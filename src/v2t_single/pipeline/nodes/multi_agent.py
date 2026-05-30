import copy
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from typing import Callable, TypeVar

from pydantic import BaseModel, ValidationError

from v2t_single.clients.gemini_client import generate_json_response
from v2t_single.pipeline.nodes.track_extraction import attach_track_and_layer_ids
from v2t_single.pipeline.schema import (
    DraftTrackOutputModel,
    GenerationModel,
    TimestampRefinementModel,
    TimestampTaskModel,
    TrackOutputModel,
    strip_draft_layer_metadata,
)
from v2t_single.pipeline.state import PipelineState
from v2t_single.prompts.multi_agent import (
    INVENTORY_SYSTEM_PROMPT,
    INVENTORY_USER_PROMPT,
    REPEATED_EVENT_REFINEMENT_SYSTEM_PROMPT,
    REPEATED_EVENT_REFINEMENT_USER_PROMPT,
    SINGLE_EVENT_REFINEMENT_SYSTEM_PROMPT,
    SINGLE_EVENT_REFINEMENT_USER_PROMPT,
)


ModelT = TypeVar("ModelT", bound=BaseModel)

_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}


def _format_offset(seconds: float) -> str:
    return f"{seconds:.3f}s"


def _render_inventory_prompt(state: PipelineState) -> str:
    return (
        INVENTORY_USER_PROMPT
        .replace("__DURATION__", f"{state['video_duration']:.3f}")
        .replace("__CUTS__", state.get("scene_cuts_prompt", "No external cut boundaries detected."))
    )


def _render_timestamp_prompt(
    task: TimestampTaskModel,
    parent_track: dict,
    layer: dict,
) -> str:
    parent_label = parent_track.get("event_type") or parent_track.get("ambience_type") or "unknown_track"
    prompt_template = (
        SINGLE_EVENT_REFINEMENT_USER_PROMPT
        if task.timing_strategy == "single_event"
        else REPEATED_EVENT_REFINEMENT_USER_PROMPT
    )
    return (
        prompt_template
        .replace("__WINDOW_START__", f"{task.start:.3f}")
        .replace("__WINDOW_END__", f"{task.end:.3f}")
        .replace("__COARSE_EVENT_TIME__", _format_optional_time(layer.get("coarse_event_time")))
        .replace("__LAYER_LABEL__", layer["layer_label"])
        .replace("__LAYER_DESCRIPTION__", layer["description"])
        .replace("__PARENT_LABEL__", parent_label)
        .replace("__PARENT_DESCRIPTION__", parent_track["description"])
    )


def _format_optional_time(value: float | None) -> str:
    if value is None:
        return "not provided"
    return f"{value:.3f} seconds"


def _timestamp_system_prompt(task: TimestampTaskModel) -> str:
    if task.timing_strategy == "single_event":
        return SINGLE_EVENT_REFINEMENT_SYSTEM_PROMPT
    return REPEATED_EVENT_REFINEMENT_SYSTEM_PROMPT


def _with_validation_retry(
    call: Callable[[str | None], ModelT],
    validate: Callable[[ModelT], None],
    retry_count: int,
) -> ModelT:
    last_error: Exception | None = None
    for attempt in range(retry_count + 1):
        correction = None if attempt == 0 else str(last_error)
        try:
            model = call(correction)
            validate(model)
            return model
        except (ValidationError, ValueError) as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def _append_correction(user_prompt: str, correction: str | None) -> str:
    if correction is None:
        return user_prompt
    return (
        f"{user_prompt}\n\n"
        "Your previous JSON failed validation. Regenerate the full JSON and fix this issue:\n"
        f"{correction}"
    )


def _track_segments(track: dict) -> list[dict[str, float]]:
    return track.get("segments", [])


def _layer_coarse_segments(track: dict, layer: dict) -> list[dict[str, float]]:
    if layer.get("sound_type") == "continuous":
        return layer.get("segments", [])
    return layer.get("coarse_segments") or _track_segments(track)


