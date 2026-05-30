import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TimeSegmentModel(BaseModel):
    """여러 timeline에 걸친 track의 시간 정보를 담는 모델"""
    model_config = ConfigDict(extra="forbid")

    start: float = Field(ge=0)
    end: float = Field(ge=0)
    
    # 'start는 end보다 작아야 한다' 모델 검증기
    @model_validator(mode="after")
    def validate_range(self) -> "TimeSegmentModel":
        if self.end <= self.start:
            raise ValueError("segment end must be greater than start")
        return self
    

# Model routing 결과 - 실제 오디오를 생성할 모델 선정 정보
GenerationModel = Literal["t2a", "v2a"]


TimestampConfidence = Literal["high", "medium", "low"]


class OnsetSoundLayerModel(BaseModel):
    """Onset sound layer로 float timestamp를 가짐"""
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    layer_label: str = Field(min_length=1)
    sound_type: Literal["onset"]
    onsets: list[float] = Field(min_length=1)
    description: str = Field(min_length=1)
    preferred_generation_model: GenerationModel
    routing_reason: str = Field(min_length=1)
    timestamp_confidence: TimestampConfidence
    

    @field_validator("onsets")
    @classmethod
    def validate_onsets(cls, onsets: list[float]) -> list[float]:
        for onset in onsets:
            if onset < 0:
                raise ValueError("onsets must be greater than or equal to 0")

        for prev, curr in zip(onsets, onsets[1:]):
            if curr < prev:
                raise ValueError("onsets must be sorted by time")
        return onsets
    

class ContinuousSoundLayerModel(BaseModel):
    """Continuous sound layer로 segment timestamp를 가짐"""
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    layer_label: str = Field(min_length=1)
    sound_type: Literal["continuous"]
    segments: list[TimeSegmentModel] = Field(min_length=1)
    description: str = Field(min_length=1)
    preferred_generation_model: GenerationModel
    routing_reason: str = Field(min_length=1)

    @field_validator("segments")
    @classmethod
    def validate_segments_sorted(
        cls, 
        segments: list[TimeSegmentModel],
    ) -> list[TimeSegmentModel]:
        for prev, curr in zip(segments, segments[1:]):
            if curr.start < prev.start:
                raise ValueError("segments must be sorted by start time")
        return segments


# 모든 sound layer는 onset과 continuous 중 하나 (둘 다 될 수 없음)
SoundLayerModel = Annotated[
    OnsetSoundLayerModel | ContinuousSoundLayerModel,
    Field(discriminator="sound_type")
]


def _segment_is_inside_parent(
    parent_segments: list[TimeSegmentModel],
    child_segment: TimeSegmentModel,
) -> bool:
    """continuous sound layer의 segment가 major track segments 중 하나에 완전히 포함되는지 검증"""
    return any(
        parent_segment.start <= child_segment.start and child_segment.end <= parent_segment.end
        for parent_segment in parent_segments
    )
    
def _onset_is_inside_parent(
    parent_segments: list[TimeSegmentModel],
    child_onset: float,
) -> bool:
    """onset sound layer가 major track segments 중 하나에 완전히 포함되는지 검증"""
    return any(
        parent_segment.start <= child_onset <= parent_segment.end
        for parent_segment in parent_segments
    )


