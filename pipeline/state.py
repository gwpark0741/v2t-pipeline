from typing import Literal, NotRequired, TypedDict


class TimeSegment(TypedDict):
    start: float
    end: float


class ActionTrack(TypedDict):
    track_id: str
    event_type: str
    segments: list[TimeSegment]
    description: str
    audio_type: Literal["sfx"]


class BackgroundTrack(TypedDict):
    track_id: str
    ambience_type: str
    segments: list[TimeSegment]
    description: str
    audio_type: Literal["ambience"]


class PipelineState(TypedDict):
    # 입력값: run.py에서 초기 state 생성 시 설정
    video_path: str
    model: str
    temperature: float
    seed: int
    use_audio: bool
    input_mode: Literal["file_api", "frames"]

    # 전처리 결과: pipeline/nodes/preprocessing.py에서 설정
    video_duration: NotRequired[float]
    working_video_path: NotRequired[str]    # 무음 처리된 영상의 임시 경로
    file_uri: NotRequired[str]
    file_name: NotRequired[str]

    # LLM 추론 결과: pipeline/nodes/track_extraction.py에서 설정
    raw_llm_response: NotRequired[str]
    action_tracks: NotRequired[list[ActionTrack]]
    background_tracks: NotRequired[list[BackgroundTrack]]

    # 메타: run.py에서 초기화, 각 노드에서 에러 누적
    run_id: str
    errors: list[str]