def _is_inside_any_segment(value: float, segments: list[dict[str, float]]) -> bool:
    return any(segment["start"] <= value <= segment["end"] for segment in segments)


def _validate_inventory_model(model: DraftTrackOutputModel, video_duration: float) -> None:
    draft = model.model_dump(mode="json")
    for track_kind in ("action_tracks", "background_tracks"):
        for track in draft[track_kind]:
            for segment in track["segments"]:
                if segment["end"] > video_duration:
                    raise ValueError("track segment must be inside video duration")
            for layer in track["sound_layers"]:
                if layer["sound_type"] == "onset" and layer["timing_strategy"] == "single_event":
                    coarse_segments = _layer_coarse_segments(track, layer)
                    max_segment_duration = max(
                        segment["end"] - segment["start"]
                        for segment in coarse_segments
                    )
                    if layer.get("coarse_event_time") is None and max_segment_duration > 3.0:
                        raise ValueError(
                            "single_event layer needs coarse_event_time unless its coarse segment is <= 3 seconds"
                        )


def _clamp_window(start: float, end: float, duration: float) -> tuple[float, float]:
    clamped_start = max(0.0, start)
    clamped_end = min(duration, end)
    if clamped_end <= clamped_start:
        raise ValueError("timestamp task window is empty after clamping")
    return clamped_start, clamped_end


def _make_single_event_task(
    task_id: str,
    track_kind: str,
    track_index: int,
    layer_index: int,
    track: dict,
    layer: dict,
    duration: float,
    padding: float,
    fps: float,
) -> TimestampTaskModel:
    coarse_segments = _layer_coarse_segments(track, layer)
    coarse_event_time = layer.get("coarse_event_time")
    if coarse_event_time is None:
        segment = max(coarse_segments, key=lambda item: item["end"] - item["start"])
        coarse_event_time = (segment["start"] + segment["end"]) / 2
    start, end = _clamp_window(
        coarse_event_time - padding,
        coarse_event_time + padding,
        duration,
    )
    return TimestampTaskModel(
        task_id=task_id,
        track_kind=track_kind,
        track_index=track_index,
        layer_index=layer_index,
        timing_strategy="single_event",
        start=start,
        end=end,
        fps=fps,
        layer_label=layer["layer_label"],
    )


def _make_repeated_event_tasks(
    task_prefix: str,
    track_kind: str,
    track_index: int,
    layer_index: int,
    track: dict,
    layer: dict,
    duration: float,
    chunk_seconds: float,
    overlap_seconds: float,
    fps: float,
) -> list[TimestampTaskModel]:
    tasks: list[TimestampTaskModel] = []
    task_number = 1
    for segment in _layer_coarse_segments(track, layer):
        segment_start, segment_end = _clamp_window(segment["start"], segment["end"], duration)
        cursor = segment_start
        while cursor < segment_end:
            end = min(segment_end, cursor + chunk_seconds)
            tasks.append(
                TimestampTaskModel(
                    task_id=f"{task_prefix}_{task_number:03d}",
                    track_kind=track_kind,
                    track_index=track_index,
                    layer_index=layer_index,
                    timing_strategy="repeated_event",
                    start=cursor,
                    end=end,
                    fps=fps,
                    layer_label=layer["layer_label"],
                )
            )
            task_number += 1
            if end >= segment_end:
                break
            cursor = max(cursor + 0.001, end - overlap_seconds)
    return tasks


