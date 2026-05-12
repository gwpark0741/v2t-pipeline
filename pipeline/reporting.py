import json
from html import escape
from pathlib import Path
from typing import Any, cast

from pipeline.state import ActionTrack, BackgroundTrack, PipelineState


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

    return f"""
    <div class="track-row">
      <div class="track-meta">
        <div class="track-id track-id-{track_kind}">{escape(track_id)}</div>
        <div class="track-label">{escape(label)}</div>
        <div class="track-kind">{escape(track_kind)}</div>
        <div class="track-description">{escape(description)}</div>
      </div>
      <div class="track-lane">
        {''.join(blocks)}
      </div>
    </div>
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


def build_report_html(state: PipelineState) -> str:
    """HTML 보고서를 생성하는 함수: state를 입력으로 받아, 필요한 필드를 추출하여 HTML 보고서 생성 -> HTML 문자열 반환"""
    video_path = state["video_path"]
    duration = state["video_duration"]
    run_id = state["run_id"]
    action_tracks: list[ActionTrack] = state.get("action_tracks", [])
    background_tracks: list[BackgroundTrack] = state.get("background_tracks", [])

    rows: list[str] = []
    for track in action_tracks:
        rows.append(
            _build_track_row(
                track_kind="action",
                track_id=track["track_id"],
                label=track["event_type"],
                description=track["description"],
                segments=track["segments"],
                duration=duration,
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
            )
        )

    timeline_ticks = _build_timeline_ticks(duration)
    video_src = escape(Path(video_path).resolve().as_uri())

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
    }}

    .playhead {{
      position: absolute;
      top: 0;
      bottom: 0;
      left: 260px;
      width: 2px;
      background: var(--playhead);
      pointer-events: none;
      z-index: 5;
      box-shadow: 0 0 0 1px rgba(193, 18, 31, 0.18);
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

    .track-kind {{
      display: inline-block;
      margin-top: 6px;
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
      .empty {{
        margin-left: 0;
        left: 0;
      }}

      .track-row {{
        grid-template-columns: 1fr;
        gap: 10px;
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
        <video id="report-video" controls preload="metadata" src="{video_src}"></video>
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
      </div>
    </section>

    <section class="timeline-panel">
      <div class="panel-header">
        <h2 class="title">Track Timeline</h2>
        <p class="subtitle">The red playhead follows the current playback time of the video.</p>
      </div>
      <div class="timeline-wrap">
        <div class="timeline-scale">{timeline_ticks}</div>
        <div class="timeline-body">
          <div id="playhead" class="playhead"></div>
          {''.join(rows) if rows else '<div class="empty">No tracks were generated for this run.</div>'}
        </div>
      </div>
    </section>
  </div>

  <script>
    const video = document.getElementById("report-video");
    const playhead = document.getElementById("playhead");
    const fallbackDuration = {duration};

    function updatePlayhead() {{
      if (!video || !playhead) return;

      const effectiveDuration =
        Number.isFinite(video.duration) && video.duration > 0
          ? video.duration
          : fallbackDuration;

      if (!effectiveDuration) return;

      const progress = Math.max(0, Math.min(1, video.currentTime / effectiveDuration));

      if (window.innerWidth <= 1100) {{
        playhead.style.left = `${{progress * 100}}%`;
        return;
      }}

      const laneOffset = 260;
      const laneWidth = playhead.parentElement.clientWidth - laneOffset;
      playhead.style.left = `${{laneOffset + (laneWidth * progress)}}px`;
    }}

    video?.addEventListener("timeupdate", updatePlayhead);
    video?.addEventListener("loadedmetadata", updatePlayhead);
    window.addEventListener("resize", updatePlayhead);
    updatePlayhead();
  </script>
</body>
</html>
"""


def _serialize_state(state: PipelineState) -> dict[str, Any]:
    return {
        "video_path": state["video_path"],
        "model": state["model"],
        "temperature": state["temperature"],
        "seed": state["seed"],
        "use_audio": state["use_audio"],
        "input_mode": state["input_mode"],
        "video_duration": state.get("video_duration"),
        "working_video_path": state.get("working_video_path"),
        "file_uri": state.get("file_uri"),
        "file_name": state.get("file_name"),
        "raw_llm_response": state.get("raw_llm_response"),
        "action_tracks": state.get("action_tracks", []),
        "background_tracks": state.get("background_tracks", []),
        "run_id": state["run_id"],
        "errors": state["errors"],
    }


def write_report_html(state: PipelineState, report_html_path: Path) -> Path:
    """주어진 state로 HTML 보고서를 생성해 지정 경로에 저장한다."""
    report_html_path.write_text(build_report_html(state), encoding="utf-8")
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

    # state를 JSON으로 직렬화하여 경로에 작성
    result_json_path.write_text(
        json.dumps(_serialize_state(state), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    # HTML 보고서 생성 및 저장
    write_report_html(state, report_html_path)

    return result_json_path, report_html_path
