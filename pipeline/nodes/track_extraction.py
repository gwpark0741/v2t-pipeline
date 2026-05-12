import json
import os


from clients.gemini_client import generate_response, get_client
from pipeline.schema import TrackOutputModel
from pipeline.state import PipelineState
from prompts.single import SYSTEM_PROMPT, USER_PROMPT


def build_user_prompt(duration: float) -> str:
    """video 전처리에서 추출한 duration을 활용하여 user prompt를 생성하는 함수"""
    return USER_PROMPT.replace("__DURATION__", str(duration))


def parse_and_validate_response(raw_response: str) -> dict:
    """Gemini 모델로부터 받은 raw response를 JSON으로 파싱하고, pydantic 모델로 검증하는 함수 -> 검증된 데이터를 딕셔너리 형태로 반환"""
    parsed = json.loads(raw_response) # Gemini 응답을 JSON으로 파싱
    validated = TrackOutputModel.model_validate(parsed) # pydantic 객체로 변환 후 검증
    return validated.model_dump() # 검증된 pydantic 모델을 dict으로 변환하여 반환


def attach_track_ids(validated_dict: dict) -> dict:
    """검증된 트랙 데이터에 고유한 track_id를 부여하는 함수 (track_id는 'act_001', 'bg_001' 형식으로 생성) -> track_id가 부여된 딕셔너리 반환"""
    for index, track in enumerate(validated_dict["action_tracks"], start=1):
        track["track_id"] = f"act_{index:03d}"

    for index, track in enumerate(validated_dict["background_tracks"], start=1):
        track["track_id"] = f"bg_{index:03d}"

    return validated_dict # track_id가 부여된 딕셔너리


def run_track_extraction(state: PipelineState) -> dict:
    """Gemini 호출 및 응답 처리 전체를 담당하는 함수: API 호출, 응답 파싱 및 검증, 필요한 필드 추출하여 반환"""
    api_key = os.environ["GEMINI_API_KEY"] # 환경변수에서 API 키 읽기
    client = get_client(api_key)

    user_prompt = build_user_prompt(state["video_duration"])
    raw_llm_response = generate_response(
        client=client,
        user_prompt=user_prompt,
        system_prompt=SYSTEM_PROMPT,
        file_name=state["file_name"],
        # temperature, model_name, seed는 초기 state에서 가져옴
        temperature=state["temperature"],
        model_name=state["model"], 
        seed=state["seed"],
    )

    # Gemini 응답을 JSON으로 파싱하고, pydantic 모델로 검증하여 필요한 필드 추출
    validated_dict = parse_and_validate_response(raw_llm_response)
    
    # 검증된 트랙 데이터에 고유한 track_id 부여
    validated_dict = attach_track_ids(validated_dict)

    # 검증된 데이터를 딕셔너리 형태로 반환 -> state 업데이트에 활용
    return {
        "raw_llm_response": raw_llm_response,
        "action_tracks": validated_dict["action_tracks"],
        "background_tracks": validated_dict["background_tracks"],
    }