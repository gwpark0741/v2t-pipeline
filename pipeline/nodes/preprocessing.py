import os
from pathlib import Path

from clients.gemini_client import get_client, upload_video
from pipeline.state import PipelineState
from tools.video_utils import get_duration, strip_audio


def resolve_working_video_path(video_path: str, use_audio: bool) -> str:
    """실제 파이프라인에서 사용할 영상 경로를 결정하는 함수 -> use_audio=false인 경우 오디오 제거한 임시 파일 생성"""
    if use_audio:
        return video_path
    return strip_audio(video_path)


def run_preprocessing(state: PipelineState) -> dict:
    """영상 전처리 후 LLM 호출에 필요한 입력 정보를 준비하는 함수 -> video_duration, working_video_path, file_uri, file_name 반환"""
    video_path = state["video_path"]

    if not Path(video_path).exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    video_duration = get_duration(video_path)
    working_video_path = resolve_working_video_path(
        video_path=video_path,
        use_audio=state["use_audio"],
    )

    # baseline에서는 Gemini File API 방식만 지원
    if state["input_mode"] != "file_api":
        raise NotImplementedError(
            f"Unsupported input_mode: {state['input_mode']}"
        )

    api_key = os.environ["GEMINI_API_KEY"]
    client = get_client(api_key)
    file_uri, file_name = upload_video(client, working_video_path)

    return {
        "video_duration": video_duration,
        "working_video_path": working_video_path,
        "file_uri": file_uri,
        "file_name": file_name,
    }