def build_timestamp_tasks(
    draft_tracks: dict,
    duration: float,
    refinement_fps: float,
    single_event_padding_seconds: float,
    repeated_chunk_seconds: float,
    chunk_overlap_seconds: float,
) -> list[dict]:
    tasks: list[TimestampTaskModel] = []
    for track_kind in ("action_tracks", "background_tracks"):
        for track_index, track in enumerate(draft_tracks[track_kind]):
            for layer_index, layer in enumerate(track["sound_layers"]):
                timing_strategy = layer["timing_strategy"]
                task_prefix = f"{track_kind}_{track_index:03d}_layer_{layer_index:03d}"
                if timing_strategy == "continuous":
                    continue
                if timing_strategy == "single_event":
                    tasks.append(
                        _make_single_event_task(
                            task_id=task_prefix,
                            track_kind="action" if track_kind == "action_tracks" else "background",
                            track_index=track_index,
                            layer_index=layer_index,
                            track=track,
                            layer=layer,
                            duration=duration,
                            padding=single_event_padding_seconds,
                            fps=refinement_fps,
                        )
                    )
                elif timing_strategy == "repeated_event":
                    tasks.extend(
                        _make_repeated_event_tasks(
                            task_prefix=task_prefix,
                            track_kind="action" if track_kind == "action_tracks" else "background",
                            track_index=track_index,
                            layer_index=layer_index,
                            track=track,
                            layer=layer,
                            duration=duration,
                            chunk_seconds=repeated_chunk_seconds,
                            overlap_seconds=chunk_overlap_seconds,
                            fps=refinement_fps,
                        )
                    )
    return [task.model_dump(mode="json") for task in tasks]


def _task_track_key(task: dict) -> str:
    return "action_tracks" if task["track_kind"] == "action" else "background_tracks"


def _merge_onsets(onsets: list[float], tolerance: float) -> list[float]:
    if not onsets:
        return []
    sorted_onsets = sorted(onsets)
    merged = [sorted_onsets[0]]
    for onset in sorted_onsets[1:]:
        if onset - merged[-1] <= tolerance:
            merged[-1] = (merged[-1] + onset) / 2
        else:
            merged.append(onset)
    return [round(value, 3) for value in merged]


def _validate_refinement(
    refinement: TimestampRefinementModel,
    task: TimestampTaskModel,
    track: dict,
    layer: dict,
) -> None:
    onsets = refinement.onsets
    if task.timing_strategy == "single_event" and len(onsets) != 1:
        raise ValueError("single_event refinement must return exactly one onset")
    layer_segments = _layer_coarse_segments(track, layer)
    for onset in onsets:
        if not task.start <= onset <= task.end:
            raise ValueError("refined onset must be inside task window")
        if not _is_inside_any_segment(onset, track["segments"]):
            raise ValueError("refined onset must be inside parent track segments")
        if not _is_inside_any_segment(onset, layer_segments):
            raise ValueError("refined onset must be inside layer coarse segments")


def _merge_confidences(confidences: list[str]) -> str:
    return max(confidences, key=lambda value: _CONFIDENCE_RANK.get(value, 1))


def route_layer(track_kind: str, layer: dict) -> tuple[GenerationModel, str]:
    timing_strategy = layer["timing_strategy"]
    timing_confidence = layer.get("timing_confidence", "medium")
    sync_sensitivity = layer.get("sync_sensitivity", "medium")
    onset_count = len(layer.get("onsets", []))
    timing_segments = layer.get("coarse_segments") or layer.get("segments") or []
    duration = sum(
        segment["end"] - segment["start"]
        for segment in timing_segments
    )
    density = onset_count / duration if duration > 0 else 0.0

    if timing_strategy == "continuous":
        return "t2a", "Continuous timing is sufficiently represented by segment ranges."
    if timing_strategy == "single_event":
        if timing_confidence == "low" and sync_sensitivity == "high":
            return "v2a", "Low-confidence sync-sensitive onset benefits from visual alignment."
        return "t2a", "Sparse single onset is sufficiently represented by explicit timing."
    if sync_sensitivity == "high" or timing_confidence == "low":
        return "v2a", "Repeated onsets need visual timing to preserve sync."
    if density >= 1.0 or onset_count >= 5:
        return "v2a", "Dense repeated onsets need visual timing to preserve sync."
    return "t2a", "Repeated onsets are sparse enough for text plus timestamps."


