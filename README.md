# v2t-single

비디오를 Gemini로 분석해 사운드 트랙 구조를 추출하고, 결과를 JSON과 HTML 보고서로 저장하는 파이프라인입니다.

현재 구현은 전체 비디오를 한 번에 분석하는 single-call baseline입니다. 단일 실행 모드와 Gemini Batch API 기반 대량 처리 모드를 함께 지원합니다.

## 주요 기능

- 단일 비디오, 디렉토리, 재귀 디렉토리 입력 지원
- Gemini File API 기반 비디오 업로드
- `video_fps`를 포함한 Gemini video metadata 전달
- prompt profile 기반 프롬프트 선택
- structured output schema 검증
- action/background track 및 sound layer 추출
- T2A/V2A generation model routing 정보 생성
- JSON 결과와 HTML 보고서 저장
- Gemini Batch API prepare/submit/collect workflow 지원
- LangSmith trace에 Gemini token usage 기록
- HunyuanVideo-Foley 및 ElevenLabs API를 사용한 V2A 생성 파이프라인

## 처리 흐름

### Single Run

```mermaid
flowchart TD
    A[v2t-run] --> B[config.yaml 로드]
    B --> C[비디오 파일 수집]
    C --> D[preprocessing]
    D --> E[build_prompt]
    E --> F[track_extraction]
    F --> G[tracks.json]
    F --> H[report.html]
```

### Batch Run

```mermaid
flowchart TD
    A[v2t-batch-prepare] --> B[비디오 전처리 및 File API 업로드]
    B --> C[manifest.jsonl 생성]
    C --> D[request chunk JSONL 생성]
    D --> E[v2t-batch-submit]
    E --> F[Gemini Batch Job 생성]
    F --> G[v2t-batch-collect]
    G --> H[Batch output 다운로드]
    H --> I[tracks.json/report.html 저장]
```

## 프로젝트 구조

```text
.
├── src/
│   └── v2t_single/
│       ├── clients/
│       ├── pipeline/
│       ├── prompts/
│       ├── tools/
│       ├── batch_collect.py
│       ├── batch_prepare.py
│       ├── batch_submit.py
│       ├── config.py
│       ├── rebuild_report.py
│       ├── run.py
│       └── scene_detect_report.py
├── docs/
│   └── project-structure.md
├── config.yaml
├── langgraph.json
├── pyproject.toml
└── README.md
```

## 설치

`uv`가 없다면 먼저 설치합니다.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
```

프로젝트 루트에서 의존성을 설치합니다.

```bash
uv sync
```

## 환경 변수

`.env.example`을 참고해 `.env`를 준비합니다.

```bash
GEMINI_API_KEY=your_gemini_key
LANGFUSE_SECRET_KEY="sk-lf-..."
LANGFUSE_PUBLIC_KEY="pk-lf-..."
LANGFUSE_BASE_URL="https://..."
ELEVENLABS_API_KEY=your_elevenlabs_key
OPENAI_API_KEY=your_openai_key
HUNYUAN_V2A_API_URL=http://localhost:8080
```

Langfuse 연동을 원치 않으시면 `LANGFUSE_SECRET_KEY` 등을 빈 값으로 두거나 주석 처리합니다.

## 설정

기본 설정은 `config.yaml`에서 관리합니다.

```yaml
mode: "single"
model: "gemini-2.5-pro"
output_dir: "results"
temperature: 0.0
seed: 42

options:
  use_audio: false
  use_scene_detect: true
  use_hitl: false
  save_intermediate: true
  input_mode: "file_api"
  video_fps: 5
  use_sound_layering: true
  prompt_profile: "single_layering_model_routing"
```

지원 prompt profile:

- `single`
- `single_audio`
- `single_layering`
- `single_layering_model_routing`

현재 baseline에서는 `input_mode: "file_api"`만 지원합니다.

## Single 실행

단일 비디오 실행:

```bash
uv run v2t-run --video videos/your_video.mp4
```

디렉토리 내 여러 영상 실행:

```bash
uv run v2t-run --video videos/
```

하위 디렉토리까지 재귀적으로 실행:

```bash
uv run v2t-run --video videos/ --recursive
```

모델 또는 temperature를 실행 시 덮어쓰기:

```bash
uv run v2t-run \
  --video videos/your_video.mp4 \
  --model gemini-2.5-pro \
  --temperature 0.0
```

다른 config 파일 사용:

```bash
uv run v2t-run --video videos/your_video.mp4 --config config.yaml
```

## PySceneDetect 리포트

Gemini 호출 없이 PySceneDetect만 실행하고, 컷별 클립과 HTML 보고서를 생성합니다.

```bash
uv run v2t-scene-detect-report \
  --video samples/vggsound_test/5PYzLVpPSXA_000070.mp4
