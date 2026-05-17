import json
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types


def upload_jsonl_file(
    client: genai.Client,
    jsonl_path: str | Path,
    display_name: str,
) -> types.File:
    """Upload a JSONL file for Gemini Batch API input."""
    return client.files.upload(
        file=str(jsonl_path),
        config=types.UploadFileConfig(
            display_name=display_name,
            mime_type="jsonl",
        ),
    )


def create_batch_job(
    client: genai.Client,
    model: str,
    batch_input_file_name: str,
    display_name: str,
) -> types.BatchJob:
    """Create a Gemini Batch API job from an uploaded JSONL input file."""
    return client.batches.create(
        model=model,
        src=batch_input_file_name,
        config=types.CreateBatchJobConfig(display_name=display_name),
    )


def get_batch_job(client: genai.Client, job_name: str) -> types.BatchJob:
    """Fetch a Gemini Batch API job by name."""
    return client.batches.get(name=job_name)


def download_batch_output(client: genai.Client, output_file_name: str) -> str:
    """Download a Gemini Batch API output JSONL file as UTF-8 text."""
    content = client.files.download(file=output_file_name)
    return content.decode("utf-8")


def batch_job_to_dict(job: types.BatchJob) -> dict[str, Any]:
    """Serialize SDK batch job objects to plain JSON-compatible dictionaries."""
    if hasattr(job, "model_dump"):
        return job.model_dump(mode="json", exclude_none=True)
    return json.loads(job.model_dump_json(exclude_none=True))


def extract_batch_line_key(line_payload: dict[str, Any]) -> str | None:
    """Return the user-defined key from a Batch API output line."""
    key = line_payload.get("key")
    if key is not None:
        return str(key)

    metadata = line_payload.get("metadata")
    if isinstance(metadata, dict) and metadata.get("key") is not None:
        return str(metadata["key"])

    return None


def extract_batch_response_text(line_payload: dict[str, Any]) -> str:
    """Extract generated text from a Batch API output JSON object."""
    response = line_payload.get("response", line_payload)

    text = response.get("text")
    if isinstance(text, str) and text:
        return text

    candidates = response.get("candidates", [])
    for candidate in candidates:
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            part_text = part.get("text")
            if isinstance(part_text, str) and part_text:
                return part_text

    raise ValueError("Batch output line does not contain response text")


def extract_batch_error(line_payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return per-request error/status payload when a Batch API output line failed."""
    if "error" in line_payload:
        return line_payload["error"]
    if "status" in line_payload:
        return line_payload["status"]
    return None