def apply_routing(draft_tracks: dict) -> dict:
    routed = copy.deepcopy(draft_tracks)
    for track_key, track_kind in (("action_tracks", "action"), ("background_tracks", "background")):
        for track in routed[track_key]:
            layer_models: list[GenerationModel] = []
            for layer in track["sound_layers"]:
                model, reason = route_layer(track_kind, layer)
                layer["preferred_generation_model"] = model
                layer["routing_reason"] = reason
                layer_models.append(model)
            if any(model == "v2a" for model in layer_models):
                track["generation_model"] = "v2a"
                track["routing_reason"] = "At least one layer requires visually aligned generation."
            else:
                track["generation_model"] = "t2a"
                track["routing_reason"] = "All layers are sufficiently represented by text and timing."
    return routed


def finalize_draft_tracks(draft_tracks: dict) -> dict:
    payload = copy.deepcopy(draft_tracks)
    for track_key in ("action_tracks", "background_tracks"):
        for track in payload[track_key]:
            final_layers = []
            for layer in track["sound_layers"]:
                final_layer = strip_draft_layer_metadata(layer)
                if final_layer["sound_type"] == "onset":
                    if not final_layer.get("onsets"):
                        raise ValueError("final onset layer must contain non-empty onsets")
                    final_layer["timestamp_confidence"] = (
                        final_layer.get("timestamp_confidence")
                        or layer.get("timing_confidence")
                        or "medium"
                    )
                elif final_layer["sound_type"] == "continuous":
                    if not final_layer.get("segments"):
                        raise ValueError("final continuous layer must contain non-empty segments")
                final_layers.append(final_layer)
            track["sound_layers"] = final_layers
    validated = TrackOutputModel.model_validate(payload).model_dump(mode="json")
    return attach_track_and_layer_ids(validated)


def run_draft_track_inventory(state: PipelineState) -> dict:
    api_key = os.environ["GEMINI_API_KEY"]
    base_prompt = _render_inventory_prompt(state)
    retry_count = state.get("multi_validation_retry_count", 1)

    def call(correction: str | None) -> DraftTrackOutputModel:
        _, model = generate_json_response(
            api_key=api_key,
            user_prompt=_append_correction(base_prompt, correction),
            system_prompt=INVENTORY_SYSTEM_PROMPT,
            file_uri=state["file_uri"],
            model_name=state["model"],
            video_fps=state.get("multi_base_fps", 1.0),
            temperature=state["temperature"],
            seed=state["seed"],
            schema_model=DraftTrackOutputModel,
        )
        return model

    draft_model = _with_validation_retry(
        call=call,
        validate=lambda model: _validate_inventory_model(model, state["video_duration"]),
        retry_count=retry_count,
    )
    draft_tracks = draft_model.model_dump(mode="json")
    return {
        "draft_tracks": draft_tracks,
        "intermediate_artifacts": {
            **state.get("intermediate_artifacts", {}),
            "01_draft_track_inventory.json": draft_tracks,
        },
    }


def run_timestamp_task_planning(state: PipelineState) -> dict:
    tasks = build_timestamp_tasks(
        draft_tracks=state["draft_tracks"],
        duration=state["video_duration"],
        refinement_fps=state.get("multi_refinement_fps", 10.0),
        single_event_padding_seconds=state.get("multi_single_event_padding_seconds", 1.5),
        repeated_chunk_seconds=state.get("multi_repeated_chunk_seconds", 12.0),
        chunk_overlap_seconds=state.get("multi_chunk_overlap_seconds", 0.25),
    )
    return {
        "timestamp_tasks": tasks,
        "intermediate_artifacts": {
            **state.get("intermediate_artifacts", {}),
            "02_timestamp_tasks.json": tasks,
        },
    }


