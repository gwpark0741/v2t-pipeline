from typing import Literal, Annotated

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
    sound_layers: list[SoundLayerModel] = Field(default_factory=list)

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
    sound_layers: list[SoundLayerModel] = Field(default_factory=list)

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
