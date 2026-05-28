import json
import os
import subprocess
import tempfile
from typing import Any


def get_duration(video_path: str) -> float:
    """cv2로 영상 길이(초) 추출 -> LLM 응답 timestamp 검증에 활용"""
    import cv2
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    if fps <= 0:
        return 0.0
    return float(frame_count / fps)


def detect_scene_cuts(
    video_path: str,
    duration: float,
    threshold: float = 35.0,
    min_scene_len: int = 6,
) -> list[dict[str, Any]]:
    """PySceneDetect로 editorial cut 단위의 start/end 목록을 반환한다."""
    try:
        from scenedetect import ContentDetector, SceneManager, open_video
    except ImportError as exc:
        raise ImportError(
            "PySceneDetect is required when use_scene_detect=true. "
            "Install dependencies with `uv sync` or `pip install scenedetect opencv-python`."
        ) from exc

    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(
        ContentDetector(
            threshold=threshold,
            min_scene_len=min_scene_len,
        )
    )
    scene_manager.detect_scenes(video)

    scenes = scene_manager.get_scene_list()
    if not scenes:
        scenes = []

    cuts: list[dict[str, Any]] = []
    for index, (start_time, end_time) in enumerate(scenes, start=1):
        start = max(0.0, start_time.get_seconds())
        end = min(duration, end_time.get_seconds())
        if end <= start:
            continue
        cuts.append({
            "cut_id": f"cut_{index:04d}",
            "start": round(start, 3),
            "end": round(end, 3),
        })

    if cuts:
        cuts[-1]["end"] = round(duration, 3)
        return cuts

    return [{"cut_id": "cut_0001", "start": 0.0, "end": round(duration, 3)}]


def format_scene_cuts_for_prompt(cuts: list[dict[str, Any]]) -> str:
    """Gemini에게 전달할 외부 cut 정보를 간결한 텍스트 블록으로 포맷한다."""
    if not cuts:
        return "No external cut boundaries detected."

    lines = []
    for cut in cuts:
        lines.append(
            f"- {cut['cut_id']}: start={cut['start']:.3f}s, end={cut['end']:.3f}s"
        )
    return "\n".join(lines)


def strip_audio(video_path: str) -> str:
    """오디오 트랙 제거한 임시 파일 경로 반환 -> use_audio=false 모드 지원"""
    fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
    try:
        import imageio_ffmpeg
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        os.close(fd)
        subprocess.run(
            [ffmpeg_exe, "-i", video_path, "-an", "-c:v", "copy", tmp_path, "-y"],
            check=True, capture_output=True
        )
        return tmp_path
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise e