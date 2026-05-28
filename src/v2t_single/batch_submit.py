import argparse
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv(override=True)

from v2t_single.clients.gemini_batch_client import (
    batch_job_to_dict,
    create_batch_job,
    upload_jsonl_file,
)
from v2t_single.clients.gemini_client import get_client


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit Gemini Batch API jobs")
    parser.add_argument("--batch-dir", required=True, help="Path to results/<batch>/batch")
    parser.add_argument("--chunk", default=None, help="Chunk stem or filename, e.g. chunk_0001")
    parser.add_argument(
        "--force-resubmit",
        action="store_true",
        help="Submit even if a job file already exists for the chunk",
    )
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False) + "\n")


def resolve_chunk_paths(batch_dir: Path, chunk: str | None) -> list[Path]:
    requests_dir = batch_dir / "requests"
    if chunk is None:
        return sorted(requests_dir.glob("*.jsonl"))

    chunk_path = Path(chunk)
    if chunk_path.suffix != ".jsonl":
        chunk_path = chunk_path.with_suffix(".jsonl")
    if not chunk_path.is_absolute():
        chunk_path = requests_dir / chunk_path.name
    if not chunk_path.exists():
        raise FileNotFoundError(f"Chunk request file not found: {chunk_path}")
    return [chunk_path]


def infer_model_from_manifest(batch_dir: Path) -> str:
    manifest_path = batch_dir / "manifest.jsonl"
    rows = load_jsonl(manifest_path)
    for row in rows:
        if row.get("model"):
            return row["model"]
    raise ValueError(f"Could not infer model from manifest: {manifest_path}")


def submit_chunk(
    batch_dir: Path,
    chunk_path: Path,
    model: str,
    force_resubmit: bool,
) -> dict[str, Any] | None:
    jobs_dir = batch_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    chunk_stem = chunk_path.stem
    job_path = jobs_dir / f"{chunk_stem}.job.json"

    if job_path.exists() and not force_resubmit:
        print(f"SKIP existing job: {job_path}")
        return None

    client = get_client(os.environ["GEMINI_API_KEY"])
    uploaded_file = upload_jsonl_file(
        client=client,
        jsonl_path=chunk_path,
        display_name=f"{chunk_stem}-batch-input",
    )
    job = create_batch_job(
        client=client,
        model=model,
        batch_input_file_name=uploaded_file.name,
        display_name=f"{chunk_stem}-batch-job",
    )

    job_payload = {
        "chunk": chunk_stem,
        "chunk_path": str(chunk_path),
        "uploaded_file_name": uploaded_file.name,
        "uploaded_file_uri": uploaded_file.uri,
        "model": model,
        "job": batch_job_to_dict(job),
        "job_name": job.name,
    }
    job_path.write_text(
        json.dumps(job_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    append_jsonl(jobs_dir / "index.jsonl", job_payload)

    print(f"Submitted {chunk_stem}: {job.name}")
    return job_payload


def main() -> None:
    args = parse_args()

    if "GEMINI_API_KEY" not in os.environ:
        raise EnvironmentError("GEMINI_API_KEY is required")

    batch_dir = Path(args.batch_dir)
    chunk_paths = resolve_chunk_paths(batch_dir, args.chunk)
    if not chunk_paths:
        raise FileNotFoundError(f"No request chunks found under {batch_dir / 'requests'}")

    model = infer_model_from_manifest(batch_dir)
    submitted = 0
    for chunk_path in chunk_paths:
        payload = submit_chunk(
            batch_dir=batch_dir,
            chunk_path=chunk_path,
            model=model,
            force_resubmit=args.force_resubmit,
        )
        if payload is not None:
            submitted += 1

    print(f"Submitted {submitted}/{len(chunk_paths)} chunks.")


if __name__ == "__main__":
    main()
