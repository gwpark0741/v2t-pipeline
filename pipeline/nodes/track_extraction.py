import json
import os


from clients.gemini_client import generate_response, get_client
from pipeline.schema import TrackOutputModel
from pipeline.state import PipelineState
from prompts.single import SYSTEM_PROMPT, USER_PROMPT


# video 전처리에서 추출한 duration을 활용하여 user prompt를 생성하는 함수
def build_user_prompt(duration: float) -> str:
    return USER_PROMPT.replace("__DURATION__", str(duration))


# Gemini 모델로부터 받은 raw response를 JSON으로 파싱하고, pydantic 모델로 검증하는 함수
def parse_and_validate_response(raw_response: str) -> dict:
    parsed = json.loads(raw_response)
    validated = TrackOutputModel.model_validate(parsed)
    return validated.model_dump()


# Gemini 호출 및 응답 처리 전체를 담당하는 함수
def run_track_extraction(state: PipelineState) -> dict:
    api_key = os.environ["GEMINI_API_KEY"] #환경변수에서 API 키 읽기
    client = get_client(api_key)

    user_prompt = build_user_prompt(state["video_duration"])
    raw_llm_response = generate_response(
        client=client,
        user_prompt=user_prompt,
        file_name=state["file_name"],
        model_name=state["model"],
        temperature=state["temperature"],
        seed=state["seed"],
        system_prompt=SYSTEM_PROMPT,
    )

    # Gemini 응답을 JSON으로 파싱하고, pydantic 모델로 검증하여 필요한 필드 추출
    validated_dict = parse_and_validate_response(raw_llm_response)

    # 검증된 데이터를 딕셔너리 형태로 반환 -> state 업데이트에 활용
    return {
        "raw_llm_response": raw_llm_response,
        "action_tracks": validated_dict["action_tracks"],
        "background_tracks": validated_dict["background_tracks"],
    }