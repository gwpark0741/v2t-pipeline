from dataclasses import dataclass, field
from typing import Literal
import yaml

from v2t_single.prompts.prompts_registry import PromptProfile

@dataclass
class PipelineOptions:
    use_audio: bool = False                                   # 오디오 트랙 포함 여부
    use_scene_detect: bool = True                             # PySceneDetect 기반 컷 자동 감지
    use_hitl: bool = False                                    # Human in the Loop (Phase 2)
    save_intermediate: bool = True                            # 중간 결과 저장
    input_mode: Literal["file_api", "frames"] = "file_api"    # 영상 입력 방식
    video_fps: float | None = None
    use_sound_layering: bool = True                          # legacy
    prompt_profile: PromptProfile = "single_layering_model_routing" # 사용할 프롬프트


@dataclass
class PipelineConfig:
    model: str                                               # 사용 모델
    mode: Literal["single", "multi"] = "single"              # 호출 방식 (single: VLM 단일 호출, multi: VLM 단계별 호출)
    temperature: float = 0.0
    seed: int = 42
    options: PipelineOptions = field(default_factory=PipelineOptions)
    output_dir: str = "results"

    @classmethod
    def from_yaml(cls, path: str) -> "PipelineConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        options = PipelineOptions(**data.pop("options", {}))
        return cls(**data, options=options)