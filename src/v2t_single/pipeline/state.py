from typing import Literal, NotRequired, TypedDict

from v2t_single.prompts.prompts_registry import PromptProfile

class TimeSegment(TypedDict):
    start: float
    end: float


class SceneCut(TypedDict):
    cut_id: str
    start: float
    end: float


# Model routing 결과 - 실제 오디오를 생성할 모델 선정 정보
GenerationModel = Literal["t2a", "v2a"]


TimestampConfidence = Literal["high", "medium", "low"]


class OnsetSoundLayer(TypedDict):
    layer_id: str
    layer_label: str
    sound_type: Literal["onset"]
    onsets: list[float]
    description: str
    preferred_generation_model: GenerationModel
    routing_reason: str
    timestamp_confidence: TimestampConfidence


class ContinuousSoundLayer(TypedDict):
    layer_id: str
    layer_label: str
    sound_type: Literal["continuous"]
    segments: list[TimeSegment]
    description: str
    preferred_generation_model: GenerationModel
    routing_reason: str


SoundLayer = OnsetSoundLayer | ContinuousSoundLayer


class ActionTrack(TypedDict):
    track_id: str
    event_type: str
    segments: list[TimeSegment]
    description: str
    audio_type: Literal["sfx"]
    sound_layers: NotRequired[list[SoundLayer]]
    generation_model: GenerationModel
    routing_reason: str


class BackgroundTrack(TypedDict):
    track_id: str
    ambience_type: str
    segments: list[TimeSegment]
    description: str
    audio_type: Literal["ambience"]
    sound_layers: NotRequired[list[SoundLayer]]
    generation_model: GenerationModel
    routing_reason: str


class PipelineState(TypedDict):
    # 입력값: run.py에서 초기 state 생성 시 설정
    video_path: str
    model: str
    temperature: float
    seed: int
    use_audio: bool
    input_mode: Literal["file_api", "frames"]
    video_fps: float | None
    use_scene_detect: bool
    use_sound_layering: bool
    prompt_profile: PromptProfile

    # 전처리 결과: pipeline/nodes/preprocessing.py에서 설정
    video_duration: NotRequired[float]
    scene_cuts: NotRequired[list[SceneCut]]
    scene_cuts_prompt: NotRequired[str]
    working_video_path: NotRequired[str]    # 무음 처리된 영상의 임시 경로
    file_uri: NotRequired[str]
    file_name: NotRequired[str]

    # prompt info: pipeline/nodes/build_prompt.py에서 설정
    system_prompt: NotRequired[str]
    user_prompt: NotRequired[str]

    # LLM 추론 결과: pipeline/nodes/track_extraction.py에서 설정
    raw_json_payload: NotRequired[str]
    action_tracks: NotRequired[list[ActionTrack]]
    background_tracks: NotRequired[list[BackgroundTrack]]

    # 메타: run.py에서 초기화, 각 노드에서 에러 누적
    run_id: str
    errors: list[str]
