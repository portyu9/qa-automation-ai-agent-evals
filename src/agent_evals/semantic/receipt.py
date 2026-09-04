"""Integrity-bound semantic judgment evidence subordinate to deterministic grading."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.semantic.calibration import SemanticCalibrationReceipt
from agent_evals.semantic.models import (
    SemanticCriterionResult,
    SemanticDecision,
    SemanticJudgeInput,
    SemanticJudgeProfile,
    SemanticJudgeResponse,
    SemanticRubricSpec,
    derive_semantic_decision,
)

_RECEIPT_SCHEMA: Literal["agent-evals/semantic-judgment-receipt/v1"] = (
    "agent-evals/semantic-judgment-receipt/v1"
)
_RECEIPT_DOMAIN = b"agent-evals/semantic-judgment-receipt/v1\0"


class SemanticJudgmentReceipt(BaseModel):
    """Bind one calibrated semantic result to one exact pre-judgment trial envelope.

    The receipt intentionally binds the *pre-semantic* subject evidence root. The final trial
    evidence root can then include the semantic event without creating a circular dependency.
    Raw candidate output is not duplicated into this receipt.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/semantic-judgment-receipt/v1"] = _RECEIPT_SCHEMA
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    subject_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    subject_evidence_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    rubric_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_profile: SemanticJudgeProfile
    calibration_receipt: SemanticCalibrationReceipt
    judge_input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    judge_response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    criteria: tuple[SemanticCriterionResult, ...] = Field(min_length=1, max_length=32)
    decision: SemanticDecision
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        scenario_identity: str,
        subject_identity: str,
        subject_evidence_root: str,
        rubric: SemanticRubricSpec,
        judge_profile: SemanticJudgeProfile,
        calibration_receipt: SemanticCalibrationReceipt,
        judge_input: SemanticJudgeInput,
        response: SemanticJudgeResponse,
    ) -> Self:
        """Create judgment evidence only for an accepted, exact-profile calibration."""
        validated_calibration = _revalidate_calibration(calibration_receipt)
        _require_accepted_matching_calibration(
            validated_calibration,
            judge_profile=judge_profile,
        )
        if judge_input.rubric.identity != rubric.identity:
            raise ValueError("semantic judge input rubric does not match the scenario rubric")
        decision = derive_semantic_decision(rubric, response)
        unsigned = {
            "schema_version": _RECEIPT_SCHEMA,
            "scenario_identity": scenario_identity,
            "subject_identity": subject_identity,
            "subject_evidence_root": subject_evidence_root,
            "rubric_identity": rubric.identity,
            "judge_profile": judge_profile.model_dump(mode="json"),
            "calibration_receipt": validated_calibration.model_dump(mode="json"),
            "judge_input_sha256": judge_input.digest,
            "judge_response_sha256": response.digest,
            "criteria": [criterion.model_dump(mode="json") for criterion in response.criteria],
            "decision": decision.value,
        }
        return cls(
            scenario_identity=scenario_identity,
            subject_identity=subject_identity,
            subject_evidence_root=subject_evidence_root,
            rubric_identity=rubric.identity,
            judge_profile=judge_profile,
            calibration_receipt=validated_calibration,
            judge_input_sha256=judge_input.digest,
            judge_response_sha256=response.digest,
            criteria=response.criteria,
            decision=decision,
            receipt_root=_receipt_root(unsigned),
        )

    @model_validator(mode="after")
    def verify_receipt(self) -> Self:
        _require_accepted_matching_calibration(
            self.calibration_receipt,
            judge_profile=self.judge_profile,
        )
        expected_root = _receipt_root(self.model_dump(mode="json", exclude={"receipt_root"}))
        if not hmac.compare_digest(expected_root, self.receipt_root):
            raise ValueError("semantic judgment receipt root does not match receipt content")
        return self


def _revalidate_calibration(value: SemanticCalibrationReceipt) -> SemanticCalibrationReceipt:
    """Never trust an already-constructed model instance at a grading trust boundary."""
    if isinstance(value, SemanticCalibrationReceipt):
        return SemanticCalibrationReceipt.model_validate(value.model_dump(mode="json"))
    return SemanticCalibrationReceipt.model_validate(value)


def _require_accepted_matching_calibration(
    calibration: SemanticCalibrationReceipt,
    *,
    judge_profile: SemanticJudgeProfile,
) -> None:
    if not calibration.accepted:
        raise ValueError("semantic judgment requires an accepted calibration receipt")
    if calibration.judge_profile.identity != judge_profile.identity:
        raise ValueError("semantic judgment judge profile does not match calibrated judge profile")


def _receipt_root(value: object) -> str:
    return hashlib.sha256(_RECEIPT_DOMAIN + _canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("semantic judgment material must be finite JSON-compatible data") from exc
