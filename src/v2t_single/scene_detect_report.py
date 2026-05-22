import argparse
import html
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from v2t_single.tools.video_utils import detect_scene_cuts, format_scene_cuts_for_prompt, get_duration


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}
SCENE_DETECT_PRESETS = {
    "high_recall": {"threshold": 27.0, "min_scene_len": 1},
    "balanced": {"threshold": 35.0, "min_scene_len": 6},
    "conservative": {"threshold": 45.0, "min_scene_len": 12},
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run PySceneDetect only and build an HTML cut-clip report."
    )
    parser.add_argument("--video", required=True, help="Path to a video file or directory")
    parser.add_argument(
        "--output-dir",
        default="results/scene_detect",
        help="Directory where scene-detect reports are written",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively search videos when --video is a directory",
    )
    parser.add_argument(
        "--preset",
        choices=sorted(SCENE_DETECT_PRESETS),
        default="balanced",
        help="Scene detection sensitivity preset",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Override PySceneDetect ContentDetector threshold",
    )
    parser.add_argument(
        "--min-scene-len",
        type=int,
        default=None,
        help="Override minimum scene length in frames",
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=None,
        help="Limit number of videos when --video is a directory",
    )
    parser.add_argument(
        "--skip-clips",
        action="store_true",
        help="Only write metadata/report without exporting per-cut clip files",
    )
    return parser.parse_args()


def collect_video_paths(input_path: str, recursive: bool) -> list[Path]:
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Input path not found: {input_path}")
    if path.is_file():
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError(f"Unsupported video extension: {path.suffix}")
        return [path]
    if not path.is_dir():
        raise ValueError(f"Input path is neither file nor directory: {input_path}")

    paths = path.rglob("*") if recursive else path.glob("*")
    videos = sorted(
        item for item in paths
        if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS
    )
    if not videos:
        raise FileNotFoundError(f"No video files found in directory: {input_path}")
    return videos


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return slug or "video"


def format_seconds(value: float) -> str:
    minutes, seconds = divmod(value, 60.0)
    return f"{int(minutes):02d}:{seconds:06.3f}"


def run_ffmpeg_clip(video_path: Path, clip_path: Path, start: float, end: float) -> None:
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.001, end - start)
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(video_path),
        "-t",
        f"{duration:.3f}",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        "-avoid_negative_ts",
        "make_zero",
        "-y",
        str(clip_path),
    ]
    subprocess.run(command, check=True)


def export_cut_clips(
    video_path: Path,
    cuts: list[dict[str, Any]],
    report_dir: Path,
    skip_clips: bool,
) -> list[dict[str, Any]]:
    clips_dir = report_dir / "clips"
    exported: list[dict[str, Any]] = []

    for cut in cuts:
        clip_name = f"{cut['cut_id']}.mp4"
        clip_path = clips_dir / clip_name
        if not skip_clips:
            run_ffmpeg_clip(
                video_path=video_path,
                clip_path=clip_path,
                start=float(cut["start"]),
                end=float(cut["end"]),
            )
        exported.append({**cut, "clip_path": f"clips/{clip_name}"})

    return exported


def build_timeline(cuts: list[dict[str, Any]], duration: float) -> str:
    if duration <= 0:
        return ""

    pieces = []
    for index, cut in enumerate(cuts):
        start = float(cut["start"])
        end = float(cut["end"])
        width = max(0.25, ((end - start) / duration) * 100)
        tone = "#2563eb" if index % 2 == 0 else "#0891b2"
        pieces.append(
            f'<div class="timeline-cut" style="width: {width:.4f}%; background: {tone};" '
            f'title="{html.escape(cut["cut_id"])} {start:.3f}s-{end:.3f}s"></div>'
        )
    return "\n".join(pieces)


def build_cut_cards(cuts: list[dict[str, Any]], skip_clips: bool) -> str:
    cards = []
    for cut in cuts:
        start = float(cut["start"])
        end = float(cut["end"])
        duration = end - start
        video_html = ""
        if not skip_clips:
            video_html = (
                f'<video controls preload="metadata" src="{html.escape(cut["clip_path"])}"></video>'
            )
        cards.append(f"""
        <article class="cut-card">
          <div class="cut-meta">
            <h2>{html.escape(cut['cut_id'])}</h2>
            <dl>
              <div><dt>Start</dt><dd>{start:.3f}s</dd></div>
              <div><dt>End</dt><dd>{end:.3f}s</dd></div>
              <div><dt>Duration</dt><dd>{duration:.3f}s</dd></div>
            </dl>
          </div>
          {video_html}
        </article>
        """)
    return "\n".join(cards)


def build_html(
    video_path: Path,
    duration: float,
    cuts: list[dict[str, Any]],
    preset: str,
    threshold: float,
    min_scene_len: int,
    skip_clips: bool,
) -> str:
    escaped_name = html.escape(video_path.name)
    original_src = html.escape(video_path.resolve().as_uri())
    timeline = build_timeline(cuts, duration)
    cards = build_cut_cards(cuts, skip_clips)
    cuts_prompt = html.escape(format_scene_cuts_for_prompt(cuts))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Scene Detect Report - {escaped_name}</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #172033;
      background: #f6f7f9;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; }}
    header {{
      padding: 28px 32px 22px;
      background: #ffffff;
      border-bottom: 1px solid #d9dee7;
    }}
    main {{ padding: 24px 32px 40px; }}
    h1 {{ margin: 0 0 14px; font-size: 28px; font-weight: 750; }}
    h2 {{ margin: 0; font-size: 18px; }}
    .summary {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 14px; }}
    .pill {{
      border: 1px solid #cfd6e3;
      background: #f8fafc;
      border-radius: 6px;
      padding: 8px 10px;
      font-size: 13px;
    }}
    .source {{
      display: grid;
      grid-template-columns: minmax(280px, 720px) minmax(240px, 1fr);
      gap: 20px;
      align-items: start;
      margin-bottom: 22px;
    }}
    video {{ width: 100%; background: #0f172a; border-radius: 6px; display: block; }}
    pre {{
      margin: 0;
      padding: 14px;
      min-height: 160px;
      overflow: auto;
      border: 1px solid #d5dbe6;
      border-radius: 6px;
      background: #ffffff;
      font-size: 12px;
      line-height: 1.5;
      white-space: pre-wrap;
    }}
    .timeline {{
      display: flex;
      width: 100%;
      height: 22px;
      overflow: hidden;
      border-radius: 6px;
      border: 1px solid #cbd5e1;
      background: #e2e8f0;
      margin: 8px 0 24px;
    }}
    .timeline-cut {{ height: 100%; border-right: 1px solid rgba(255,255,255,.7); }}
    .cuts {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }}
    .cut-card {{
      background: #ffffff;
      border: 1px solid #d9dee7;
      border-radius: 8px;
      padding: 14px;
    }}
    .cut-card video {{ margin-top: 12px; aspect-ratio: 16 / 9; object-fit: contain; }}
    dl {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 10px 0 0; }}
    dt {{ color: #64748b; font-size: 11px; text-transform: uppercase; }}
    dd {{ margin: 3px 0 0; font-size: 13px; font-weight: 650; }}
    @media (max-width: 860px) {{
      header, main {{ padding-left: 18px; padding-right: 18px; }}
      .source {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>{escaped_name}</h1>
    <div class="summary">
      <div class="pill">Duration: {duration:.3f}s ({format_seconds(duration)})</div>
      <div class="pill">Cuts: {len(cuts)}</div>
      <div class="pill">Detector: ContentDetector</div>
      <div class="pill">Preset: {html.escape(preset)}</div>
      <div class="pill">Threshold: {threshold}</div>
      <div class="pill">min_scene_len: {min_scene_len} frame(s)</div>
    </div>
  </header>
  <main>
    <section class="source">
      <video controls preload="metadata" src="{original_src}"></video>
      <pre>{cuts_prompt}</pre>
    </section>
    <section class="timeline" aria-label="Scene cut timeline">
      {timeline}
    </section>
    <section class="cuts">
      {cards}
    </section>
  </main>
</body>
</html>
"""


def write_report(
    video_path: Path,
    report_dir: Path,
    preset: str,
    threshold: float,
    min_scene_len: int,
    skip_clips: bool,
) -> Path:
    duration = get_duration(str(video_path))
    cuts = detect_scene_cuts(
        str(video_path),
        duration,
        threshold=threshold,
        min_scene_len=min_scene_len,
    )
    cuts_with_clips = export_cut_clips(
        video_path=video_path,
        cuts=cuts,
        report_dir=report_dir,
        skip_clips=skip_clips,
    )

    metadata = {
        "video_path": str(video_path.resolve()),
        "video_duration": duration,
        "detector": "ContentDetector",
        "preset": preset,
        "threshold": threshold,
        "min_scene_len": min_scene_len,
        "scene_cuts": cuts_with_clips,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "scene_cuts.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report_html = report_dir / "report.html"
    report_html.write_text(
        build_html(
            video_path=video_path,
            duration=duration,
            cuts=cuts_with_clips,
            preset=preset,
            threshold=threshold,
            min_scene_len=min_scene_len,
            skip_clips=skip_clips,
        ),
        encoding="utf-8",
    )
    return report_html


def write_index(output_root: Path, reports: list[tuple[Path, Path]]) -> Path:
    links = []
    for video_path, report_path in reports:
        rel = report_path.relative_to(output_root).as_posix()
        links.append(
            f'<li><a href="{html.escape(rel)}">{html.escape(video_path.name)}</a></li>'
        )
    index_html = output_root / "index.html"
    index_html.write_text(f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Scene Detect Reports</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 32px; color: #172033; }}
    li {{ margin: 8px 0; }}
  </style>
</head>
<body>
  <h1>Scene Detect Reports</h1>
  <ul>{''.join(links)}</ul>
</body>
</html>
""", encoding="utf-8")
    return index_html


def main() -> None:
    args = parse_args()
    preset_values = SCENE_DETECT_PRESETS[args.preset]
    threshold = args.threshold if args.threshold is not None else preset_values["threshold"]
    min_scene_len = (
        args.min_scene_len
        if args.min_scene_len is not None
        else preset_values["min_scene_len"]
    )

    if min_scene_len <= 0:
        raise ValueError("--min-scene-len must be positive")
    if threshold <= 0:
        raise ValueError("--threshold must be positive")
    if args.max_videos is not None and args.max_videos <= 0:
        raise ValueError("--max-videos must be positive")

    video_paths = collect_video_paths(args.video, recursive=args.recursive)
    if args.max_videos is not None:
        video_paths = video_paths[: args.max_videos]

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_root = Path(args.output_dir) / run_id
    output_root.mkdir(parents=True, exist_ok=True)

    reports: list[tuple[Path, Path]] = []
    total = len(video_paths)
    for index, video_path in enumerate(video_paths, start=1):
        report_dir = output_root / f"{index:04d}_{slugify(video_path.stem)}"
        print(f"[{index}/{total}] Scene detecting: {video_path}", flush=True)
        report_html = write_report(
            video_path=video_path,
            report_dir=report_dir,
            preset=args.preset,
            threshold=threshold,
            min_scene_len=min_scene_len,
            skip_clips=args.skip_clips,
        )
        reports.append((video_path, report_html))
        print(f"  Report: {report_html.resolve()}", flush=True)

    if len(reports) > 1:
        index_html = write_index(output_root, reports)
        print(f"Index: {index_html.resolve()}")
    else:
        print(f"Report: {reports[0][1].resolve()}")


if __name__ == "__main__":
    main()
