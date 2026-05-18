import os


from clients.gemini_client import generate_structured_response
from pipeline.state import PipelineState


def _attach_layer_ids(track: dict) -> None:
    """track 내부 sound_layers에 parent track_id 기반 layer_id를 부여한다."""
    track_id = track["track_id"]
    for index, layer in enumerate(track.get("sound_layers", []), start=1):
        layer["layer_id"] = f"{track_id}_layer_{index:03d}"


def attach_track_and_layer_ids(validated_dict: dict) -> dict:
    """검증된 트랙 데이터에 track_id와 layer_id를 부여한 딕셔너리를 반환한다."""
    for index, track in enumerate(validated_dict["action_tracks"], start=1):
        track["track_id"] = f"act_{index:03d}"
        _attach_layer_ids(track)

    for index, track in enumerate(validated_dict["background_tracks"], start=1):
        track["track_id"] = f"bg_{index:03d}"
        _attach_layer_ids(track)

    return validated_dict


def attach_track_ids(validated_dict: dict) -> dict:
    """Backward-compatible wrapper for callers that still import the old name."""
    return attach_track_and_layer_ids(validated_dict)


def run_track_extraction(state: PipelineState) -> dict:
    """Gemini 호출 및 응답 처리 전체를 담당하는 함수: API 호출 -> structured_output -> 필요한 필드 추출하여 반환"""
    api_key = os.environ["GEMINI_API_KEY"] # 환경변수에서 API 키 읽기

    raw_json_payload, structured_output = generate_structured_response(
        api_key=api_key,
        user_prompt=state["user_prompt"],
        system_prompt=state["system_prompt"],
        file_uri=state["file_uri"],
        model_name=state["model"],
        video_fps=state["video_fps"],
        temperature=state["temperature"],
        seed=state["seed"],
    )
    
    validated_dict = structured_output.model_dump()
    validated_dict = attach_track_and_layer_ids(validated_dict)

    return {
        "raw_json_payload": raw_json_payload,
        "action_tracks": validated_dict["action_tracks"],
        "background_tracks": validated_dict["background_tracks"],

    }
