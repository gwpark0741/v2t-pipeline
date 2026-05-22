import argparse
from pathlib import Path

from v2t_single.pipeline.reporting import rebuild_report_from_json


def parse_args():
    parser = argparse.ArgumentParser(
        description="Rebuild an HTML report from a saved tracks.json file"
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to an existing tracks.json file",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path for report.html",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    report_path = rebuild_report_from_json(args.input, args.output)
    print(f"HTML report rebuilt: {Path(report_path).resolve()}")


if __name__ == "__main__":
    main()
