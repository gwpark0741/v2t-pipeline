from typing import Literal

from pipeline.state import PipelineState
from prompts import single, single_audio, single_layering


def select_prompt_profile(
        use_audio: bool,
        use_sound_layering: bool,
) -> Literal["single", "single_audio", "single_layering"]:
    """실행 옵션 값들을 받아, 사용할 prompt profile을 반환"""
    if use_sound_layering:
        return "single_layering"
    if use_audio:
        return "single_audio"
    else:
        return "single"


def load_prompt_templates(
        profile: Literal["single", "single_audio", "single_layering"]
) -> tuple[str, str]:
    """prompt profile에 따라 적합한 파일에서 prompt template를 가져옴"""
    if profile == "single":
        return single.SYSTEM_PROMPT, single.USER_PROMPT
    
    if profile == "single_audio":
        return single_audio.SYSTEM_PROMPT, single_audio.USER_PROMPT
    
    if profile == "single_layering":
        return single_layering.SYSTEM_PROMPT, single_layering.USER_PROMPT
    
    else:
        raise ValueError(f"Unsupported prompt profile: {profile}")


def render_user_prompt(user_prompt_template: str, duration: float) -> str:
    """video 전처리에서 추출한 duration을 활용하여 user prompt를 생성하는 함수"""
    return user_prompt_template.replace("__DURATION__", str(duration))


def run_build_prompt(state: PipelineState) -> dict:
    """state에서 use_audio, video_duration을 읽어, system/user prompt 생성"""
    profile = select_prompt_profile(state["use_audio"], state["use_sound_layering"])
    system_prompt, user_prompt_template = load_prompt_templates(profile)
    user_prompt = render_user_prompt(user_prompt_template, state["video_duration"])

    return {
        "prompt_profile": profile,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }