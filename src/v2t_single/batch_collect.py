import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv(override=True)
from pydantic import ValidationError

from v2t_single.clients.gemini_batch_client import (
    batch_job_to_dict,
    download_batch_output,
    extract_batch_error,
    extract_batch_line_key,
    extract_batch_response_text,
    get_batch_job,
)
from v2t_single.clients.gemini_client import get_client
from v2t_single.pipeline.nodes.track_extraction import attach_track_ids
from v2t_single.pipeline.reporting import save_run_artifacts
from v2t_single.pipeline.schema import TrackOutputModel
from v2t_single.pipeline.state import PipelineState


TERMINAL_STATES = {
    "JOB_STATE_SUCCEEDED",
    "JOB_STATE_FAILED",
    "JOB_STATE_CANCELLED",
    "JOB_STATE_EXPIRED",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Gemini Batch API results")
    parser.add_argument("--batch-dir", required=True, help="Path to results/<batch>/batch")
    parser.add_argument("--chunk", default=None, help="Chunk stem, e.g. chunk_0001")
    parser.add_argument("--poll", action="store_true", help="Poll until terminal state")
    parser.add_argument("--poll-interval", type=int, default=60, help="Polling interval seconds")
    return parser.parse_args()


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


def resolve_job_files(batch_dir: Path, chunk: str | None) -> list[Path]:
    jobs_dir = batch_dir / "jobs"
    if chunk is None:
        return sorted(jobs_dir.glob("*.job.json"))

    chunk_path = Path(chunk)
    if chunk_path.suffix != ".json":
        chunk_path = jobs_dir / f"{chunk_path.stem}.job.json"
    elif not chunk_path.is_absolute():
        chunk_path = jobs_dir / chunk_path.name
    if not chunk_path.exists():
        raise FileNotFoundError(f"Job file not found: {chunk_path}")
    return [chunk_path]


def get_job_state_name(job) -> str:
    state = getattr(job, "state", None)
    if state is None:
        return "JOB_STATE_UNSPECIFIED"
    return getattr(state, "name", str(state))


def get_dest_file_name(job, job_dict: dict[str, Any]) -> str | None:
    dest = getattr(job, "dest", None)
    file_name = getattr(dest, "file_name", None)
    if file_name:
        return file_name

    dict_dest = job_dict.get("dest")
    if isinstance(dict_dest, dict):
        return dict_dest.get("file_name") or dict_dest.get("fileName")
    return None


def wait_for_terminal_job(client, job_name: str, poll: bool, poll_interval: int):
    while True:
        job = get_batch_job(client, job_name)
        state_name = get_job_state_name(job)
        print(f"{job_name}: {state_name}")
        if state_name in TERMINAL_STATES or not poll:
            return job
        time.sleep(poll_interval)


def build_state_from_manifest_entry(
    entry: dict[str, Any],
    raw_json_payload: str,
    validated_dict: dict[str, Any],
) -> PipelineState:
    return {
        "video_path": entry["video_path"],
        "model": entry["model"],
        "temperature": entry["temperature"],
        "seed": entry["seed"],
        "use_audio": entry["use_audio"],
        "input_mode": entry["input_mode"],
        "video_fps": entry["video_fps"],
        "use_scene_detect": entry.get("use_scene_detect", False),
        "use_sound_layering": entry["use_sound_layering"],
        "prompt_profile": entry["prompt_profile"],
        "video_duration": entry["video_duration"],
        "scene_cuts": entry.get("scene_cuts", []),
        "scene_cuts_prompt": entry.get("scene_cuts_prompt"),
        "working_video_path": entry["working_video_path"],
        "file_uri": entry["file_uri"],
        "file_name": entry["file_name"],
        "raw_json_payload": raw_json_payload,
        "action_tracks": validated_dict["action_tracks"],
        "background_tracks": validated_dict["background_tracks"],
        "run_id": entry["run_id"],
        "errors": [],
    }


def result_exists(entry: dict[str, Any]) -> bool:
    return (Path(entry["output_root"]) / entry["run_id"] / "tracks.json").exists()


def process_output_line(
    line_payload: dict[str, Any],
    manifest_by_key: dict[str, dict[str, Any]],
    batch_dir: Path,
    chunk: str,
) -> bool:
    key = extract_batch_line_key(line_payload)
    if key is None:
        append_jsonl(
            batch_dir / "failed.jsonl",
            {
                "stage": "collect",
                "chunk": chunk,
                "error": "missing batch output key",
                "payload": line_payload,
            },
        )
        return False

    entry = manifest_by_key.get(key)
    if entry is None:
        append_jsonl(
            batch_dir / "failed.jsonl",
            {
                "stage": "collect",
                "chunk": chunk,
                "key": key,
                "error": "key not found in manifest",
                "payload": line_payload,
            },
        )
        return False

    if result_exists(entry):
        print(f"SKIP existing result: {key}")
        return True

    line_error = extract_batch_error(line_payload)
    if line_error is not None:
        append_jsonl(
            batch_dir / "failed.jsonl",
            {
                "stage": "batch_response",
                "chunk": chunk,
                "key": key,
                "video_path": entry["video_path"],
                "error": line_error,
            },
        )
        return False

    try:
        response_text = extract_batch_response_text(line_payload)
        structured_output = TrackOutputModel.model_validate_json(response_text)
        validated_dict = attach_track_ids(structured_output.model_dump())
        state = build_state_from_manifest_entry(
            entry=entry,
            raw_json_payload=response_text,
            validated_dict=validated_dict,
        )
        save_run_artifacts(state, entry["output_root"])
        print(f"SAVED {key}: {entry['run_id']}")
        return True
    except (ValidationError, ValueError, KeyError) as exc:
        append_jsonl(
            batch_dir / "failed.jsonl",
            {
                "stage": "validation",
                "chunk": chunk,
                "key": key,
                "video_path": entry["video_path"],
                "error": str(exc),
                "payload": line_payload,
            },
        )
        return False


def collect_job(
    batch_dir: Path,
    job_path: Path,
    manifest_by_key: dict[str, dict[str, Any]],
    poll: bool,
    poll_interval: int,
) -> tuple[int, int]:
    client = get_client(os.environ["GEMINI_API_KEY"])
    job_payload = json.loads(job_path.read_text(encoding="utf-8"))
    job_name = job_payload["job_name"]
    chunk = job_payload["chunk"]

    job = wait_for_terminal_job(client, job_name, poll=poll, poll_interval=poll_interval)
    job_dict = batch_job_to_dict(job)
    state_name = get_job_state_name(job)

    job_payload["latest_job"] = job_dict
    job_payload["latest_state"] = state_name
    job_path.write_text(
        json.dumps(job_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if state_name != "JOB_STATE_SUCCEEDED":
        if state_name in TERMINAL_STATES:
            append_jsonl(
                batch_dir / "job_failures.jsonl",
                {
                    "chunk": chunk,
                    "job_name": job_name,
                    "state": state_name,
                    "job": job_dict,
                },
            )
        return 0, 0

    output_file_name = get_dest_file_name(job, job_dict)
    if not output_file_name:
        append_jsonl(
            batch_dir / "job_failures.jsonl",
            {
                "chunk": chunk,
                "job_name": job_name,
                "state": state_name,
                "error": "succeeded job has no output file",
                "job": job_dict,
            },
        )
        return 0, 0

    outputs_dir = batch_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    output_path = outputs_dir / f"{chunk}.results.jsonl"

    if not output_path.exists():
        output_text = download_batch_output(client, output_file_name)
        output_path.write_text(output_text, encoding="utf-8")
        print(f"Downloaded output: {output_path}")

    rows = load_jsonl(output_path)
    success = 0
    failed = 0
    for row in rows:
        if process_output_line(row, manifest_by_key, batch_dir, chunk):
            success += 1
        else:
            failed += 1
    return success, failed


def main() -> None:
    args = parse_args()

    if "GEMINI_API_KEY" not in os.environ:
        raise EnvironmentError("GEMINI_API_KEY is required")

    batch_dir = Path(args.batch_dir)
    manifest_rows = load_jsonl(batch_dir / "manifest.jsonl")
    manifest_by_key = {row["key"]: row for row in manifest_rows}
    job_files = resolve_job_files(batch_dir, args.chunk)

    total_success = 0
    total_failed = 0
    for job_path in job_files:
        success, failed = collect_job(
            batch_dir=batch_dir,
            job_path=job_path,
            manifest_by_key=manifest_by_key,
            poll=args.poll,
            poll_interval=args.poll_interval,
        )
        total_success += success
        total_failed += failed

    print(f"Collected jobs={len(job_files)} success={total_success} failed={total_failed}")


if __name__ == "__main__":
    main()
