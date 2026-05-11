from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# 여러 timeline에 걸친 track의 시간 정보를 담는 모델
class TimeSegmentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: float = Field(ge=0)
    end: float = Field(ge=0)
    
    # 'start는 end보다 작아야 한다' 모델 검증기
    @model_validator(mode="after")
    def validate_range(self) -> "TimeSegmentModel":
        if self.end <= self.start:
            raise ValueError("segment end must be greater than start")
        return self


# action_tracks 필드와 검증 로직을 담는 모델
class ActionTrackModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    event_type: str = Field(min_length=1)
    segments: list[TimeSegmentModel] = Field(min_length=1)
    description: str = Field(min_length=1)
    audio_type: Literal["sfx"]

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


# background_tracks 필드와 검증 로직을 담는 모델
class BackgroundTrackModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    ambience_type: str = Field(min_length=1)
    segments: list[TimeSegmentModel] = Field(min_length=1)
    description: str = Field(min_length=1)
    audio_type: Literal["ambience"]

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


# 전체 출력 스키마 모델
class TrackOutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_tracks: list[ActionTrackModel] = Field(default_factory=list)
    background_tracks: list[BackgroundTrackModel] = Field(default_factory=list)
