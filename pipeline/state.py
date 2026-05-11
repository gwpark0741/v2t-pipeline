from typing import TypedDict


class SoundEvent(TypedDict):
    event_id: str        # 이벤트 고유 식별자 (evt_001, evt_002, ...)
    event_type: str      # 이벤트 유형 (sword_fight, guitar_playing, ...)
    start: float         # 시작 시간 (초)
    end: float           # 종료 시간 (초)
    description: str     # T2A 모델 입력용 영어 설명

# LangGraph State Container
class PipelineState(TypedDict):
    # 입력
    video_path: str
    model: str
    temperature: float
    seed: int
    use_audio: bool
    input_mode: str

    # 전처리 결과
    video_duration: float
    file_uri: str | None     # File API 업로드 후 URI

    # 노드 결과
    raw_llm_response: str               # LLM 원본 응답 (디버깅용)
    sound_events: list[SoundEvent]

    # 메타
    run_id: str
    errors: list[str]