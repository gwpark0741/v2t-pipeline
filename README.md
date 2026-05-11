V2T_SINGLE/
├── pipeline/
│   ├── nodes/
│   │   ├── preprocess.py    ← tools 호출만 (얇아짐)
│   │   └── single_call.py   ← tools 호출만 (얇아짐)
│   ├── state.py
│   └── graph.py
├── prompts/
│   └── single.py
├── tools/
│   ├── video_utils.py       ← ffmpeg/ffprobe 래퍼
│   └── gemini_client.py     ← File API 업로드, 모델 호출
├── results/
├── videos/
├── config.py
├── config.yaml
└── run.py