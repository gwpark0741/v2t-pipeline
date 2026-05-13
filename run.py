import argparse # argparse 모듈을 사용하여 명령 인자를 파싱
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from config import PipelineConfig
from pipeline.graph import build_graph
from pipeline.reporting import save_run_artifacts
from pipeline.state import PipelineState

def parse_args():
    """커맨드라인 인자를 정의하고 파싱하는 함수"""
    parser = argparse.ArgumentParser(description="Run V2T single-call baseline pipeline") # 커맨드라인 인자를 정의하고 파싱하는 객체
    parser.add_argument("--video", required=True, help="Path to input video file")
    parser.add_argument("--config", default="config.yaml", help="Path to config yaml")
    parser.add_argument("--model", default=None, help="Optional model override")
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Optional temperature override",
    )
    return parser.parse_args()


def make_run_id() -> str:
    """현재 날짜와 시간을 기반으로 고유한 실행 ID 생성"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def build_initial_state(args, config: PipelineConfig) -> PipelineState:
    """초기 상태를 생성하는 함수"""
    model = args.model if args.model is not None else config.model
    temperature = (
        args.temperature if args.temperature is not None else config.temperature
    )

    return {
        "video_path": args.video,
        "model": model,
        "temperature": temperature,
        "seed": config.seed,
        "use_audio": config.options.use_audio,
        "input_mode": config.options.input_mode,
        "run_id": make_run_id(),
        "errors": [],
    }


def main():
    """파이프라인 실행의 진입점 함수"""
    load_dotenv() # .env 파일에서 환경 변수 로드

    args = parse_args() # 커맨드라인 인자 파싱
    config = PipelineConfig.from_yaml(args.config) # yaml 파일에서 파이프라인 설정 로드

    graph = build_graph()

    initial_state = build_initial_state(args, config) # 초기 상태 생성
    final_state = graph.invoke(initial_state) # 그래프 실행, 초기 상태를 입력으로 받아 최종 상태 반환

    # 실행 결과를 저장 및 결과 JSON과 HTML 보고서 생성, 저장 경로 반환
    result_json_path, report_html_path = save_run_artifacts(
        final_state,
        config.output_dir,
    )

    print(f"Run completed: {final_state['run_id']}")
    print(f"Result JSON: {Path(result_json_path).resolve()}")
    print(f"HTML report: {Path(report_html_path).resolve()}")


if __name__ == "__main__":
    main()
