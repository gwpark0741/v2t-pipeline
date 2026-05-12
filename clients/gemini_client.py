import json
import time

from google import genai
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
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


def _extract_json_payload(raw_message) -> str:
    """LangChain raw AIMessage에서 가능한 한 JSON 원문에 가까운 문자열 추출"""
    tool_calls = raw_message.additional_kwargs.get("tool_calls", [])
    if tool_calls:
        function = tool_calls[0].get("function", {})
        arguments = function.get("arguments")
        if isinstance(arguments, str) and arguments:
            return arguments

    if isinstance(raw_message.content, str):
        return raw_message.content

    return json.dumps(raw_message.model_dump(mode="json"), ensure_ascii=False)


def generate_structured_response(
    api_key: str,
    user_prompt: str,
    file_uri: str,
    model_name: str,
    temperature: float,
    seed: int,
    system_prompt: str = "",
) -> tuple[str, TrackOutputModel]:
    """LangChain + Gemini structured output 호출 -> raw_json_payload, track_output 반환"""

    # LangChain Gemini chat model 초기화
    llm = ChatGoogleGenerativeAI(
        api_key=api_key,
        model=model_name,
        temperature=temperature,
        seed=seed,
        response_mime_type="application/json",
    )
    
    # Pydantic schema로 구조화된 출력 강제
    structured_llm = llm.with_structured_output(
        TrackOutputModel,
        include_raw=True, # 원본 AIMessage 보존
    )

    # system prompt + user prompt + vidoes 재공 -> 구조화된 llm output
    result = structured_llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(
                content=[
                    {
                        "type": "file",
                        "file_id": file_uri,
                        "mime_type": "video/mp4",
                    },
                    {
                        "type": "text",
                        "text": user_prompt,
                    },
                ]
            ),
        ]
    )

    # 파싱 에러 발생 시 유형을 구분
    parsing_error = result["parsing_error"]
    if parsing_error is not None:
        if isinstance(parsing_error, json.JSONDecodeError):
            print(f"LLM did not return valid JSON: {parsing_error}")
        elif isinstance(parsing_error, ValidationError):
            print(f"LLM JSON did not match TrackOutputModel: {parsing_error}")

        raise parsing_error

    track_output = result["parsed"]
    if track_output is None:
        raise ValueError("Structured output parsing returned None")
    
    # 디버깅용 원본 JSON 파싱 텍스트 추출
    raw_json_payload = _extract_json_payload(result["raw"])
    return raw_json_payload, track_output
