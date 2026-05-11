from typing import Literal, NotRequired, TypedDict


class TimeSegment(TypedDict):
    start: float
    end: float


class ActionTrack(TypedDict):
    event_type: str
    segments: list[TimeSegment]
    description: str
    audio_type: Literal["sfx"]


class BackgroundTrack(TypedDict):
    ambience_type: str
    segments: list[TimeSegment]
    description: str
    audio_type: Literal["ambience"]


class PipelineState(TypedDict):
    # 입력
    video_path: str
    model: str
    temperature: float
    seed: int
    use_audio: bool
    input_mode: Literal["file_api", "frames"]

    # 전처리 결과
    video_duration: NotRequired[float]
    file_uri: NotRequired[str | None]

    # 노드 결과
    raw_llm_response: NotRequired[str]
    action_tracks: NotRequired[list[ActionTrack]]
    background_tracks: NotRequired[list[BackgroundTrack]]

    # 메타
    run_id: str
    errors: list[str]
