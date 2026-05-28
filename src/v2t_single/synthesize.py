"""
V2T → V2A 오디오 생성 및 영상 합성 CLI.

분석 결과(tracks.json)를 입력으로 받아,
오디오를 생성하고 원본 영상에 합성하여 최종 영상을 출력합니다.

사용법:
  uv run v2t-synthesize --tracks results/.../tracks.json --output output.mp4
  uv run v2t-synthesize --tracks results/.../tracks.json --video videos/my_video.mp4

tracks.json 내에 video_path가 포함되어 있으므로 --video를 생략할 수 있습니다.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from v2t_single.audio_client import generate_audio_for_item
from v2t_single.convert import AudioPlan, convert_tracks_to_audio_plan
from v2t_single.mix import mix_audio_into_video

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="v2t-synthesize",
        description="V2T tracks.json으로부터 오디오를 생성하고 영상에 합성합니다.",
    )
    parser.add_argument(
        "--tracks",
        required=True,
        help="v2t-pipeline이 출력한 tracks.json 파일 경로",
    )
    parser.add_argument(
        "--video",
        default=None,
        help="원본 비디오 경로 (생략 시 tracks.json 내 video_path 사용)",
    )
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        help="출력 비디오 경로 (기본: tracks.json과 같은 디렉토리에 synthesized_<timestamp>.mp4)",
    )
    parser.add_argument(
        "--keep-original-audio",
        action="store_true",
        default=False,
        help="원본 비디오의 오디오를 유지하면서 생성된 오디오를 추가 (기본: 제거 후 교체)",
    )
    parser.add_argument(
        "--onset-half-width",
        type=float,
        default=0.5,
        help="onset 타입 sound_layer의 구간 확장 반폭(초) (기본: 0.5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="오디오 생성 및 합성 없이 변환 결과(AudioPlan)만 출력",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="상세 로그 출력",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv(override=True)

    args = parse_args(argv)

    # 로깅 설정
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="[%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )

    # ── 1. tracks.json 로드 ───────────────────────────────────────────────────
    tracks_path = Path(args.tracks)
    if not tracks_path.exists():
        print(f"Error: tracks.json not found: {tracks_path}", file=sys.stderr)
        return 1

    print(f"[1/4] Loading tracks.json: {tracks_path}", file=sys.stderr)
    tracks_data = json.loads(tracks_path.read_text(encoding="utf-8"))

    # ── 2. 비디오 경로 결정 ───────────────────────────────────────────────────
    video_path = args.video
    if video_path is None:
        # tracks.json에서 video_path 추출
        video_path = tracks_data.get("video_path")
        if not video_path:
            print(
                "Error: --video not specified and tracks.json has no video_path.",
                file=sys.stderr,
            )
            return 1

    # tracks.json 옆의 videos/ 폴더에 번들된 영상 확인
    if not Path(video_path).exists():
        bundled = tracks_path.parent / "videos" / Path(video_path).name
        if bundled.exists():
            video_path = str(bundled)
            logger.info("Using bundled video: %s", video_path)
        else:
            print(
                f"Error: Video not found: {video_path}\n"
                f"  (also checked: {bundled})",
                file=sys.stderr,
            )
            return 1

    print(f"[1/4] Video: {video_path}", file=sys.stderr)

    # ── 3. V2T → AudioPlan 변환 ──────────────────────────────────────────────
    print("[2/4] Converting tracks to AudioPlan...", file=sys.stderr)
    audio_plan = convert_tracks_to_audio_plan(
        tracks_data, onset_half_width=args.onset_half_width
    )

    n_items = len(audio_plan.items)
    type_counts: dict[str, int] = {}
    for item in audio_plan.items:
        type_counts[item.type] = type_counts.get(item.type, 0) + 1

    print(
        f"  → {n_items} items created: {type_counts}",
        file=sys.stderr,
    )
    print(
        f"  → Total duration: {audio_plan.total_duration:.1f}s",
        file=sys.stderr,
    )

    if args.dry_run:
        # dry-run: AudioPlan만 JSON으로 출력하고 종료
        _print_audio_plan_json(audio_plan)
        print("[dry-run] AudioPlan printed to stdout. Exiting.", file=sys.stderr)
        return 0

    if n_items == 0:
        print("Warning: No audio items to generate.", file=sys.stderr)
        return 0

    # ── 4. 오디오 생성 ────────────────────────────────────────────────────────
    print(f"[3/4] Generating {n_items} audio tracks...", file=sys.stderr)
    audio_dir = Path(tempfile.mkdtemp(prefix="v2t_synth_audio_"))
    generated_audio: dict[str, str] = {}

    for i, item in enumerate(audio_plan.items, 1):
        if item.type == "silence":
            continue

        duration = item.time[1] - item.time[0]
        out_path = str(audio_dir / f"{item.item_id}.wav")

        desc_preview = item.description[:60] + ("..." if len(item.description) > 60 else "")
        print(
            f"  [{i}/{n_items}] {item.item_id} ({item.type}, "
            f"{item.time[0]:.1f}s-{item.time[1]:.1f}s): {desc_preview}",
            file=sys.stderr,
        )

        result_path = generate_audio_for_item(
            kind=item.type,
            description=item.description,
            out_path=out_path,
            duration=duration,
            video_path=video_path,
            time=item.time,
            generation_model=item.generation_model,
        )
        if result_path:
            generated_audio[item.item_id] = result_path

    n_generated = len(generated_audio)
    n_expected = sum(1 for item in audio_plan.items if item.type != "silence")
    print(
        f"  → Generated {n_generated}/{n_expected} audio files.",
        file=sys.stderr,
    )

    if n_generated == 0:
        print("Error: No audio files were generated.", file=sys.stderr)
        return 1

    # ── 5. 영상 합성 ──────────────────────────────────────────────────────────
    output_path = args.output
    if output_path is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(tracks_path.parent / f"synthesized_{timestamp}.mp4")

    print(f"[4/4] Mixing audio into video → {output_path}", file=sys.stderr)
    result = mix_audio_into_video(
        video_path=video_path,
        audio_plan=audio_plan,
        generated_audio=generated_audio,
        output_path=output_path,
        keep_original_audio=args.keep_original_audio,
    )

    if result:
        print(f"\n✅ Synthesis complete: {Path(result).resolve()}", file=sys.stderr)
        return 0
    else:
        print("\n❌ Synthesis failed.", file=sys.stderr)
        return 1


def _print_audio_plan_json(audio_plan: AudioPlan) -> None:
    """AudioPlan을 JSON으로 stdout에 출력."""
    import json

    data = {
        "total_duration": audio_plan.total_duration,
        "item_count": len(audio_plan.items),
        "items": [
            {
                "item_id": item.item_id,
                "type": item.type,
                "time": list(item.time),
                "description": item.description,
                "volume": item.volume,
                "intensity": item.intensity,
                "pan": item.pan,
                "confidence": item.confidence,
                "track_id": item.track_id,
            }
            for item in audio_plan.items
        ],
    }
    print(json.dumps(data, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