```

과분할이 보이면 더 보수적인 preset을 사용합니다.

```bash
uv run v2t-scene-detect-report \
  --video samples/vggsound_test/5PYzLVpPSXA_000070.mp4 \
  --preset conservative
```

Preset은 `high_recall`(threshold 27, min_scene_len 1), `balanced`(35, 6), `conservative`(45, 12)를 지원하며, `--threshold`, `--min-scene-len`으로 직접 덮어쓸 수 있습니다.

디렉토리 입력도 지원합니다.

```bash
uv run v2t-scene-detect-report \
  --video samples/vggsound_test \
  --max-videos 5
```

출력은 `results/scene_detect/<run_id>/<video>/report.html`, `scene_cuts.json`, `clips/cut_*.mp4`로 저장됩니다.

## Batch 실행

Batch 처리는 3단계로 나뉩니다.

### 1. 요청 준비

비디오 전처리, Gemini File API 업로드, manifest 및 request chunk를 생성합니다.

```bash
uv run v2t-batch-prepare \
  --video videos/ \
  --batch-name my_batch \
  --chunk-size 200
```

재귀 탐색:

```bash
uv run v2t-batch-prepare \
  --video videos/ \
  --batch-name my_batch \
  --recursive
```

테스트용 일부만 준비:

```bash
uv run v2t-batch-prepare \
  --video videos/ \
  --batch-name my_batch \
  --max-videos 10
```

기존 manifest를 재사용:

```bash
uv run v2t-batch-prepare \
  --video videos/ \
  --batch-name my_batch \
  --resume
```

### 2. Batch job 제출

생성된 request chunk를 Gemini Batch API에 제출합니다.

```bash
uv run v2t-batch-submit --batch-dir results/my_batch/batch
```

특정 chunk만 제출:

```bash
uv run v2t-batch-submit \
  --batch-dir results/my_batch/batch \
  --chunk chunk_0001
```

이미 job 파일이 있어도 다시 제출:

```bash
uv run v2t-batch-submit \
  --batch-dir results/my_batch/batch \
  --chunk chunk_0001 \
  --force-resubmit
```

### 3. Batch 결과 수집

완료된 job의 output을 내려받고, 각 비디오별 `tracks.json`과 `report.html`을 생성합니다.

```bash
uv run v2t-batch-collect --batch-dir results/my_batch/batch
```

job이 끝날 때까지 polling:

```bash
uv run v2t-batch-collect \
  --batch-dir results/my_batch/batch \
  --poll \
  --poll-interval 60
```

특정 chunk만 수집:

```bash
uv run v2t-batch-collect \
  --batch-dir results/my_batch/batch \
  --chunk chunk_0001
```

### 실패 항목 재시도

`v2t-batch-collect`가 만든 `failed.jsonl`을 이용해 retry request chunk를 만들 수 있습니다.

```bash
uv run v2t-batch-prepare \
  --batch-name my_batch \
  --resume \
  --retry-failed results/my_batch/batch/failed.jsonl
```

생성된 `retry_*.jsonl`도 `v2t-batch-submit`, `v2t-batch-collect`의 `--chunk` 옵션으로 동일하게 처리합니다.

## 출력 결과

Single 실행에서 파일 하나를 입력하면 `results/<input-file-name>/<run_id>/` 아래에 결과가 저장됩니다.

```text
results/your_video.mp4/
└── 20260518_162830_your_video/
    ├── report.html
    ├── tracks.json
    └── videos/
        └── your_video.mp4
```

디렉토리 입력은 입력 디렉토리 이름을 상위 폴더로 사용합니다.

```text
results/videos/
├── 20260518_162830_01/
│   ├── report.html
│   ├── tracks.json
│   └── videos/
│       └── 01.mp4
└── 20260518_162905_02/
    ├── report.html
    ├── tracks.json
    └── videos/
        └── 02.mp4
```

Batch 실행은 `results/<batch-name>/batch/` 아래에 batch 관리 파일을 저장하고, 각 비디오별 결과는 `results/<batch-name>/<run_id>/` 아래에 저장합니다.

```text
results/my_batch/
├── batch/
│   ├── manifest.jsonl
│   ├── requests/
│   │   └── chunk_0001.jsonl
│   ├── jobs/
│   │   ├── chunk_0001.job.json
│   │   └── index.jsonl
│   ├── outputs/
│   │   └── chunk_0001.results.jsonl
│   └── failed.jsonl
└── video_000001_your_video/
    ├── report.html
    ├── tracks.json
    └── videos/
        └── your_video.mp4
