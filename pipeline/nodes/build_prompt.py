from pipeline.state import PipelineState
from prompts.prompts_registry import PromptProfile, PROMPT_REGISTRY


def select_prompt_profile(
        use_audio: bool,
        use_sound_layering: bool,
        prompt_profile: PromptProfile | None
) -> PromptProfile:
    """실행 옵션 값들을 받아, 사용할 prompt profile을 반환"""
    if prompt_profile is not None:
        return prompt_profile
    if use_sound_layering:
        return "single_layering"
    if use_audio:
        return "single_audio"
    return "single"


def load_prompt_templates(
    profile: PromptProfile
) -> tuple[str, str]:
    """prompt profile에 따라 적합한 파일에서 prompt template를 가져옴"""
    return PROMPT_REGISTRY[profile]


def render_user_prompt(user_prompt_template: str, duration: float) -> str:
    """video 전처리에서 추출한 duration을 활용하여 user prompt를 생성하는 함수"""
    return user_prompt_template.replace("__DURATION__", str(duration))


def run_build_prompt(state: PipelineState) -> dict:
    """state에서 prompt_profile, video_duration을 읽어, system/user prompt 생성"""

    profile = select_prompt_profile(
        use_audio=state["use_audio"],
        use_sound_layering=state["use_sound_layering"],
        prompt_profile=state["prompt_profile"],
    )
    
    system_prompt, user_prompt_template = load_prompt_templates(profile)
    user_prompt = render_user_prompt(user_prompt_template, state["video_duration"])

    return {
        "prompt_profile": profile,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }