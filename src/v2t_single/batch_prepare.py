import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from v2t_single.config import PipelineConfig
from v2t_single.pipeline.nodes.build_prompt import run_build_prompt
from v2t_single.pipeline.nodes.preprocessing import run_preprocessing
from v2t_single.pipeline.schema import TrackOutputModel
from v2t_single.pipeline.state import PipelineState


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare Gemini Batch API requests")
    parser.add_argument("--video", help="Path to input video file or directory")
    parser.add_argument("--recursive", action="store_true", help="Recursively search videos")
    parser.add_argument("--config", default="config.yaml", help="Path to config yaml")
    parser.add_argument("--batch-name", required=True, help="Batch result directory name")
    parser.add_argument("--chunk-size", type=int, default=200, help="Requests per JSONL chunk")
    parser.add_argument("--resume", action="store_true", help="Reuse prepared manifest entries")
    parser.add_argument("--dry-run", action="store_true", help="Do not strip/upload videos")
    parser.add_argument("--max-videos", type=int, default=None, help="Limit videos for testing")
    parser.add_argument("--retry-failed", default=None, help="failed.jsonl path to prepare retry chunks")
    return parser.parse_args()


def collect_video_paths(input_path: str, recursive: bool = False) -> list[Path]:
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Input path not found: {input_path}")
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise ValueError(f"Input path is neither file nor directory: {input_path}")

    paths = path.rglob("*") if recursive else path.glob("*")
    videos = sorted(
        item
        for item in paths
        if item.is_file() and item.suffix.lower() in VIDEO_EXTENSIONS
    )
    if not videos:
        raise FileNotFoundError(f"No video files found in directory: {input_path}")
    return videos


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_jsonl(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for payload in payloads:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return slug or "video"


def build_run_id(index: int, video_path: Path) -> str:
    return f"video_{index:06d}_{slugify(video_path.stem)}"


def build_initial_state(
    video_path: Path,
    run_id: str,
    config: PipelineConfig,
) -> PipelineState:
    return {
        "video_path": str(video_path),
        "model": config.model,
        "temperature": config.temperature,
        "seed": config.seed,
        "use_audio": config.options.use_audio,
        "input_mode": config.options.input_mode,
        "video_fps": config.options.video_fps,
        "use_scene_detect": config.options.use_scene_detect,
        "use_sound_layering": config.options.use_sound_layering,
        "prompt_profile": config.options.prompt_profile,
        "run_id": run_id,
        "errors": [],
    }


def build_batch_request(entry: dict[str, Any]) -> dict[str, Any]:
    video_part: dict[str, Any] = {
        "file_data": {
            "file_uri": entry["file_uri"],
            "mime_type": "video/mp4",
        }
    }
    if entry.get("video_fps") is not None:
        video_part["video_metadata"] = {"fps": entry["video_fps"]}

    return {
        "key": entry["key"],
        "request": {
            "contents": [
                {
                    "parts": [
                        video_part,
                        {"text": entry["user_prompt"]},
                    ],
                    "role": "user",
                }
            ],
            "system_instruction": {
                "parts": [
                    {"text": entry["system_prompt"]},
                ]
            },
            "generation_config": {
                "temperature": entry["temperature"],
                "seed": entry["seed"],
                "response_mime_type": "application/json",
                "response_json_schema": TrackOutputModel.model_json_schema(),
            },
        },
    }


def load_retry_entries(
    failed_path: Path,
    manifest_entries: list[dict[str, Any]],
    output_root: Path,
) -> list[dict[str, Any]]:
    manifest_by_key = {entry["key"]: entry for entry in manifest_entries}
    manifest_by_video = {entry["video_path"]: entry for entry in manifest_entries}
    retry_entries: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for row in load_jsonl(failed_path):
        entry = None
        if row.get("key") in manifest_by_key:
            entry = manifest_by_key[row["key"]]
        elif row.get("video_path") in manifest_by_video:
            entry = manifest_by_video[row["video_path"]]

        if entry is None:
            print(f"SKIP retry row not found in manifest: {row}")
            continue

        if entry["key"] in seen_keys:
            continue
        seen_keys.add(entry["key"])

        result_path = output_root / entry["run_id"] / "tracks.json"
        if result_path.exists():
            print(f"SKIP retry result exists: {entry['key']}")
            continue

        retry_entries.append(entry)

    return retry_entries


def prepare_entry(
    key: str,
    run_id: str,
    video_path: Path,
    output_root: Path,
    config: PipelineConfig,
    dry_run: bool,
) -> dict[str, Any]:
    state = build_initial_state(video_path, run_id, config)

    if dry_run:
        from v2t_single.tools.video_utils import (
            detect_scene_cuts,
            format_scene_cuts_for_prompt,
            get_duration,
        )

        video_duration = get_duration(str(video_path))
        scene_cuts = (
            detect_scene_cuts(str(video_path), video_duration)
            if state["use_scene_detect"]
            else []
        )
        preprocessing = {
            "video_duration": video_duration,
            "scene_cuts": scene_cuts,
            "scene_cuts_prompt": format_scene_cuts_for_prompt(scene_cuts),
            "working_video_path": str(video_path),
            "file_uri": f"dry-run://{key}",
            "file_name": f"dry-run/{key}",
        }
    else:
        preprocessing = run_preprocessing(state)

    state.update(preprocessing)
    prompt_info = run_build_prompt(state)
    state.update(prompt_info)

    return {
        "key": key,
        "status": "prepared",
        "video_path": str(video_path),
        "run_id": run_id,
        "output_root": str(output_root),
        "video_duration": state["video_duration"],
        "scene_cuts": state.get("scene_cuts", []),
        "scene_cuts_prompt": state.get("scene_cuts_prompt"),
        "working_video_path": state["working_video_path"],
        "file_uri": state["file_uri"],
        "file_name": state["file_name"],
        "model": state["model"],
        "temperature": state["temperature"],
        "seed": state["seed"],
        "use_audio": state["use_audio"],
        "input_mode": state["input_mode"],
        "video_fps": state["video_fps"],
        "use_scene_detect": state["use_scene_detect"],
        "use_sound_layering": state["use_sound_layering"],
        "prompt_profile": state["prompt_profile"],
        "system_prompt": state["system_prompt"],
        "user_prompt": state["user_prompt"],
    }


def write_request_chunks(
    batch_dir: Path,
    entries: list[dict[str, Any]],
    chunk_size: int,
    retry_mode: bool,
) -> None:
    requests_dir = batch_dir / "requests"
    prefix = "retry" if retry_mode else "chunk"

    for index in range(0, len(entries), chunk_size):
        chunk_number = (index // chunk_size) + 1
        chunk_entries = entries[index : index + chunk_size]
        request_rows = [build_batch_request(entry) for entry in chunk_entries]
        request_path = requests_dir / f"{prefix}_{chunk_number:04d}.jsonl"
        write_jsonl(request_path, request_rows)
        print(f"Wrote {len(request_rows)} requests: {request_path}")


def main() -> None:
    load_dotenv()
    args = parse_args()

    if args.chunk_size <= 0:
        raise ValueError("--chunk-size must be greater than 0")
    if not args.video and not args.retry_failed:
        raise ValueError("Provide either --video or --retry-failed")
    if not args.dry_run and "GEMINI_API_KEY" not in os.environ:
        raise EnvironmentError("GEMINI_API_KEY is required unless --dry-run is used")

    config = PipelineConfig.from_yaml(args.config)
    output_root = Path(config.output_dir) / args.batch_name
    batch_dir = output_root / "batch"
    manifest_path = batch_dir / "manifest.jsonl"

    if manifest_path.exists() and not args.resume:
        raise FileExistsError(
            f"Manifest already exists: {manifest_path}. Use --resume to reuse it."
        )

    batch_dir.mkdir(parents=True, exist_ok=True)
    existing_entries = load_jsonl(manifest_path) if args.resume else []
    existing_by_video = {entry["video_path"]: entry for entry in existing_entries}

    retry_mode = args.retry_failed is not None
    if retry_mode:
        if not existing_entries:
            raise FileNotFoundError(
                f"Retry requires an existing manifest. Use --resume with {manifest_path}."
            )
        prepared_entries = load_retry_entries(
            failed_path=Path(args.retry_failed),
            manifest_entries=existing_entries,
            output_root=output_root,
        )
        if args.max_videos is not None:
            prepared_entries = prepared_entries[: args.max_videos]
        if not prepared_entries:
            print("No retry entries to write.")
            return
        write_request_chunks(
            batch_dir=batch_dir,
            entries=prepared_entries,
            chunk_size=args.chunk_size,
            retry_mode=True,
        )
        print(f"Prepared {len(prepared_entries)} retry entries in {batch_dir}")
        return

    video_paths = collect_video_paths(args.video, recursive=args.recursive)
    if args.max_videos is not None:
        video_paths = video_paths[: args.max_videos]

    prepared_entries: list[dict[str, Any]] = []
    total = len(video_paths)

    for index, video_path in enumerate(video_paths, start=1):
        run_id = build_run_id(index, video_path)
        result_path = output_root / run_id / "tracks.json"

        if result_path.exists():
            print(f"[{index}/{total}] SKIP result exists: {video_path}")
            continue

        existing = existing_by_video.get(str(video_path))
        if existing and existing.get("status") == "prepared" and existing.get("file_uri"):
            print(f"[{index}/{total}] REUSE prepared: {video_path}")
            prepared_entries.append(existing)
            continue

        key = f"video_{index:06d}" if not retry_mode else f"retry_{index:06d}"
        print(f"[{index}/{total}] Preparing: {video_path}")
        entry = prepare_entry(
            key=key,
            run_id=run_id,
            video_path=video_path,
            output_root=output_root,
            config=config,
            dry_run=args.dry_run,
        )
        append_jsonl(manifest_path, entry)
        prepared_entries.append(entry)

    if not prepared_entries:
        print("No entries to write.")
        return

    write_request_chunks(
        batch_dir=batch_dir,
        entries=prepared_entries,
        chunk_size=args.chunk_size,
        retry_mode=retry_mode,
    )

    print(f"Prepared {len(prepared_entries)} entries in {batch_dir}")


if __name__ == "__main__":
    main()