```

`tracks.json`에는 실행 메타데이터, 비디오 정보, Gemini raw JSON payload, 검증된 action/background tracks가 저장됩니다.

`report.html`에서는 비디오, 트랙 목록, sound layer, routing badge, segment timeline, 재생 위치와 동기화되는 playhead를 확인할 수 있습니다.

## 보고서 재생성

이미 생성된 `tracks.json`이 있으면 Gemini를 다시 호출하지 않고 HTML 보고서만 재생성할 수 있습니다.

```bash
uv run v2t-rebuild-report --input results/<path-to-run>/tracks.json
```

출력 경로 지정:

```bash
uv run v2t-rebuild-report \
  --input results/<path-to-run>/tracks.json \
  --output results/<path-to-run>/report.html
```

## Langfuse Tracing

`src/v2t_single/clients/gemini_client.py`의 single Gemini 호출은 Langfuse `@observe` 데코레이터로 감싸져 있습니다. Gemini 응답의 `usage_metadata`를 Langfuse usage schema로 변환해 trace에 기록합니다.

추가로 `audio_client.py`의 각 TTS, SFX, V2A 호출 역시 Langfuse를 통해 LLM Generation 및 Span으로 기록되어 전체 파이프라인의 실행 시간과 비용을 추적할 수 있습니다.

Langfuse 웹 UI에서 cost가 보이려면 pricing map에 해당 provider/model 조합이 매칭되어야 합니다. 매칭되지 않으면 token usage는 남지만 cost가 비어 있을 수 있습니다.

현재 batch collect 경로는 Gemini Batch API 결과를 로컬 산출물로 변환하며, single 호출처럼 LLM run을 직접 생성하지는 않습니다.

## 개발 메모

- `.env`, `videos/`, `results/`, `samples/`는 git에 포함하지 않습니다.
- `use_scene_detect`가 켜져 있으면 PySceneDetect로 모델 입력 전에 cut id/start/end를 추출해 Gemini user prompt와 결과 JSON에 기록합니다.
- `use_hitl`, `input_mode: "frames"`는 설정 필드는 있지만 현재 baseline 구현 범위 밖입니다.
- `use_sound_layering`은 legacy 옵션이며, 실제 프롬프트 선택은 `prompt_profile`을 우선 사용합니다.

## V2A (HunyuanVideo-Foley) 원격 서버 설정

비디오 클립 기반 효과음 생성을 위해 **HunyuanVideo-Foley** 모델을 사용합니다. 모델 크기(약 20GB)와 요구 사양(CUDA) 때문에 로컬 실행 대신 **Vast.ai**와 같은 원격 GPU 서버에 컨테이너를 띄우고, SSH 터널링을 통해 API 요청을 전달하는 방식을 권장합니다.

### 1. 원격 인스턴스 셋업
1. GPU (VRAM 24GB 이상 권장) 및 최소 **50GB 이상의 여유 디스크 공간**을 가진 인스턴스를 대여합니다.
2. Base Image: `pytorch/pytorch:2.4.0-cuda11.8-cudnn9-devel` (또는 12.x 호환 이미지).
3. 로컬의 `setup_remote.sh` 스크립트를 서버에 복사하고 실행하여 환경을 구축합니다:
   ```bash
   scp -P <port> setup_remote.sh root@<ip>:/root/
   ssh -p <port> root@<ip> "bash setup_remote.sh"
   ```

### 2. API 서버 실행 및 로컬 포트 포워딩
원격 서버에 포함된 `hunyuan_api_server.py`를 실행하고, 로컬 포트(8080)와 연결합니다.

1. 원격 서버에서 API 구동:
   ```bash
   # 서버 터미널에서 실행 (tmux 환경 권장)
   cd /root/HunyuanVideo-Foley
   export HUNYUAN_MODEL_PATH=/root/HunyuanVideo-Foley/weights
   python3 hunyuan_api_server.py
   ```
2. 로컬 윈도우에서 SSH 터널링 연결 (창을 끄지 않고 유지):
   ```bash
   ssh -p <port> root@<ip> -L 8080:localhost:8080
   ```
3. 로컬 프로젝트의 `.env` 파일에 API URL을 설정:
   ```bash
   HUNYUAN_V2A_API_URL=http://localhost:8080
   ```
이후 `v2t-synthesize` 명령어를 실행하면 해당 터널링 포트를 통해 V2A 모델이 오디오를 생성합니다.
