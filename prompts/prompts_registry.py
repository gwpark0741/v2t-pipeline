from typing import Literal

from prompts import (
    single,
    single_audio,
    single_layering,
    single_layering_model_routing,
)

PromptProfile = Literal[
    "single",
    "single_audio",
    "single_layering",
    "single_layering_model_routing",
]


PROMPT_REGISTRY: dict[PromptProfile, tuple[str, str]] = {
    "single": (single.SYSTEM_PROMPT, single.USER_PROMPT),
    "single_audio": (single_audio.SYSTEM_PROMPT, single_audio.USER_PROMPT),
    "single_layering": (single_layering.SYSTEM_PROMPT, single_layering.USER_PROMPT),
    "single_layering_model_routing": (
        single_layering_model_routing.SYSTEM_PROMPT,
        single_layering_model_routing.USER_PROMPT,
    ),
}