class ActionTrackModel(BaseModel):
    """action_tracks 필드와 검증 로직을 담는 모델"""
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    event_type: str = Field(min_length=1)
    segments: list[TimeSegmentModel] = Field(min_length=1)
    description: str = Field(min_length=1)
    audio_type: Literal["sfx"]
    generation_model: GenerationModel
    routing_reason: str = Field(min_length=1)
    sound_layers: list[SoundLayerModel] = Field(min_length=1)

    # segments 리스트가 시간 순으로 정렬되어 있는지 검증하는 필드 검증기
    @field_validator("segments")
    @classmethod
    def validate_segments_sorted(
        cls,
        segments: list[TimeSegmentModel],
    ) -> list[TimeSegmentModel]:
        for prev, curr in zip(segments, segments[1:]):
            if curr.start < prev.start:
                raise ValueError("segments must be sorted by start time")
        return segments
    
    # sound layer의 timestamp가 현재 track time에 포함되는지 확인
    @model_validator(mode="after")
    def validate_sound_layers_inside_track(self) -> "ActionTrackModel":
        for layer in self.sound_layers:
            if layer.sound_type == "onset":
                for onset in layer.onsets:
                    if not _onset_is_inside_parent(self.segments, onset):
                        raise ValueError("sound layer onset must be inside parent track segments") 
            elif layer.sound_type == "continuous":
                for segment in layer.segments:
                    if not _segment_is_inside_parent(self.segments, segment):
                        raise ValueError("sound layer continuous must be inside parent track segments")                    
        return self

    # sound layers의 preferrend generation model이 하나라도 V2A라면, 전체 track 생성 모델을 V2A로 지정
    @model_validator(mode="after")
    def validate_generation_model_routing(self) -> "ActionTrackModel":
        if any(layer.preferred_generation_model == "v2a" for layer in self.sound_layers):
            if self.generation_model != "v2a":
                raise ValueError("parent generation_model must be v2a if any sound layer prefers v2a")
        return self


class BackgroundTrackModel(BaseModel):
    """background_tracks 필드와 검증 로직을 담는 모델"""
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    ambience_type: str = Field(min_length=1)
    segments: list[TimeSegmentModel] = Field(min_length=1)
    description: str = Field(min_length=1)
    audio_type: Literal["ambience"]
    generation_model: GenerationModel
    routing_reason: str = Field(min_length=1)
    sound_layers: list[SoundLayerModel] = Field(min_length=1)

    # segments 리스트가 시간 순으로 정렬되어 있는지 검증하는 필드 검증기
    @field_validator("segments")
    @classmethod
    def validate_segments_sorted(
        cls,
        segments: list[TimeSegmentModel],
    ) -> list[TimeSegmentModel]:
        for prev, curr in zip(segments, segments[1:]):
            if curr.start < prev.start:
                raise ValueError("segments must be sorted by start time")
        return segments
    
    # sound layer의 timestamp가 현재 track time에 포함되는지 확인
    @model_validator(mode="after")
    def validate_sound_layers_inside_track(self) -> "BackgroundTrackModel":
        for layer in self.sound_layers:
            if layer.sound_type == "onset":
                for onset in layer.onsets:
                    if not _onset_is_inside_parent(self.segments, onset):
                        raise ValueError("sound layer onset must be inside parent track segments")      
            elif layer.sound_type == "continuous":
                for segment in layer.segments:
                    if not _segment_is_inside_parent(self.segments, segment):
                        raise ValueError("sound layer continuous must be inside parent track segments")        
        return self
    
    # sound layers의 preferrend generation model이 하나라도 V2A라면, 전체 track 생성 모델을 V2A로 지정
    @model_validator(mode="after")
    def validate_generation_model_routing(self) -> "BackgroundTrackModel":
        if any(layer.preferred_generation_model == "v2a" for layer in self.sound_layers):
            if self.generation_model != "v2a":
                raise ValueError("parent generation_model must be v2a if any sound layer prefers v2a")
        return self


class TrackOutputModel(BaseModel):
    """ 전체 출력 스키마 모델"""
    model_config = ConfigDict(extra="forbid")

    action_tracks: list[ActionTrackModel] = Field(default_factory=list)
    background_tracks: list[BackgroundTrackModel] = Field(default_factory=list)


TimingStrategy = Literal["continuous", "single_event", "repeated_event"]
SyncSensitivity = Literal["low", "medium", "high"]
TrackKind = Literal["action", "background"]

_SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


def _validate_snake_case_label(value: str) -> str:
    if not _SNAKE_CASE_PATTERN.match(value):
        raise ValueError("label must be snake_case")
    return value


