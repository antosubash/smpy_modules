"""Error codes of the AI steps, prompts, group runs and presets.

Each has a worded ``errors.*`` entry in both catalogues (``tests/test_error_labels.py``).
"""

from __future__ import annotations

from typing import Final

CODE_UNSAFE_SCHEMA: Final = "unsafe_output_schema"
CODE_PROMPT_NAME_TAKEN: Final = "prompt_name_taken"
CODE_INVALID_INPUTS: Final = "invalid_prompt_inputs"
CODE_INVALID_RUN_TARGET: Final = "invalid_run_target"
CODE_AI_UNAVAILABLE: Final = "ai_unavailable"
CODE_PROMPT_IN_USE: Final = "prompt_in_use"
CODE_PRESET_NOT_FOUND: Final = "preset_not_found"
CODE_REVIEW_STALE: Final = "review_stale"
CODE_INVALID_REVIEW: Final = "invalid_review_data"
CODE_INVALID_SCHEMA: Final = "invalid_schema"
GROUP_RUN_CODES: Final = (
    "group_empty",
    "group_too_large",
    "member_prompt_missing",
    "member_results_missing",
    "no_usable_inputs",
    "output_too_large",
)
"""What a group run can end with besides the AI codes (``sm_images.pipeline.ai.group_run``)."""
AI_CODES: Final = (
    CODE_UNSAFE_SCHEMA,
    CODE_PROMPT_NAME_TAKEN,
    CODE_INVALID_INPUTS,
    CODE_INVALID_RUN_TARGET,
    CODE_AI_UNAVAILABLE,
    CODE_PROMPT_IN_USE,
    CODE_PRESET_NOT_FOUND,
    CODE_REVIEW_STALE,
    CODE_INVALID_REVIEW,
    CODE_INVALID_SCHEMA,
    "display_not_ready",
    "ai_not_configured",
    "quota_exceeded",
    "ai_error",
    *GROUP_RUN_CODES,
)
"""What the prompt and preset routes answer and an AI step's or group's run can end with."""
