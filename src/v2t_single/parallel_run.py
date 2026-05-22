import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv

from v2t_single.config import PipelineConfig
from v2t_single.pipeline.graph import build_graph
from v2t_single.pipeline.reporting import save_run_artifacts
from v2t_single.run import build_initial_state, collect_video_paths, make_batch_output_root


_print_lock = Lock()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run V2T pipeline over videos with bounded parallelism"
    )
    parser.add_argument("--video", required=True, help="Path to input video file or directory")
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Recursively search videos inside the input directory",
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config yaml")
    parser.add_argument("--model", default=None, help="Optional model override")
    parser.add_argument("--max-videos", type=int, default=None, help="Limit videos for testing")
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="Optional temperature override",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="Number of videos to process in parallel, e.g. 2 or 3",
    )
    return parser.parse_args()


def log(message: str) -> None:
    with _print_lock:
        print(message, flush=True)


def run_one_video(
    index: int,
    total: int,
    video_path: Path,
    args: argparse.Namespace,
    config: PipelineConfig,
    batch_output_root: Path,
) -> tuple[Path, bool, str]:
    log(f"[{index}/{total}] START: {video_path}")

    try:
        graph = build_graph()
        initial_state = build_initial_state(str(video_path), args, config)
        final_state = graph.invoke(initial_state)

        result_json_path, report_html_path = save_run_artifacts(
            final_state,
            str(batch_output_root),
        )

        message = (
            f"[{index}/{total}] DONE: {video_path}\n"
            f"  Run ID: {final_state['run_id']}\n"
            f"  Result JSON: {Path(result_json_path).resolve()}\n"
            f"  HTML report: {Path(report_html_path).resolve()}"
        )
        log(message)
        return video_path, True, message

    except Exception as exc:
        message = f"[{index}/{total}] FAILED: {video_path}\n  Error: {exc}"
        log(message)
        return video_path, False, message


def main() -> None:
    load_dotenv()

    args = parse_args()
    if args.max_videos is not None and args.max_videos <= 0:
        raise ValueError("--max-videos must be a positive integer")
    if args.workers <= 0:
        raise ValueError("--workers must be a positive integer")

    config = PipelineConfig.from_yaml(args.config)

    video_paths = collect_video_paths(args.video, recursive=args.recursive)
    if args.max_videos is not None:
        video_paths = video_paths[: args.max_videos]

    batch_output_root = make_batch_output_root(args.video, config.output_dir)
    batch_output_root.mkdir(parents=True, exist_ok=True)

    total = len(video_paths)
    workers = min(args.workers, total)
    log(f"Processing {total} video(s) with {workers} worker(s)")
    log(f"Output root: {batch_output_root.resolve()}")

    successes = 0
    failures = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                run_one_video,
                index,
                total,
                video_path,
                args,
                config,
                batch_output_root,
            )
            for index, video_path in enumerate(video_paths, start=1)
        ]

        for future in as_completed(futures):
            _, ok, _ = future.result()
            if ok:
                successes += 1
            else:
                failures += 1

    log(f"Finished: {successes} succeeded, {failures} failed")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
