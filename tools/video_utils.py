import json
import os
import subprocess
import tempfile


def get_duration(video_path: str) -> float:
    """ffprobe로 영상 길이(초) 추출 -> LLM 응답 timestamp 검증에 활용"""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path],
        capture_output=True, text=True, check=True
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def strip_audio(video_path: str) -> str:
    """오디오 트랙 제거한 임시 파일 경로 반환 -> use_audio=false 모드 지원"""
    fd, tmp_path = tempfile.mkstemp(suffix=".mp4")
    try:
        os.close(fd)
        subprocess.run(
            ["ffmpeg", "-i", video_path, "-an", "-c:v", "copy", tmp_path, "-y"],
            check=True, capture_output=True
        )
        return tmp_path
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise e