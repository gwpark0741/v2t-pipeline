import argparse # argparse 모듈을 사용하여 명령 인자를 파싱
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from config import PipelineConfig
from pipeline.graph import build_graph
from pipeline.reporting import save_run_artifacts
from pipeline.state import PipelineState


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}


def parse_args():
    """커맨드라인 인자를 정의하고 파싱하는 함수"""
    parser = argparse.ArgumentParser(description="Run V2T single-call baseline pipeline") # 커맨드라인 인자를 정의하고 파싱하는 객체
    parser.add_argument("--video", required=True, help="Path to input video file or directory")
    parser.add_argument("--recursive", action="store_true", help="Recursively search videos inside the input directory",)
    parser.add_argument("--config", default="config.yaml", help="Path to config yaml")
    parser.add_argument("--model", default=None, help="Optional model override")
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Optional temperature override",
    )
    return parser.parse_args()


def make_batch_output_root(input_path: str, output_dir: str) -> Path:
    input_name = Path(input_path).resolve().name
    return Path(output_dir) / input_name


def make_run_id(video_path: str) -> str:
    """video name + 현재 날짜와 시간을 기반으로 고유한 실행 ID 생성"""
    video_name = Path(video_path).stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{timestamp}_{video_name}"


def collect_video_paths(input_path: str, recursive: bool = False) -> list[Path]:
    path = Path(input_path)

    if not path.exists():
        raise FileNotFoundError(f"Input path not found: {input_path}")
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise ValueError(f"Input path is neither file nor directory: {input_path}")
    
    if recursive:
        pattern_iter = path.rglob("*") 
    else:
        pattern_iter = path.glob("*")
    
    video_paths = sorted(
        p for p in pattern_iter
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    )

    if not video_paths:
        raise FileNotFoundError(f"No video files found in directory: {input_path}")
    
    return video_paths


def build_initial_state(
        video_path: str,
        args,
        config: PipelineConfig
) -> PipelineState:
    """초기 상태를 생성하는 함수"""
    model = args.model if args.model is not None else config.model
    temperature = (
        args.temperature if args.temperature is not None else config.temperature
    )

    return {
        "video_path": video_path,
        "model": model,
        "temperature": temperature,
        "seed": config.seed,
        "use_audio": config.options.use_audio,
        "input_mode": config.options.input_mode,
        "video_fps": config.options.video_fps,
        "use_sound_layering": config.options.use_sound_layering,
        "run_id": make_run_id(video_path),
        "errors": [],
    }


def main():
    """파이프라인 실행의 진입점 함수"""
    load_dotenv() # .env 파일에서 환경 변수 로드

    args = parse_args() # 커맨드라인 인자 파싱
    config = PipelineConfig.from_yaml(args.config) # yaml 파일에서 파이프라인 설정 로드

    graph = build_graph()

    video_paths = collect_video_paths(args.video, recursive=args.recursive)

    batch_output_root = make_batch_output_root(args.video, config.output_dir)
    batch_output_root.mkdir(parents=True, exist_ok=True)

    for video_path in video_paths:
        print(f"Processing: {video_path}")

        try:
            initial_state = build_initial_state(str(video_path), args, config)
            final_state = graph.invoke(initial_state)

            result_json_path, report_html_path = save_run_artifacts(
                final_state,
                str(batch_output_root),
            )

            print(f"Run completed: {final_state['run_id']}")
            print(f"Result JSON: {Path(result_json_path).resolve()}")
            print(f"HTML report: {Path(report_html_path).resolve()}")

        except Exception as exc:
            print(f"Failed: {video_path}")
            print(f"Error: {exc}")


if __name__ == "__main__":
    main()