class DraftOnsetSoundLayerModel(BaseModel):
    """Multi-agent 중간 단계에서 채워지는 onset layer draft."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    layer_label: str = Field(min_length=1)
    sound_type: Literal["onset"]
    onsets: list[float] = Field(default_factory=list)
    coarse_segments: list[TimeSegmentModel] | None = None
    description: str = Field(min_length=1)
    preferred_generation_model: GenerationModel | None = None
    routing_reason: str | None = None
    timestamp_confidence: TimestampConfidence | None = None
    timing_strategy: Literal["single_event", "repeated_event"]
    coarse_event_time: float | None = Field(default=None, ge=0)
    timing_confidence: TimestampConfidence
    sync_sensitivity: SyncSensitivity
    analysis_notes: str | None = None

    @field_validator("layer_label")
    @classmethod
    def validate_layer_label(cls, value: str) -> str:
        return _validate_snake_case_label(value)

    @field_validator("onsets")
    @classmethod
    def validate_onsets(cls, onsets: list[float]) -> list[float]:
        for onset in onsets:
            if onset < 0:
                raise ValueError("onsets must be greater than or equal to 0")
        for prev, curr in zip(onsets, onsets[1:]):
            if curr < prev:
                raise ValueError("onsets must be sorted by time")
        return onsets

    @field_validator("coarse_segments")
    @classmethod
    def validate_coarse_segments_sorted(
        cls,
        segments: list[TimeSegmentModel] | None,
    ) -> list[TimeSegmentModel] | None:
        if segments is None:
            return None
        for prev, curr in zip(segments, segments[1:]):
            if curr.start < prev.start:
                raise ValueError("coarse_segments must be sorted by start time")
        return segments


class DraftContinuousSoundLayerModel(BaseModel):
    """Multi-agent 중간 단계에서 채워지는 continuous layer draft."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    layer_label: str = Field(min_length=1)
    sound_type: Literal["continuous"]
    segments: list[TimeSegmentModel] = Field(min_length=1)
    description: str = Field(min_length=1)
    preferred_generation_model: GenerationModel | None = None
    routing_reason: str | None = None
    timing_strategy: Literal["continuous"]
    timing_confidence: TimestampConfidence
    sync_sensitivity: SyncSensitivity
    analysis_notes: str | None = None

    @field_validator("layer_label")
    @classmethod
    def validate_layer_label(cls, value: str) -> str:
        return _validate_snake_case_label(value)

    @field_validator("segments")
    @classmethod
    def validate_segments_sorted(
        cls,
        segments: list[TimeSegmentModel],
    ) -> list[TimeSegmentModel]:
        for prev, curr in zip(segments, segments[1:]):
            if curr.start < prev.start:
                raise ValueError("segments must be sorted by start time")
        return segments


DraftSoundLayerModel = Annotated[
    DraftOnsetSoundLayerModel | DraftContinuousSoundLayerModel,
    Field(discriminator="sound_type"),
]


def _validate_layer_labels_unique(layers: list[DraftSoundLayerModel]) -> None:
    labels = [layer.layer_label for layer in layers]
    if len(labels) != len(set(labels)):
        raise ValueError("layer_label values must be unique inside a parent track")


class DraftActionTrackModel(BaseModel):
    """기존 action track 구조를 최대한 유지하는 multi-agent draft."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    event_type: str = Field(min_length=1)
    segments: list[TimeSegmentModel] = Field(min_length=1)
    description: str = Field(min_length=1)
    audio_type: Literal["sfx"]
    generation_model: GenerationModel | None = None
    routing_reason: str | None = None
    sound_layers: list[DraftSoundLayerModel] = Field(min_length=1)

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, value: str) -> str:
        return _validate_snake_case_label(value)

    @field_validator("segments")
    @classmethod
    def validate_segments_sorted(
        cls,
        segments: list[TimeSegmentModel],
    ) -> list[TimeSegmentModel]:
        for prev, curr in zip(segments, segments[1:]):
            if curr.start < prev.start:
                raise ValueError("segments must be sorted by start time")
        return segments

    @model_validator(mode="after")
    def validate_layers(self) -> "DraftActionTrackModel":
        _validate_layer_labels_unique(self.sound_layers)
        for layer in self.sound_layers:
            if layer.sound_type == "continuous":
                for segment in layer.segments:
                    if not _segment_is_inside_parent(self.segments, segment):
                        raise ValueError("continuous layer segment must be inside parent track segments")
            elif layer.sound_type == "onset":
                for segment in layer.coarse_segments or []:
                    if not _segment_is_inside_parent(self.segments, segment):
                        raise ValueError("onset layer coarse segment must be inside parent track segments")
                for onset in layer.onsets:
                    if not _onset_is_inside_parent(self.segments, onset):
                        raise ValueError("onset layer timestamp must be inside parent track segments")
        return self


class DraftBackgroundTrackModel(BaseModel):
    """기존 background track 구조를 최대한 유지하는 multi-agent draft."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ambience_type: str = Field(min_length=1)
    segments: list[TimeSegmentModel] = Field(min_length=1)
    description: str = Field(min_length=1)
    audio_type: Literal["ambience"]
    generation_model: GenerationModel | None = None
    routing_reason: str | None = None
    sound_layers: list[DraftSoundLayerModel] = Field(min_length=1)

    @field_validator("ambience_type")
    @classmethod
    def validate_ambience_type(cls, value: str) -> str:
        return _validate_snake_case_label(value)

    @field_validator("segments")
    @classmethod
    def validate_segments_sorted(
        cls,
        segments: list[TimeSegmentModel],
    ) -> list[TimeSegmentModel]:
        for prev, curr in zip(segments, segments[1:]):
            if curr.start < prev.start:
                raise ValueError("segments must be sorted by start time")
        return segments

    @model_validator(mode="after")
    def validate_layers(self) -> "DraftBackgroundTrackModel":
        _validate_layer_labels_unique(self.sound_layers)
        for layer in self.sound_layers:
            if layer.sound_type == "continuous":
                for segment in layer.segments:
                    if not _segment_is_inside_parent(self.segments, segment):
                        raise ValueError("continuous layer segment must be inside parent track segments")
            elif layer.sound_type == "onset":
                for segment in layer.coarse_segments or []:
                    if not _segment_is_inside_parent(self.segments, segment):
                        raise ValueError("onset layer coarse segment must be inside parent track segments")
                for onset in layer.onsets:
                    if not _onset_is_inside_parent(self.segments, onset):
                        raise ValueError("onset layer timestamp must be inside parent track segments")
        return self


class DraftTrackOutputModel(BaseModel):
    """Multi-agent 단계 간에 오가는 tracks.json 유사 draft."""
    model_config = ConfigDict(extra="forbid")

    action_tracks: list[DraftActionTrackModel] = Field(default_factory=list)
    background_tracks: list[DraftBackgroundTrackModel] = Field(default_factory=list)


class TimestampTaskModel(BaseModel):
    """Layer timestamp refinement를 원래 draft 위치에 주입하기 위한 작업 단위."""
    model_config = ConfigDict(extra="forbid")

    task_id: str
    track_kind: TrackKind
    track_index: int = Field(ge=0)
    layer_index: int = Field(ge=0)
    timing_strategy: Literal["single_event", "repeated_event"]
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    fps: float = Field(gt=0)
    layer_label: str

    @model_validator(mode="after")
    def validate_range(self) -> "TimestampTaskModel":
        if self.end <= self.start:
            raise ValueError("task end must be greater than start")
        return self


class TimestampRefinementModel(BaseModel):
    """Gemini high-fps refinement 응답 schema."""
    model_config = ConfigDict(extra="forbid")

    onsets: list[float] = Field(min_length=1)
    timestamp_confidence: TimestampConfidence
    analysis_notes: str | None = None

    @field_validator("onsets")
    @classmethod
    def validate_onsets(cls, onsets: list[float]) -> list[float]:
        for onset in onsets:
            if onset < 0:
                raise ValueError("onsets must be greater than or equal to 0")
        for prev, curr in zip(onsets, onsets[1:]):
            if curr < prev:
                raise ValueError("onsets must be sorted by time")
        return onsets


def strip_draft_layer_metadata(layer: dict[str, Any]) -> dict[str, Any]:
    """Final TrackOutputModel에 없는 draft-only 필드를 제거한다."""
    draft_only_keys = {
        "coarse_segments",
        "timing_strategy",
        "coarse_event_time",
        "timing_confidence",
        "sync_sensitivity",
        "analysis_notes",
    }
    return {
        key: value
        for key, value in layer.items()
        if key not in draft_only_keys and value is not None
    }
