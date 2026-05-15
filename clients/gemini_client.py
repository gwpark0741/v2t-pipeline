import time

from google import genai
from google.genai import types
from pydantic import ValidationError

from pipeline.schema import TrackOutputModel


def get_client(api_key: str) -> genai.Client:
    """Gemini 클라이언트 생성"""
    return genai.Client(api_key=api_key)


def upload_video(
        client: genai.Client, 
        video_path: str, 
        max_timeout: int = 200,
) -> tuple[str, str]:
    """영상 파일을 Gemini File API에 업로드 -> file_uri와 file_name 반환"""
    video_file = client.files.upload(file=video_path)
    start_time = time.time()

    print(f"Uploading {video_file.name} to Gemini File API...")

    while video_file.state.name == "PROCESSING":
        # 타임아웃 체크
        if time.time() - start_time > max_timeout:
            raise TimeoutError("File upload timed out.")

        print(f"File {video_file.name} is still processing...")
        time.sleep(10)  # 10초마다 상태 확인
        video_file = client.files.get(name=video_file.name)

    if video_file.state.name == "FAILED":
        raise RuntimeError(f"File upload failed: {video_file.failure_reason}")

    print(f"File {video_file.name} upload completed successfully.")
    return video_file.uri, video_file.name


def _build_video_part(
        file_uri: str, 
        video_fps: float | None
) -> types.Part:
    """비디오 파일에 대한 추론 준비: File API 업로드된 video + fps info -> video part 생성"""
    file_data = types.FileData(
        file_uri=file_uri,
        mime_type="video/mp4",
    )

    if video_fps is None:
        return types.Part(file_data=file_data)
    
    return types.Part(
        file_data=file_data,
        video_metadata=types.VideoMetadata(fps=video_fps),
    )


def _build_generation_config(
    system_prompt: str,
    temperature: float,
    seed: int,
) -> types.GenerateContentConfig:
    """Gemini generation config 생성"""
    return types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature = temperature,
        seed = seed,
        response_mime_type="application/json",
        response_json_schema=TrackOutputModel.model_json_schema(),
    )


def _extract_response_text(response) -> str:
    """Gemini SDK 응답에서 JSON 텍스트 추출"""
    response_text = getattr(response, "text", None)
    if not response_text:
        raise ValueError("Gemini returned empty response text")
    return response_text


def _validate_track_output(response_text: str) -> TrackOutputModel:
    """Gemini 응답 JSON을 Pydantic schema로 검증"""
    try:
        return TrackOutputModel.model_validate_json(response_text)
    except ValidationError as exc:
        print(f"LLM JSON did not match TrackOutputModel: {exc}")
        raise


def generate_structured_response(
    api_key: str,
    user_prompt: str,
    file_uri: str,
    model_name: str,
    temperature: float,
    seed: int,
    system_prompt: str = "",
    video_fps: float | None = None,
) -> tuple[str, TrackOutputModel]:
    """Gemini SDK + Gemini structured output 호출 -> raw_json_payload, track_output 반환"""
    client = get_client(api_key)
    video_part = _build_video_part(file_uri, video_fps)
    config = _build_generation_config(system_prompt, temperature, seed)

    response = client.models.generate_content(
        model = model_name,
        contents=[
            video_part,
            types.Part(text=user_prompt)
        ],
        config=config,
    )

    raw_json_payload = _extract_response_text(response)
    track_output = _validate_track_output(raw_json_payload)
    return raw_json_payload, track_output