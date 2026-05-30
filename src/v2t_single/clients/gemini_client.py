import time
from typing import TypeVar

from langsmith import get_current_run_tree, traceable

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from v2t_single.pipeline.schema import TrackOutputModel


SchemaModelT = TypeVar("SchemaModelT", bound=BaseModel)


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
        video_fps: float | None,
        start_offset: str | None = None,
        end_offset: str | None = None,
) -> types.Part:
    """비디오 파일에 대한 추론 준비: File API 업로드된 video + fps info -> video part 생성"""
    file_data = types.FileData(
        file_uri=file_uri,
        mime_type="video/mp4",
    )

    if video_fps is None and start_offset is None and end_offset is None:
        return types.Part(file_data=file_data)

    video_metadata = types.VideoMetadata(
        fps=video_fps,
        start_offset=start_offset,
        end_offset=end_offset,
    )
    
    return types.Part(
        file_data=file_data,
        video_metadata=video_metadata,
    )


def _build_generation_config(
    system_prompt: str,
    temperature: float,
    seed: int,
    schema_model: type[BaseModel] = TrackOutputModel,
) -> types.GenerateContentConfig:
    """Gemini generation config 생성"""
    return types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature = temperature,
        seed = seed,
        response_mime_type="application/json",
        response_json_schema=schema_model.model_json_schema(),
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


def _validate_json_output(
    response_text: str,
    schema_model: type[SchemaModelT],
) -> SchemaModelT:
    """Gemini JSON 응답을 호출자가 넘긴 Pydantic schema로 검증한다."""
    try:
        return schema_model.model_validate_json(response_text)
    except ValidationError as exc:
        print(f"LLM JSON did not match {schema_model.__name__}: {exc}")
        raise


def _extract_langsmith_usage_metadata(response) -> dict:
    """Gemini SDK가 반환하는 usage 정보를 LangSmith usage 형식으로 반환하는 helper"""
    # Gemini response에 존재하는 token 사용량 정보를 가져옴
    usage = getattr(response, "usage_metadata", None)

    if usage is None:
        return {}
    
    # Gemini가 반환한 token 정보를 기반으로 input/output token 개수 계산
    input_tokens = (
        (usage.prompt_token_count or 0)
        + (usage.tool_use_prompt_token_count or 0)
    )
    output_tokens = (
        (usage.candidates_token_count or 0)
        + (usage.thoughts_token_count or 0)
    )

    # LangSmith usage_metadata schema
    usage_metadata = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": usage.total_token_count or input_tokens + output_tokens,
    }

    input_details = {}
    if usage.cached_content_token_count:
        input_details["cache_read"] = usage.cached_content_token_count

    output_details = {}
    if usage.thoughts_token_count:
        output_details["reasoning"] = usage.thoughts_token_count

    if input_details:
        usage_metadata["input_token_details"] = input_details
    if output_details:
        usage_metadata["output_token_details"] = output_details

    return usage_metadata

# LangSmith trace decorartor
@traceable (
    # LangSmith UI에 표시될 이름
    name = "Gemini GenerateContent",
    # LangSmith가 LLM 호출로 인식 가능하게
    run_type="llm",

    # api_key가 trace에 남지 않도록 제외
    process_inputs=lambda inputs: {
        "model_name": inputs.get("model_name"),
        "file_uri": inputs.get("file_uri"),
        "video_fps": inputs.get("video_fps"),
        "temperature": inputs.get("temperature"),
        "seed": inputs.get("seed"),
        "system_prompt": inputs.get("system_prompt"),
        "user_prompt": inputs.get("user_prompt"),
    },
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

    # LangSmith SDK가 제공하는 현재 run 객체를 가져와서, Langsmith metadata를 추가 (@tracable)
    run = get_current_run_tree()
    if run is not None:
        run.add_metadata({
            "ls_provider": "google_genai",
            "ls_model_name": model_name.removeprefix("models/"),
            "ls_model_type": "chat",
            "ls_temperature": temperature,
            "ls_invocation_params": {
                "seed": seed,
                "video_fps": video_fps,
            },
        })

    # Google genai SDK - 응답 생성
    response = client.models.generate_content(
        model = model_name,
        contents=[
            video_part,
            types.Part(text=user_prompt)
        ],
        config=config,
    )

    # Gemini 응답을 LangSmith schema로 변환
    usage_metadata = _extract_langsmith_usage_metadata(response)

    # Langsmith run에 metadata를 붙임
    if run is not None and usage_metadata:
        run.set(usage_metadata=usage_metadata)

    # Gemini 응답에서 JSON 파싱
    raw_json_payload = _extract_response_text(response)
    # Pydantic validation
    track_output = _validate_track_output(raw_json_payload)
    # raw JSON과 검증된 모델을 반환
    return raw_json_payload, track_output


@traceable(
    name="Gemini Generate JSON",
    run_type="llm",
    process_inputs=lambda inputs: {
        "model_name": inputs.get("model_name"),
        "file_uri": inputs.get("file_uri"),
        "video_fps": inputs.get("video_fps"),
        "start_offset": inputs.get("start_offset"),
        "end_offset": inputs.get("end_offset"),
        "temperature": inputs.get("temperature"),
        "seed": inputs.get("seed"),
        "schema_model": getattr(inputs.get("schema_model"), "__name__", None),
        "system_prompt": inputs.get("system_prompt"),
        "user_prompt": inputs.get("user_prompt"),
    },
)
def generate_json_response(
    api_key: str,
    user_prompt: str,
    file_uri: str,
    model_name: str,
    temperature: float,
    seed: int,
    schema_model: type[SchemaModelT],
    system_prompt: str = "",
    video_fps: float | None = None,
    start_offset: str | None = None,
    end_offset: str | None = None,
) -> tuple[str, SchemaModelT]:
    """Gemini SDK + arbitrary structured JSON schema 호출."""
    client = get_client(api_key)
    video_part = _build_video_part(
        file_uri=file_uri,
        video_fps=video_fps,
        start_offset=start_offset,
        end_offset=end_offset,
    )
    config = _build_generation_config(
        system_prompt=system_prompt,
        temperature=temperature,
        seed=seed,
        schema_model=schema_model,
    )

    run = get_current_run_tree()
    if run is not None:
        run.add_metadata({
            "ls_provider": "google_genai",
            "ls_model_name": model_name.removeprefix("models/"),
            "ls_model_type": "chat",
            "ls_temperature": temperature,
            "ls_invocation_params": {
                "seed": seed,
                "video_fps": video_fps,
                "start_offset": start_offset,
                "end_offset": end_offset,
                "schema_model": schema_model.__name__,
            },
        })

    response = client.models.generate_content(
        model=model_name,
        contents=[
            video_part,
            types.Part(text=user_prompt),
        ],
        config=config,
    )

    usage_metadata = _extract_langsmith_usage_metadata(response)
    if run is not None and usage_metadata:
        run.set(usage_metadata=usage_metadata)

    raw_json_payload = _extract_response_text(response)
    return raw_json_payload, _validate_json_output(raw_json_payload, schema_model)
