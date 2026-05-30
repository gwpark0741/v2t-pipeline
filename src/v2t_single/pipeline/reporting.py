import json
import shutil
from html import escape
from pathlib import Path
from typing import Any, cast

from v2t_single.pipeline.state import ActionTrack, BackgroundTrack, PipelineState


def _format_seconds(seconds: float) -> str:
    minutes = int(seconds // 60)
    remainder = seconds - (minutes * 60)
    return f"{minutes:02d}:{remainder:05.2f}"


def _build_track_row(
    track_kind: str,
    track_id: str,
    label: str,
    description: str,
    segments: list[dict[str, float]],
    duration: float,
    generation_model: str | None = None,
    routing_reason: str | None = None,
) -> str:
    blocks: list[str] = []
    for segment in segments:
        start = segment["start"]
        end = segment["end"]
        left = 0.0 if duration == 0 else (start / duration) * 100
        width = 0.0 if duration == 0 else ((end - start) / duration) * 100
        blocks.append(
            f"""
            <div class="segment segment-{track_kind}" style="left: {left:.4f}%; width: {width:.4f}%;">
              <span class="segment-time">{_format_seconds(start)} - {_format_seconds(end)}</span>
            </div>
            """
        )

    routing_badge = ""
    routing_detail = ""
    if generation_model:
        routing_badge = (
            f'<span class="routing-badge routing-badge-{escape(generation_model)}">'
            f'{escape(generation_model)}</span>'
        )
        if routing_reason:
            routing_detail = (
                f'<div class="routing-reason">Route: {escape(routing_reason)}</div>'
            )

    return f"""
    <div class="track-row">
      <div class="track-meta">
        <div class="track-id track-id-{track_kind}">{escape(track_id)}</div>
        <div class="track-label">{escape(label)}</div>
        <div class="track-badges">
          <span class="track-kind">{escape(track_kind)}</span>
          {routing_badge}
        </div>
        <div class="track-description">{escape(description)}</div>
        {routing_detail}
      </div>
      <div class="track-lane">
        {''.join(blocks)}
      </div>
    </div>
    """


def _build_continuous_layer_blocks(
    layer_kind: str,
    segments: list[dict[str, float]],
    duration: float,
) -> str:
    blocks: list[str] = []
    for segment in segments:
        start = segment["start"]
        end = segment["end"]
        left = 0.0 if duration == 0 else (start / duration) * 100
        width = 0.0 if duration == 0 else ((end - start) / duration) * 100
        blocks.append(
            f"""
            <div class="layer-segment layer-segment-{layer_kind}" style="left: {left:.4f}%; width: {width:.4f}%;">
              <span class="segment-time">{_format_seconds(start)} - {_format_seconds(end)}</span>
            </div>
            """
        )
    return "".join(blocks)


def _build_onset_layer_blocks(
    onsets: list[float],
    duration: float,
) -> str:
    markers: list[str] = []
    for onset in onsets:
        left = 0.0 if duration == 0 else (onset / duration) * 100
        markers.append(
            f"""
            <div class="onset-marker" style="left: {left:.4f}%;">
              <span class="onset-time">{_format_seconds(onset)}</span>
            </div>
            """
        )
    return "".join(markers)


def _build_layer_row(
    track_kind: str,
    track_id: str,
    layer: dict[str, Any],
    duration: float,
) -> str:
    sound_type = layer.get("sound_type", "unknown")
    layer_id = layer.get("layer_id")
    layer_label = layer.get("layer_label", "unknown_layer")
    description = layer.get("description", "")
    preferred_generation_model = layer.get("preferred_generation_model")
    routing_reason = layer.get("routing_reason")
    timestamp_confidence = layer.get("timestamp_confidence")
    layer_kind_class = f"{track_kind}-{sound_type}"

    if sound_type == "onset":
        layer_blocks = _build_onset_layer_blocks(layer.get("onsets", []), duration)
        timing_summary = f"{len(layer.get('onsets', []))} onsets"
    elif sound_type == "continuous":
        layer_blocks = _build_continuous_layer_blocks(
            track_kind,
            layer.get("segments", []),
            duration,
        )
        timing_summary = f"{len(layer.get('segments', []))} segments"
    else:
        layer_blocks = ""
        timing_summary = "unknown timing"

    routing_badge = ""
    routing_detail = ""
    if preferred_generation_model:
        routing_badge = (
            f'<span class="routing-badge routing-badge-{escape(preferred_generation_model)}">'
            f'{escape(preferred_generation_model)}</span>'
        )
        if routing_reason:
            routing_detail = (
                f'<div class="routing-reason">Route: {escape(routing_reason)}</div>'
            )

    confidence_badge = ""
    if timestamp_confidence:
        confidence_badge = (
            f'<span class="confidence-badge confidence-badge-{escape(timestamp_confidence)}">'
            f'{escape(timestamp_confidence)} confidence</span>'
        )

    layer_id_ref = ""
    if layer_id:
        layer_id_ref = f'<div class="layer-id-ref">{escape(layer_id)}</div>'

    return f"""
    <div class="layer-row layer-row-{track_kind}">
      <div class="track-meta layer-meta">
        {layer_id_ref}
        <div class="track-label">{escape(layer_label)}</div>
        <div class="layer-badges">
          <span class="layer-type layer-type-{escape(sound_type)}">{escape(sound_type)}</span>
          <span class="layer-count">{escape(timing_summary)}</span>
          {routing_badge}
          {confidence_badge}
        </div>
        <div class="track-description">{escape(description)}</div>
        {routing_detail}
      </div>
      <div class="track-lane layer-lane layer-lane-{escape(layer_kind_class)}">
        {layer_blocks}
      </div>
    </div>
    """


def _build_layer_group(
    track_kind: str,
    track_id: str,
    label: str,
    description: str,
    segments: list[dict[str, float]],
    layers: list[dict[str, Any]],
    duration: float,
    generation_model: str | None = None,
    routing_reason: str | None = None,
) -> str:
    parent_row = _build_track_row(
        track_kind=track_kind,
        track_id=track_id,
        label=label,
        description=description,
        segments=segments,
        duration=duration,
        generation_model=generation_model,
        routing_reason=routing_reason,
    ).replace('class="track-row"', 'class="track-row layer-parent-row"', 1)

    if not layers:
        layer_rows = '<div class="layer-empty">No finer sound layers for this parent track.</div>'
    else:
        layer_rows = "".join(
            _build_layer_row(
                track_kind=track_kind,
                track_id=track_id,
                layer=layer,
                duration=duration,
            )
            for layer in layers
        )

    return f"""
    <section class="layer-group">
      {parent_row}
      {layer_rows}
    </section>
    """


def _build_timeline_ticks(duration: float, steps: int = 6) -> str:
    if duration <= 0:
        return ""

    ticks: list[str] = []
    for index in range(steps + 1):
        time_value = (duration / steps) * index
        left = (index / steps) * 100
        ticks.append(
            f"""
            <div class="tick" style="left: {left:.4f}%;">
              <span>{_format_seconds(time_value)}</span>
            </div>
            """
        )
    return "".join(ticks)


def build_report_html(state: PipelineState, video_src: str) -> str:
    """HTML 보고서를 생성하는 함수: state를 입력으로 받아, 필요한 필드를 추출하여 HTML 보고서 생성 -> HTML 문자열 반환"""
    video_path = state["video_path"]
    duration = state["video_duration"]
    run_id = state["run_id"]
    action_tracks: list[ActionTrack] = state.get("action_tracks", [])
    background_tracks: list[BackgroundTrack] = state.get("background_tracks", [])

    rows: list[str] = []
    layer_groups: list[str] = []
    for track in action_tracks:
        rows.append(
            _build_track_row(
                track_kind="action",
                track_id=track["track_id"],
                label=track["event_type"],
                description=track["description"],
                segments=track["segments"],
                duration=duration,
                generation_model=track.get("generation_model"),
                routing_reason=track.get("routing_reason"),
            )
        )
        layer_groups.append(
            _build_layer_group(
                track_kind="action",
                track_id=track["track_id"],
                label=track["event_type"],
                description=track["description"],
                segments=track["segments"],
                layers=track.get("sound_layers", []),
                duration=duration,
                generation_model=track.get("generation_model"),
                routing_reason=track.get("routing_reason"),
            )
        )
    for track in background_tracks:
        rows.append(
            _build_track_row(
                track_kind="background",
                track_id=track["track_id"],
                label=track["ambience_type"],
                description=track["description"],
                segments=track["segments"],
                duration=duration,
                generation_model=track.get("generation_model"),
                routing_reason=track.get("routing_reason"),
            )
        )
        layer_groups.append(
            _build_layer_group(
                track_kind="background",
                track_id=track["track_id"],
                label=track["ambience_type"],
                description=track["description"],
                segments=track["segments"],
                layers=track.get("sound_layers", []),
                duration=duration,
                generation_model=track.get("generation_model"),
                routing_reason=track.get("routing_reason"),
            )
        )

    timeline_ticks = _build_timeline_ticks(duration)
    escaped_video_src = escape(video_src)
    layer_count = sum(len(track.get("sound_layers", [])) for track in action_tracks + background_tracks)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>V2T Report - {escape(run_id)}</title>
  <style>
    :root {{
      --bg: #f5f1e8;
      --panel: #fffaf0;
      --line: #d6cbbb;
      --text: #1f1a14;
      --muted: #6c6257;
      --action: #1e8f6f;
      --background: #b36b00;
      --playhead: #c1121f;
      --shadow: 0 12px 30px rgba(31, 26, 20, 0.08);
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: "SF Pro Text", "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(255, 255, 255, 0.95), rgba(245, 241, 232, 0.95)),
        linear-gradient(135deg, #f7f2e7, #efe4cf);
      color: var(--text);
    }}

    .page {{
      display: grid;
      grid-template-columns: minmax(320px, 420px) 1fr;
      gap: 24px;
      min-height: 100vh;
      padding: 24px;
    }}

    .video-panel,
    .timeline-panel {{
      background: var(--panel);
      border: 1px solid rgba(214, 203, 187, 0.8);
      border-radius: 20px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }}

    .video-panel {{
      position: sticky;
      top: 24px;
      align-self: start;
    }}

    .panel-header {{
      padding: 18px 20px 10px;
      border-bottom: 1px solid rgba(214, 203, 187, 0.7);
      background: linear-gradient(180deg, rgba(255, 252, 246, 0.95), rgba(255, 250, 240, 0.85));
    }}

    .title {{
      margin: 0;
      font-size: 1.15rem;
      font-weight: 700;
    }}

    .subtitle {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 0.92rem;
    }}

    .video-wrap {{
      padding: 20px;
    }}

    video {{
      width: 100%;
      border-radius: 14px;
      background: #000;
    }}

    .summary {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      padding: 0 20px 20px;
    }}

    .summary-card {{
      padding: 14px;
      border: 1px solid rgba(214, 203, 187, 0.8);
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.65);
    }}

    .summary-label {{
      color: var(--muted);
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}

    .summary-value {{
      margin-top: 6px;
      font-size: 1rem;
      font-weight: 700;
      word-break: break-word;
    }}

    .timeline-panel {{
      padding-bottom: 20px;
    }}

    .tabs {{
      display: flex;
      gap: 8px;
      padding: 16px 20px 0;
      border-bottom: 1px solid rgba(214, 203, 187, 0.65);
    }}

    .tab-button {{
      appearance: none;
      border: 1px solid rgba(214, 203, 187, 0.9);
      border-bottom: 0;
      padding: 10px 14px;
      border-radius: 12px 12px 0 0;
      background: rgba(255, 255, 255, 0.55);
      color: var(--muted);
      font-weight: 800;
      cursor: pointer;
    }}

    .tab-button.active {{
      color: var(--text);
      background: rgba(255, 250, 240, 0.96);
    }}

    .tab-panel {{
      display: none;
    }}

    .tab-panel.active {{
      display: block;
    }}

    .timeline-wrap {{
      padding: 20px;
    }}

    .timeline-scale {{
      position: relative;
      height: 34px;
      margin: 0 0 18px 260px;
      border-top: 2px solid var(--line);
    }}

    .tick {{
      position: absolute;
      top: -2px;
      width: 1px;
      height: 12px;
      background: var(--line);
    }}

    .tick span {{
      position: absolute;
      top: 14px;
      transform: translateX(-50%);
      font-size: 0.78rem;
      color: var(--muted);
      white-space: nowrap;
    }}

    .timeline-body {{
      position: relative;
      cursor: pointer;
      user-select: none;
      touch-action: none;
    }}

    .timeline-body.is-scrubbing {{
      cursor: grabbing;
    }}

    .playhead {{
      position: absolute;
      top: 0;
      bottom: 0;
      left: 0;
      width: 2px;
      transform: translateX(260px);
      background: var(--playhead);
      pointer-events: none;
      z-index: 5;
      box-shadow: 0 0 0 1px rgba(193, 18, 31, 0.18);
      will-change: transform;
    }}

    .playhead::before {{
      content: "";
      position: absolute;
      top: -10px;
      left: -5px;
      width: 12px;
      height: 12px;
      border-radius: 999px;
      background: var(--playhead);
    }}

    .track-row {{
      display: grid;
      grid-template-columns: 240px 1fr;
      gap: 20px;
      align-items: center;
      margin-bottom: 18px;
    }}

    .track-meta {{
      padding-right: 8px;
      display: flex;
      flex-direction: column;
      align-items: flex-start;
    }}

    .track-id {{
      display: inline-flex;
      align-items: center;
      width: fit-content;
      margin-bottom: 8px;
      padding: 4px 9px;
      border-radius: 999px;
      font-size: 0.73rem;
      font-weight: 800;
      line-height: 1;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      font-family: ui-monospace, "SFMono-Regular", "SF Mono", "Menlo", "Consolas", monospace;
      border: 1px solid transparent;
    }}

    .track-id-action {{
      background: rgba(30, 143, 111, 0.12);
      color: #136b53;
      border-color: rgba(30, 143, 111, 0.22);
    }}

    .track-id-background {{
      background: rgba(179, 107, 0, 0.12);
      color: #8a5400;
      border-color: rgba(179, 107, 0, 0.22);
    }}


    .track-label {{
      font-weight: 700;
      font-size: 0.98rem;
    }}

    .track-badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 6px;
      align-items: center;
    }}

    .track-kind {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: white;
      background: #7d7468;
    }}

    .track-description {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.86rem;
      line-height: 1.45;
    }}

    .routing-reason {{
      margin-top: 6px;
      padding: 7px 9px;
      border: 1px solid rgba(214, 203, 187, 0.85);
      border-radius: 10px;
      background: rgba(255, 255, 255, 0.58);
      color: #5b5147;
      font-size: 0.78rem;
      line-height: 1.35;
    }}

    .routing-badge {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 900;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: white;
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.24);
    }}

    .routing-badge-t2a {{
      background: linear-gradient(135deg, #5b6f95, #7692bf);
    }}

    .routing-badge-v2a {{
      background: linear-gradient(135deg, #8b3f17, #d46b2c);
    }}

    .confidence-badge {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 0.75rem;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #2b241d;
      border: 1px solid rgba(214, 203, 187, 0.9);
    }}

    .confidence-badge-high {{
      background: rgba(30, 143, 111, 0.15);
      color: #136b53;
      border-color: rgba(30, 143, 111, 0.25);
    }}

    .confidence-badge-medium {{
      background: rgba(218, 154, 45, 0.18);
      color: #8a5400;
      border-color: rgba(218, 154, 45, 0.3);
    }}

    .confidence-badge-low {{
      background: rgba(193, 18, 31, 0.12);
      color: #8d0d17;
      border-color: rgba(193, 18, 31, 0.25);
    }}

    .track-lane {{
      position: relative;
      min-height: 56px;
      border: 1px solid rgba(214, 203, 187, 0.8);
      border-radius: 14px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.95), rgba(249, 244, 235, 0.92)),
        repeating-linear-gradient(
          90deg,
          transparent 0,
          transparent calc(20% - 1px),
          rgba(214, 203, 187, 0.3) calc(20% - 1px),
          rgba(214, 203, 187, 0.3) 20%
        );
      overflow: hidden;
    }}

    .segment {{
      position: absolute;
      top: 9px;
      bottom: 9px;
      min-width: 6px;
      border-radius: 10px;
      padding: 6px 8px;
      display: flex;
      align-items: center;
      white-space: nowrap;
      overflow: hidden;
      font-size: 0.76rem;
      font-weight: 700;
      color: white;
    }}

    .segment-action {{
      background: linear-gradient(135deg, #1e8f6f, #49b38f);
    }}

    .segment-background {{
      background: linear-gradient(135deg, #b36b00, #da9a2d);
    }}

    .layer-group {{
      margin-bottom: 28px;
      padding-bottom: 18px;
      border-bottom: 1px solid rgba(214, 203, 187, 0.75);
    }}

    .layer-group:last-child {{
      border-bottom: 0;
      margin-bottom: 0;
    }}

    .layer-row {{
      display: grid;
      grid-template-columns: 240px 1fr;
      gap: 20px;
      align-items: center;
      margin: 0 0 10px;
    }}

    .layer-parent-row {{
      margin-bottom: 10px;
    }}

    .layer-parent-row .track-lane {{
      min-height: 38px;
      border-style: dashed;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.88), rgba(249, 244, 235, 0.76)),
        repeating-linear-gradient(
          90deg,
          transparent 0,
          transparent calc(20% - 1px),
          rgba(214, 203, 187, 0.24) calc(20% - 1px),
          rgba(214, 203, 187, 0.24) 20%
        );
    }}

    .layer-meta {{
      padding-left: 16px;
      border-left: 3px solid rgba(125, 116, 104, 0.35);
    }}

    .layer-row-action .layer-meta {{
      border-left-color: rgba(30, 143, 111, 0.48);
    }}

    .layer-row-background .layer-meta {{
      border-left-color: rgba(179, 107, 0, 0.5);
    }}

    .layer-id-ref {{
      margin-bottom: 6px;
      color: #3f3831;
      font-family: ui-monospace, "SFMono-Regular", "SF Mono", "Menlo", "Consolas", monospace;
      font-size: 0.76rem;
      font-weight: 900;
      line-height: 1.25;
      word-break: break-word;
    }}

    .layer-badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      margin-top: 6px;
      align-items: center;
    }}

    .layer-type {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: white;
    }}

    .layer-type-continuous {{
      background: #315f9d;
    }}

    .layer-type-onset {{
      background: #c1121f;
    }}

    .layer-count {{
      display: inline-block;
      padding: 3px 8px;
      border-radius: 999px;
      font-size: 0.75rem;
      letter-spacing: 0.04em;
      color: var(--muted);
      background: rgba(255, 255, 255, 0.72);
      border: 1px solid rgba(214, 203, 187, 0.8);
    }}

    .layer-lane {{
      min-height: 44px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(246, 249, 250, 0.95)),
        repeating-linear-gradient(
          90deg,
          transparent 0,
          transparent calc(20% - 1px),
          rgba(159, 177, 192, 0.26) calc(20% - 1px),
          rgba(159, 177, 192, 0.26) 20%
        );
    }}

    .layer-lane-action-continuous {{
      border-color: rgba(49, 95, 157, 0.34);
    }}

    .layer-lane-background-continuous {{
      border-color: rgba(49, 95, 157, 0.34);
    }}

    .layer-lane-action-onset,
    .layer-lane-background-onset {{
      border-color: rgba(193, 18, 31, 0.34);
    }}

    .layer-segment {{
      position: absolute;
      top: 10px;
      bottom: 10px;
      min-width: 6px;
      border-radius: 8px;
      padding: 5px 8px;
      display: flex;
      align-items: center;
      white-space: nowrap;
      overflow: hidden;
      font-size: 0.72rem;
      font-weight: 800;
      color: white;
    }}

    .layer-segment-action {{
      background: linear-gradient(135deg, #315f9d, #5d8bc6);
    }}

    .layer-segment-background {{
      background: linear-gradient(135deg, #315f9d, #5d8bc6);
    }}

    .onset-marker {{
      position: absolute;
      top: 8px;
      bottom: 8px;
      width: 2px;
      transform: translateX(-50%);
      background: #c1121f;
    }}

    .onset-marker::before {{
      content: "";
      position: absolute;
      top: 50%;
      left: 50%;
      width: 12px;
      height: 12px;
      border-radius: 999px;
      background: #c1121f;
      box-shadow: 0 0 0 4px rgba(193, 18, 31, 0.14);
      transform: translate(-50%, -50%);
    }}

    .onset-time {{
      position: absolute;
      top: -17px;
      left: 50%;
      transform: translateX(-50%);
      color: #8d0d17;
      font-size: 0.68rem;
      font-weight: 800;
      white-space: nowrap;
    }}

    .layer-empty {{
      margin: 0 0 0 34px;
      padding: 14px 16px;
      color: var(--muted);
      border: 1px dashed var(--line);
      border-radius: 14px;
      background: rgba(255, 255, 255, 0.5);
    }}

    .segment-time {{
      text-overflow: ellipsis;
      overflow: hidden;
    }}

    .empty {{
      margin-left: 260px;
      padding: 24px;
      color: var(--muted);
      border: 1px dashed var(--line);
      border-radius: 14px;
      text-align: center;
    }}

    @media (max-width: 1100px) {{
      .page {{
        grid-template-columns: 1fr;
      }}

      .video-panel {{
        position: static;
      }}

      .timeline-scale,
      .playhead,
      .empty,
      .layer-empty {{
        margin-left: 0;
        left: 0;
      }}

      .track-row,
      .layer-row {{
        grid-template-columns: 1fr;
        gap: 10px;
      }}

      .layer-row {{
        margin-left: 0;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="video-panel">
      <div class="panel-header">
        <h1 class="title">V2T Track Report</h1>
        <p class="subtitle">Run ID: {escape(run_id)}</p>
      </div>
      <div class="video-wrap">
        <video id="report-video" controls preload="metadata" src="{escaped_video_src}"></video>
      </div>
      <div class="summary">
        <div class="summary-card">
          <div class="summary-label">Video</div>
          <div class="summary-value">{escape(Path(video_path).name)}</div>
        </div>
        <div class="summary-card">
          <div class="summary-label">Duration</div>
          <div class="summary-value">{_format_seconds(duration)}</div>
        </div>
        <div class="summary-card">
          <div class="summary-label">Action Tracks</div>
          <div class="summary-value">{len(action_tracks)}</div>
        </div>
        <div class="summary-card">
          <div class="summary-label">Background Tracks</div>
          <div class="summary-value">{len(background_tracks)}</div>
        </div>
        <div class="summary-card">
          <div class="summary-label">Sound Layers</div>
          <div class="summary-value">{layer_count}</div>
        </div>
      </div>
    </section>

    <section class="timeline-panel">
      <div class="panel-header">
        <h2 class="title">Track Timeline</h2>
        <p class="subtitle">The red playhead follows the current playback time of the video.</p>
      </div>
      <div class="tabs" role="tablist" aria-label="Report views">
        <button class="tab-button active" type="button" data-tab-target="major-tab">Major Tracks</button>
        <button class="tab-button" type="button" data-tab-target="layers-tab">Sound Layers</button>
      </div>
      <div id="major-tab" class="tab-panel active">
        <div class="timeline-wrap">
          <div class="timeline-scale">{timeline_ticks}</div>
          <div class="timeline-body">
            <div class="playhead"></div>
            {''.join(rows) if rows else '<div class="empty">No tracks were generated for this run.</div>'}
          </div>
        </div>
      </div>
      <div id="layers-tab" class="tab-panel">
        <div class="timeline-wrap">
          <div class="timeline-scale">{timeline_ticks}</div>
          <div class="timeline-body">
            <div class="playhead"></div>
            {''.join(layer_groups) if layer_groups else '<div class="empty">No sound layers were generated for this run.</div>'}
          </div>
        </div>
      </div>
    </section>
  </div>

  <script>
    const video = document.getElementById("report-video");
    const playheads = Array.from(document.querySelectorAll(".playhead"));
    const timelineBodies = Array.from(document.querySelectorAll(".timeline-body"));
    const tabButtons = Array.from(document.querySelectorAll(".tab-button"));
    const tabPanels = Array.from(document.querySelectorAll(".tab-panel"));
    const fallbackDuration = {duration};
    let playheadFrameId = null;
    let isScrubbing = false;

    function updatePlayhead() {{
      if (!video || !playheads.length) return;

      const effectiveDuration =
        Number.isFinite(video.duration) && video.duration > 0
          ? video.duration
          : fallbackDuration;

      if (!effectiveDuration) return;

      const progress = Math.max(0, Math.min(1, video.currentTime / effectiveDuration));

      playheads.forEach((playhead) => {{
        if (window.innerWidth <= 1100) {{
          const laneWidth = playhead.parentElement.clientWidth;
          playhead.style.transform = `translateX(${{laneWidth * progress}}px)`;
          return;
        }}

        const laneOffset = 260;
        const laneWidth = playhead.parentElement.clientWidth - laneOffset;
        playhead.style.transform = `translateX(${{laneOffset + (laneWidth * progress)}}px)`;
      }});
    }}

    function getEffectiveDuration() {{
      if (!video) return fallbackDuration;
      return Number.isFinite(video.duration) && video.duration > 0
        ? video.duration
        : fallbackDuration;
    }}

    function getTimelineProgressFromEvent(event, timelineBody) {{
      const rect = timelineBody.getBoundingClientRect();
      const laneOffset = window.innerWidth <= 1100 ? 0 : 260;
      const laneStart = rect.left + laneOffset;
      const laneWidth = Math.max(1, rect.width - laneOffset);
      const progress = (event.clientX - laneStart) / laneWidth;
      return Math.max(0, Math.min(1, progress));
    }}

    function seekTimeline(event, timelineBody) {{
      if (!video) return;
      const effectiveDuration = getEffectiveDuration();
      if (!effectiveDuration) return;
      const progress = getTimelineProgressFromEvent(event, timelineBody);
      video.currentTime = progress * effectiveDuration;
      updatePlayhead();
    }}

    function startScrubbing(event) {{
      if (!video) return;
      const timelineBody = event.currentTarget;
      isScrubbing = true;
      timelineBodies.forEach((body) => body.classList.add("is-scrubbing"));
      timelineBody.setPointerCapture?.(event.pointerId);
      seekTimeline(event, timelineBody);
    }}

    function scrubTimeline(event) {{
      if (!isScrubbing) return;
      seekTimeline(event, event.currentTarget);
    }}

    function stopScrubbing(event) {{
      if (!isScrubbing) return;
      isScrubbing = false;
      timelineBodies.forEach((body) => body.classList.remove("is-scrubbing"));
      event.currentTarget.releasePointerCapture?.(event.pointerId);
      updatePlayhead();
    }}

    function tickPlayhead() {{
      updatePlayhead();
      playheadFrameId = window.requestAnimationFrame(tickPlayhead);
    }}

    function startPlayheadLoop() {{
      if (playheadFrameId !== null) return;
      playheadFrameId = window.requestAnimationFrame(tickPlayhead);
    }}

    function stopPlayheadLoop() {{
      if (playheadFrameId === null) return;
      window.cancelAnimationFrame(playheadFrameId);
      playheadFrameId = null;
      updatePlayhead();
    }}

    tabButtons.forEach((button) => {{
      button.addEventListener("click", () => {{
        const targetId = button.dataset.tabTarget;
        tabButtons.forEach((item) => item.classList.toggle("active", item === button));
        tabPanels.forEach((panel) => panel.classList.toggle("active", panel.id === targetId));
        updatePlayhead();
      }});
    }});

    timelineBodies.forEach((timelineBody) => {{
      timelineBody.addEventListener("pointerdown", startScrubbing);
      timelineBody.addEventListener("pointermove", scrubTimeline);
      timelineBody.addEventListener("pointerup", stopScrubbing);
      timelineBody.addEventListener("pointercancel", stopScrubbing);
    }});

    video?.addEventListener("play", startPlayheadLoop);
    video?.addEventListener("pause", stopPlayheadLoop);
    video?.addEventListener("ended", stopPlayheadLoop);
    video?.addEventListener("seeking", updatePlayhead);
    video?.addEventListener("seeked", updatePlayhead);
    video?.addEventListener("timeupdate", updatePlayhead);
    video?.addEventListener("loadedmetadata", updatePlayhead);
    window.addEventListener("resize", updatePlayhead);
    updatePlayhead();
  </script>
</body>
</html>
"""


def _serialize_state(state: PipelineState) -> dict[str, Any]:
    payload = {
        "video_path": state["video_path"],
        "model": state["model"],
        "temperature": state["temperature"],
        "seed": state["seed"],
        "use_audio": state["use_audio"],
        "input_mode": state["input_mode"],
        "use_scene_detect": state.get("use_scene_detect"),
        "video_duration": state.get("video_duration"),
        "scene_cuts": state.get("scene_cuts", []),
        "scene_cuts_prompt": state.get("scene_cuts_prompt"),
        "working_video_path": state.get("working_video_path"),
        "file_uri": state.get("file_uri"),
        "file_name": state.get("file_name"),
        "raw_json_payload": state.get("raw_json_payload"),
        "action_tracks": state.get("action_tracks", []),
        "background_tracks": state.get("background_tracks", []),
        "run_id": state["run_id"],
        "errors": state["errors"],
    }
    return payload


def _write_intermediate_artifacts(state: PipelineState, run_dir: Path) -> None:
    if not state.get("save_intermediate"):
        return
    artifacts = state.get("intermediate_artifacts", {})
    if not artifacts:
        return
    intermediate_dir = run_dir / "intermediate"
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    for filename, payload in artifacts.items():
        (intermediate_dir / filename).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _resolve_report_video_src(report_dir: Path, state: PipelineState) -> str:
    bundled_video_path = report_dir / "videos" / Path(state["video_path"]).name
    if bundled_video_path.exists():
        return bundled_video_path.relative_to(report_dir).as_posix()
    return Path(state["video_path"]).resolve().as_uri()


def write_report_html(state: PipelineState, report_html_path: Path) -> Path:
    """주어진 state로 HTML 보고서를 생성해 지정 경로에 저장한다."""
    video_src = _resolve_report_video_src(report_html_path.parent, state)
    report_html_path.write_text(
        build_report_html(state, video_src=video_src),
        encoding="utf-8",
    )
    return report_html_path


def load_saved_state(result_json_path: str | Path) -> PipelineState:
    """저장된 tracks.json을 읽어 보고서 재생성에 사용할 state로 복원한다."""
    payload = json.loads(Path(result_json_path).read_text(encoding="utf-8"))
    return cast(PipelineState, payload)


def rebuild_report_from_json(
    result_json_path: str | Path,
    report_html_path: str | Path | None = None,
) -> Path:
    """기존 tracks.json을 이용해 HTML 보고서만 다시 생성한다."""
    result_json_path = Path(result_json_path)
    state = load_saved_state(result_json_path)
    target_path = (
        Path(report_html_path)
        if report_html_path is not None
        else result_json_path.with_name("report.html")
    )
    return write_report_html(state, target_path)


def save_run_artifacts(state: PipelineState, output_root: str) -> tuple[Path, Path]:
    """실행 결과를 저장하는 함수: state를 JSON으로 저장하고, HTML 보고서 생성 및 저장"""
    
    # 실행 결과를 저장할 디렉토리 생성 (output_root/run_id/)
    run_dir = Path(output_root) / state["run_id"]
    run_dir.mkdir(parents=True, exist_ok=True)

    # 결과 JSON과 HTML 보고서의 경로
    result_json_path = run_dir / "tracks.json"
    report_html_path = run_dir / "report.html"
    bundled_video_dir = run_dir / "videos"
    bundled_video_dir.mkdir(parents=True, exist_ok=True)
    bundled_video_path = bundled_video_dir / Path(state["video_path"]).name
    shutil.copy2(state["video_path"], bundled_video_path)

    # state를 JSON으로 직렬화하여 경로에 작성
    result_json_path.write_text(
        json.dumps(_serialize_state(state), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_intermediate_artifacts(state, run_dir)
    # HTML 보고서 생성 및 저장
    write_report_html(state, report_html_path)

    return result_json_path, report_html_path
