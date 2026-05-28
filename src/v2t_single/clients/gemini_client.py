import time

from langfuse.decorators import langfuse_context, observe

from google import genai
from google.genai import types
from pydantic import ValidationError

from v2t_single.pipeline.schema import TrackOutputModel


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


def _extract_langfuse_usage_metadata(response) -> dict:
    """Gemini SDK가 반환하는 usage 정보를 Langfuse usage 형식으로 반환하는 helper"""
    usage = getattr(response, "usage_metadata", None)

    if usage is None:
        return {}
    
    input_tokens = (
        (usage.prompt_token_count or 0)
        + (usage.tool_use_prompt_token_count or 0)
    )
    output_tokens = (
        (usage.candidates_token_count or 0)
        + (usage.thoughts_token_count or 0)
    )

    # Langfuse usage schema (input, output, total)
    usage_metadata = {
        "input": input_tokens,
        "output": output_tokens,
        "total": usage.total_token_count or input_tokens + output_tokens,
    }

    return usage_metadata

# Langfuse trace decorator
@observe(
    name="Gemini GenerateContent",
    as_type="generation"
)
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

    # Langfuse에 입력 기록 덮어쓰기 (api_key 제외)
    langfuse_context.update_current_observation(
        input={
            "model_name": model_name,
            "file_uri": file_uri,
            "video_fps": video_fps,
            "temperature": temperature,
            "seed": seed,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        },
        model=model_name.removeprefix("models/"),
        model_parameters={
            "temperature": temperature,
            "seed": seed,
            "video_fps": video_fps,
        }
    )

    # Google genai SDK - 응답 생성
    response = client.models.generate_content(
        model = model_name,
        contents=[
            video_part,
            types.Part(text=user_prompt)
        ],
        config=config,
    )

    # Gemini 응답을 Langfuse schema로 변환
    usage_metadata = _extract_langfuse_usage_metadata(response)

    # Langfuse run에 usage metadata를 붙임
    if usage_metadata:
        langfuse_context.update_current_observation(usage=usage_metadata)

    # Gemini 응답에서 JSON 파싱
    raw_json_payload = _extract_response_text(response)
    # Pydantic validation
    track_output = _validate_track_output(raw_json_payload)
    # raw JSON과 검증된 모델을 반환
    return raw_json_payload, track_output