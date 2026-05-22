# Project Structure

이 프로젝트는 표준 `src` layout을 사용합니다.

```text
.
├── src/v2t_single/        # Python package source
│   ├── clients/           # Gemini API clients
│   ├── pipeline/          # LangGraph graph, state, schema, reporting
│   ├── prompts/           # Prompt profiles and registry
│   ├── tools/             # Shared utility helpers
│   ├── run.py             # Single-run CLI entrypoint implementation
│   ├── parallel_run.py    # Parallel single-run CLI implementation
│   ├── batch_prepare.py   # Batch request preparation CLI implementation
│   ├── batch_submit.py    # Batch job submission CLI implementation
│   ├── batch_collect.py   # Batch output collection CLI implementation
│   ├── rebuild_report.py  # Report rebuild CLI implementation
│   └── scene_detect_report.py
├── docs/                  # Project documentation
├── config.yaml            # Default runtime configuration
├── langgraph.json         # LangGraph server configuration
├── pyproject.toml         # Package metadata, dependencies, CLI scripts
├── samples/               # Local sample inputs, ignored by git
├── videos/                # Local video inputs, ignored by git
└── results/               # Generated outputs, ignored by git
```

CLI commands are exposed through `pyproject.toml`, so prefer:

```bash
uv run v2t-run --video videos/your_video.mp4
uv run v2t-batch-prepare --video videos/ --batch-name my_batch
```

For module-style execution, the same code can also be run with:

```bash
uv run python -m v2t_single.run --video videos/your_video.mp4
```