def _refine_timestamp_task(
    task_payload: dict,
    draft_tracks: dict,
    state: PipelineState,
    api_key: str,
    retry_count: int,
) -> tuple[tuple[str, int, int], TimestampRefinementModel]:
    task = TimestampTaskModel.model_validate(task_payload)
    track_key = _task_track_key(task_payload)
    track = draft_tracks[track_key][task.track_index]
    layer = track["sound_layers"][task.layer_index]
    base_prompt = _render_timestamp_prompt(task, track, layer)

    def call(correction: str | None) -> TimestampRefinementModel:
        _, model = generate_json_response(
            api_key=api_key,
            user_prompt=_append_correction(base_prompt, correction),
            system_prompt=_timestamp_system_prompt(task),
            file_uri=state["file_uri"],
            model_name=state["model"],
            video_fps=task.fps,
            start_offset=_format_offset(task.start),
            end_offset=_format_offset(task.end),
            temperature=state["temperature"],
            seed=state["seed"],
            schema_model=TimestampRefinementModel,
        )
        return model

    refinement = _with_validation_retry(
        call=call,
        validate=lambda model: _validate_refinement(
            model,
            task,
            track,
            layer,
        ),
        retry_count=retry_count,
    )
    return (track_key, task.track_index, task.layer_index), refinement


def run_timestamp_refinement(state: PipelineState) -> dict:
    draft_tracks = copy.deepcopy(state["draft_tracks"])
    retry_count = state.get("multi_validation_retry_count", 1)
    merge_tolerance = state.get("multi_timestamp_merge_tolerance_seconds", 0.10)
    grouped_onsets: dict[tuple[str, int, int], list[float]] = {}
    grouped_confidences: dict[tuple[str, int, int], list[str]] = {}
    api_key = os.environ["GEMINI_API_KEY"]
    task_payloads = state.get("timestamp_tasks", [])
    max_workers = max(1, int(state.get("multi_refinement_max_workers", 4)))

    if task_payloads:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(task_payloads))) as executor:
            futures = [
                executor.submit(
                    copy_context().run,
                    _refine_timestamp_task,
                    task_payload,
                    draft_tracks,
                    state,
                    api_key,
                    retry_count,
                )
                for task_payload in task_payloads
            ]
            for future in as_completed(futures):
                key, refinement = future.result()
                grouped_onsets.setdefault(key, []).extend(refinement.onsets)
                grouped_confidences.setdefault(key, []).append(refinement.timestamp_confidence)

    for (track_key, track_index, layer_index), onsets in grouped_onsets.items():
        layer = draft_tracks[track_key][track_index]["sound_layers"][layer_index]
        layer["onsets"] = _merge_onsets(onsets, merge_tolerance)
        layer["timestamp_confidence"] = _merge_confidences(
            grouped_confidences[(track_key, track_index, layer_index)]
        )

    refined_model = DraftTrackOutputModel.model_validate(draft_tracks)
    refined_tracks = refined_model.model_dump(mode="json")
    return {
        "draft_tracks": refined_tracks,
        "timestamp_refined_tracks": refined_tracks,
        "intermediate_artifacts": {
            **state.get("intermediate_artifacts", {}),
            "03_timestamp_refined_tracks.json": refined_tracks,
        },
    }


def run_model_routing(state: PipelineState) -> dict:
    routed_tracks = apply_routing(state["draft_tracks"])
    DraftTrackOutputModel.model_validate(routed_tracks)
    return {
        "draft_tracks": routed_tracks,
        "routed_tracks": routed_tracks,
        "intermediate_artifacts": {
            **state.get("intermediate_artifacts", {}),
            "04_routed_tracks.json": routed_tracks,
        },
    }


def run_finalize_tracks(state: PipelineState) -> dict:
    finalized = finalize_draft_tracks(state["draft_tracks"])
    return {
        "action_tracks": finalized["action_tracks"],
        "background_tracks": finalized["background_tracks"],
        "raw_json_payload": None,
    }
