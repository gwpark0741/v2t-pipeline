"""
V2T tracks.json → AudioPlan 변환 모듈.

V2T 파이프라인이 출력하는 ActionTrack / BackgroundTrack + SoundLayer 구조를
V2A 파이프라인의 AudioPlan (AudioPlanItem 리스트) 형식으로 변환합니다.

변환 시 활용하는 V2T 정보:
  - track.description, sound_layer.description → AudioPlanItem.description
  - track.segments / sound_layer.segments / sound_layer.onsets → time
  - track.audio_type (sfx / ambience) → AudioPlanItem.type
  - track.generation_model (t2a / v2a) → description에 힌트로 첨부
  - sound_layer.timestamp_confidence → AudioPlanItem.confidence 매핑
  - sound_layer.preferred_generation_model → description 힌트
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── onset → 구간 변환 기본 듀레이션 (초) ──────────────────────────────────────
_DEFAULT_ONSET_HALF_WIDTH = 0.5   # onset ± 0.5s → 1초 구간

# ── timestamp_confidence → confidence 매핑 ────────────────────────────────────
_CONFIDENCE_MAP: dict[str, float] = {
    "high": 1.0,
    "medium": 0.8,
    "low": 0.6,
}

# ── audio_type → V2A plan item type 매핑 ──────────────────────────────────────
_TYPE_MAP: dict[str, str] = {
    "sfx": "sfx",
    "ambience": "ambience",
}


@dataclass
class AudioPlanItem:
    """V2A 파이프라인의 AudioPlanItem에 대응하는 데이터 클래스."""

    item_id: str
    type: str           # sfx | music | ambience | dialogue | silence
    time: tuple[float, float]
    description: str
    volume: float = 0.8
    intensity: float = 0.5
    pan: float = 0.0
    confidence: float = 1.0
    track_id: str | None = None
    generation_model: str = "t2a"


@dataclass
class AudioPlan:
    """V2A 파이프라인의 AudioPlan에 대응하는 데이터 클래스."""

    items: list[AudioPlanItem] = field(default_factory=list)
    total_duration: float = 0.0


def convert_tracks_to_audio_plan(
    tracks_data: dict[str, Any],
    *,
    onset_half_width: float = _DEFAULT_ONSET_HALF_WIDTH,
) -> AudioPlan:
    """
    V2T 파이프라인의 tracks.json 데이터를 AudioPlan으로 변환합니다.

    Parameters
    ----------
    tracks_data : dict
        tracks.json 을 json.loads() 한 결과 딕셔너리.
        필수 키: "action_tracks", "background_tracks"
        선택 키: "video_duration"

    onset_half_width : float
        onset 타입 sound_layer의 각 onset 포인트를
        (onset - half_width, onset + half_width) 구간으로 변환할 때 사용.

    Returns
    -------
    AudioPlan
        변환된 오디오 플랜.
    """
    items: list[AudioPlanItem] = []
    counter: dict[str, int] = {}  # type별 카운터 (item_id 생성용)

    video_duration = tracks_data.get("video_duration", 0.0) or 0.0

    # ── ActionTrack 변환 ──────────────────────────────────────────────────────
    for track in tracks_data.get("action_tracks", []):
        _convert_track(
            track=track,
            track_type_key="event_type",
            default_audio_type="sfx",
            items=items,
            counter=counter,
            video_duration=video_duration,
            onset_half_width=onset_half_width,
            default_volume=0.85,
        )

    # ── BackgroundTrack 변환 ──────────────────────────────────────────────────
    for track in tracks_data.get("background_tracks", []):
        _convert_track(
            track=track,
            track_type_key="ambience_type",
            default_audio_type="ambience",
            items=items,
            counter=counter,
            video_duration=video_duration,
            onset_half_width=onset_half_width,
            default_volume=0.6,
        )

    # 시간 순서로 정렬
    items.sort(key=lambda x: x.time[0])

    return AudioPlan(items=items, total_duration=video_duration)


# ── 내부 변환 함수 ────────────────────────────────────────────────────────────


def _convert_track(
    *,
    track: dict[str, Any],
    track_type_key: str,
    default_audio_type: str,
    items: list[AudioPlanItem],
    counter: dict[str, int],
    video_duration: float,
    onset_half_width: float,
    default_volume: float,
) -> None:
    """하나의 Track (Action 또는 Background)을 AudioPlanItem 리스트에 추가."""

    audio_type = track.get("audio_type", default_audio_type)
    plan_type = _TYPE_MAP.get(audio_type, audio_type)
    track_id = track.get("track_id", "")
    track_desc = track.get("description", "")
    track_label = track.get(track_type_key, "")
    generation_model = track.get("generation_model", "t2a")
    routing_reason = track.get("routing_reason", "")

    sound_layers = track.get("sound_layers", [])

    if sound_layers:
        # sound_layer 기반 변환 (더 세밀한 정보 활용)
        for layer in sound_layers:
            _convert_sound_layer(
                layer=layer,
                plan_type=plan_type,
                track_id=track_id,
                track_desc=track_desc,
                track_label=track_label,
                generation_model=generation_model,
                routing_reason=routing_reason,
                items=items,
                counter=counter,
                video_duration=video_duration,
                onset_half_width=onset_half_width,
                default_volume=default_volume,
            )
    else:
        # sound_layer가 없으면 track의 segments를 직접 사용
        segments = track.get("segments", [])
        for seg in segments:
            start = float(seg.get("start", 0))
            end = float(seg.get("end", 0))
            if end <= start:
                continue

            item_id = _next_item_id(counter, plan_type)
            desc = _build_description(
                layer_desc=track_desc,
                track_label=track_label,
                generation_model=generation_model,
                routing_reason=routing_reason,
            )
            items.append(AudioPlanItem(
                item_id=item_id,
                type=plan_type,
                time=(start, end),
                description=desc,
                volume=default_volume,
                intensity=0.5,
                pan=0.0,
                confidence=1.0,
                track_id=track_id,
            ))


def _convert_sound_layer(
    *,
    layer: dict[str, Any],
    plan_type: str,
    track_id: str,
    track_desc: str,
    track_label: str,
    generation_model: str,
    routing_reason: str,
    items: list[AudioPlanItem],
    counter: dict[str, int],
    video_duration: float,
    onset_half_width: float,
    default_volume: float,
) -> None:
    """하나의 SoundLayer를 AudioPlanItem(들)로 변환."""

    sound_type = layer.get("sound_type", "")
    layer_desc = layer.get("description", track_desc)
    layer_label = layer.get("layer_label", track_label)

    # preferred_generation_model 활용 (layer별 t2a/v2a 라우팅 정보)
    layer_gen_model = layer.get("preferred_generation_model", generation_model)
    layer_routing_reason = layer.get("routing_reason", routing_reason)

    # timestamp_confidence → confidence 매핑
    confidence = _CONFIDENCE_MAP.get(
        layer.get("timestamp_confidence", "high"), 1.0
    )

    desc = _build_description(
        layer_desc=layer_desc,
        track_label=layer_label,
        generation_model=layer_gen_model,
        routing_reason=layer_routing_reason,
    )

    if sound_type == "continuous":
        # continuous 타입: 각 segment를 직접 변환
        for seg in layer.get("segments", []):
            start = float(seg.get("start", 0))
            end = float(seg.get("end", 0))
            if end <= start:
                continue

            item_id = _next_item_id(counter, plan_type)
            items.append(AudioPlanItem(
                item_id=item_id,
                type=plan_type,
                time=(start, end),
                description=desc,
                volume=default_volume,
                intensity=0.5,
                pan=0.0,
                confidence=confidence,
                track_id=track_id,
                generation_model=layer_gen_model,
            ))

    elif sound_type == "onset":
        # onset 타입: 각 onset 포인트를 구간으로 확장
        for onset in layer.get("onsets", []):
            onset = float(onset)
            start = max(0.0, onset - onset_half_width)
            end = onset + onset_half_width
            if video_duration > 0:
                end = min(end, video_duration)
            if end <= start:
                continue

            item_id = _next_item_id(counter, plan_type)
            items.append(AudioPlanItem(
                item_id=item_id,
                type=plan_type,
                time=(start, end),
                description=desc,
                volume=default_volume,
                intensity=0.6,   # onset은 보통 임팩트가 강함
                pan=0.0,
                confidence=confidence,
                track_id=track_id,
                generation_model=layer_gen_model,
            ))
    else:
        logger.warning("Unknown sound_type '%s' in layer, skipping.", sound_type)


def _next_item_id(counter: dict[str, int], plan_type: str) -> str:
    """고유한 item_id를 생성합니다."""
    idx = counter.get(plan_type, 0)
    counter[plan_type] = idx + 1
    return f"plan_{plan_type}_{idx}"


def _build_description(
    *,
    layer_desc: str,
    track_label: str,
    generation_model: str,
    routing_reason: str,
) -> str:
    """
    설명 텍스트를 조합합니다. V2T의 routing 정보를 힌트로 포함합니다.

    generation_model이 'v2a'이면 비디오 연동이 필요한 소리이므로
    설명에 시각적 컨텍스트 힌트를 추가합니다.
    """
    parts: list[str] = []

    if track_label:
        parts.append(f"[{track_label}]")

    if layer_desc:
        parts.append(layer_desc.strip())

    # V2A 모델 라우팅 힌트 추가
    if generation_model == "v2a" and routing_reason:
        parts.append(f"(Note: visually synchronized — {routing_reason.strip()})")

    return " ".join(parts) if parts else "audio"
