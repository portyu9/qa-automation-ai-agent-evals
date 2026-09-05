"""Provider-neutral contract for calibrated subordinate semantic judges."""

from __future__ import annotations

from typing import Protocol

from agent_evals.semantic.calibration import SemanticCalibrationReceipt
from agent_evals.semantic.models import (
    SemanticJudgeInput,
    SemanticJudgeProfile,
    SemanticJudgeResponse,
)


class SemanticJudge(Protocol):
    """One semantic evaluator whose authority is bound to an exact calibration."""

    @property
    def profile(self) -> SemanticJudgeProfile: ...

    @property
    def calibration_receipt(self) -> SemanticCalibrationReceipt: ...

    async def judge(self, judge_input: SemanticJudgeInput) -> SemanticJudgeResponse: ...


class SemanticJudgeConfigurationError(ValueError):
    """Configured semantic judge does not possess valid grading authority."""


def validate_semantic_judge_authority(
    judge: SemanticJudge,
) -> tuple[SemanticJudgeProfile, SemanticCalibrationReceipt]:
    """Revalidate exact profile/calibration material before any semantic invocation."""
    try:
        profile = SemanticJudgeProfile.model_validate(judge.profile.model_dump(mode="json"))
        calibration = SemanticCalibrationReceipt.model_validate(
            judge.calibration_receipt.model_dump(mode="json")
        )
    except (AttributeError, ValueError) as exc:
        raise SemanticJudgeConfigurationError(
            "semantic judge profile or calibration receipt is malformed"
        ) from exc

    if not calibration.accepted:
        raise SemanticJudgeConfigurationError(
            "semantic judge calibration has not satisfied its acceptance policy"
        )
    if calibration.judge_profile.identity != profile.identity:
        raise SemanticJudgeConfigurationError(
            "semantic judge profile does not match its accepted calibration"
        )
    return profile, calibration
