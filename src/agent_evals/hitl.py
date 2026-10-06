"""Authenticated human-approval governance and duplicate-safe resume assurance.

The existing ApprovalIntentSpec/receipt binds evaluator intent to an exact invocation. This module
adds a separate human-authentication/governance evidence domain. Receipt hashes provide integrity
only; authentication must be established by the external verifier represented in each observation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from agent_evals._receipt_validation import (
    is_receipt_construction,
    validate_receipt_construction,
)
from agent_evals.contracts.models import ApprovalDecision

_EVIDENCE_SCHEMA: Literal["agent-evals/human-approval-evidence/v1"] = (
    "agent-evals/human-approval-evidence/v1"
)
_POLICY_SCHEMA: Literal["agent-evals/approval-governance-policy/v1"] = (
    "agent-evals/approval-governance-policy/v1"
)
_RECEIPT_SCHEMA: Literal["agent-evals/approval-governance-receipt/v1"] = (
    "agent-evals/approval-governance-receipt/v1"
)
_CHECKPOINT_SCHEMA: Literal["agent-evals/hitl-resume-checkpoint/v1"] = (
    "agent-evals/hitl-resume-checkpoint/v1"
)
_RESUME_RECEIPT_SCHEMA: Literal["agent-evals/hitl-resume-receipt/v1"] = (
    "agent-evals/hitl-resume-receipt/v1"
)
_EVIDENCE_DOMAIN = b"agent-evals/human-approval-evidence/v1\0"
_RECEIPT_DOMAIN = b"agent-evals/approval-governance-receipt/v1\0"
_CHECKPOINT_DOMAIN = b"agent-evals/hitl-resume-checkpoint/v1\0"
_RESUME_DOMAIN = b"agent-evals/hitl-resume-receipt/v1\0"


class ApprovalAuthenticationMethod(StrEnum):
    OIDC = "oidc"
    WEBAUTHN = "webauthn"
    MTLS = "mtls"
    SIGNED_TOKEN = "signed-token"


class ApprovalRole(StrEnum):
    APPROVER = "approver"
    ESCALATION_APPROVER = "escalation-approver"


class HITLResumeOutcome(StrEnum):
    COMPLETED = "completed"
    DUPLICATE_REJECTED = "duplicate-rejected"
    ABORTED = "aborted"


class HumanApprovalEvidence(BaseModel):
    """Externally authenticated human decision for one exact invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/human-approval-evidence/v1"] = _EVIDENCE_SCHEMA
    approval_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    invocation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signer_id: str = Field(min_length=1, max_length=256)
    session_id: str = Field(min_length=1, max_length=256)
    observed_at_unix_ms: int = Field(ge=0, le=9_999_999_999_999, strict=True)
    decision: ApprovalDecision
    role: ApprovalRole = ApprovalRole.APPROVER
    authentication_method: ApprovalAuthenticationMethod
    credential_fingerprint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authentication_verified: bool = Field(strict=True)
    delegated_by: str | None = Field(default=None, min_length=1, max_length=256)
    evidence_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        approval_id: str,
        scenario_identity: str,
        invocation_sha256: str,
        signer_id: str,
        session_id: str,
        observed_at_unix_ms: int,
        decision: ApprovalDecision,
        authentication_method: ApprovalAuthenticationMethod,
        credential_fingerprint_sha256: str,
        authentication_verified: bool,
        role: ApprovalRole = ApprovalRole.APPROVER,
        delegated_by: str | None = None,
    ) -> Self:
        material = {
            "schema_version": _EVIDENCE_SCHEMA,
            "approval_id": approval_id,
            "scenario_identity": scenario_identity,
            "invocation_sha256": invocation_sha256,
            "signer_id": signer_id,
            "session_id": session_id,
            "observed_at_unix_ms": observed_at_unix_ms,
            "decision": decision.value,
            "role": role.value,
            "authentication_method": authentication_method.value,
            "credential_fingerprint_sha256": credential_fingerprint_sha256,
            "authentication_verified": authentication_verified,
            "delegated_by": delegated_by,
        }
        return cls(**material, evidence_root=_domain_root(_EVIDENCE_DOMAIN, material))

    @model_validator(mode="after")
    def verify_root(self) -> Self:
        material = self.model_dump(mode="json", exclude={"evidence_root"})
        if not hmac.compare_digest(self.evidence_root, _domain_root(_EVIDENCE_DOMAIN, material)):
            raise ValueError("human approval evidence root mismatch")
        if self.signer_id != self.signer_id.strip() or self.session_id != self.session_id.strip():
            raise ValueError("human approval signer/session identity must be trimmed")
        if self.delegated_by is not None and self.delegated_by == self.signer_id:
            raise ValueError("approval delegation cannot be self-delegation")
        return self


class ApprovalDelegation(BaseModel):
    """Bounded approval delegation valid for one scenario/invocation scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    delegator_id: str = Field(min_length=1, max_length=256)
    delegate_id: str = Field(min_length=1, max_length=256)
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    invocation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expires_at_unix_ms: int = Field(ge=0, le=9_999_999_999_999, strict=True)
    externally_verified: bool = Field(strict=True)

    @model_validator(mode="after")
    def validate_delegation(self) -> Self:
        if self.delegator_id == self.delegate_id:
            raise ValueError("approval delegation must change signer identity")
        return self


class ApprovalGovernancePolicy(BaseModel):
    """Expiry, revocation, delegation, escalation, quorum and separation-of-duties policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/approval-governance-policy/v1"] = _POLICY_SCHEMA
    quorum: int = Field(default=1, ge=1, le=100, strict=True)
    max_age_ms: int = Field(default=15 * 60 * 1000, ge=1, le=7 * 24 * 60 * 60 * 1000, strict=True)
    require_distinct_sessions: bool = Field(default=True, strict=True)
    require_separation_of_duties: bool = Field(default=True, strict=True)
    allow_delegation: bool = Field(default=False, strict=True)
    require_escalation_approver: bool = Field(default=False, strict=True)
    allowed_authentication_methods: frozenset[ApprovalAuthenticationMethod] = frozenset(
        ApprovalAuthenticationMethod
    )


class ApprovalGovernanceReceipt(BaseModel):
    """Integrity-bound human approval policy evaluation for one exact invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/approval-governance-receipt/v1"] = _RECEIPT_SCHEMA
    policy: ApprovalGovernancePolicy
    requester_id: str = Field(min_length=1, max_length=256)
    evaluated_at_unix_ms: int = Field(ge=0, le=9_999_999_999_999, strict=True)
    approvals: tuple[HumanApprovalEvidence, ...] = Field(min_length=1, max_length=100)
    delegations: tuple[ApprovalDelegation, ...] = ()
    revoked_approval_ids: frozenset[str] = frozenset()
    effective_signers: tuple[str, ...]
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        policy: ApprovalGovernancePolicy,
        requester_id: str,
        evaluated_at_unix_ms: int,
        approvals: tuple[HumanApprovalEvidence, ...],
        delegations: tuple[ApprovalDelegation, ...] = (),
        revoked_approval_ids: frozenset[str] = frozenset(),
    ) -> Self:
        _require_exact(policy, ApprovalGovernancePolicy, "approval governance policy")
        checked_policy = ApprovalGovernancePolicy.model_validate_json(policy.model_dump_json())
        if not requester_id.strip() or requester_id != requester_id.strip():
            raise ValueError("approval requester identity must be trimmed and non-empty")
        if isinstance(evaluated_at_unix_ms, bool) or evaluated_at_unix_ms < 0:
            raise ValueError("approval evaluation timestamp must be a non-negative integer")

        checked_approvals: list[HumanApprovalEvidence] = []
        for item in approvals:
            _require_exact(item, HumanApprovalEvidence, "human approval evidence")
            checked_approvals.append(
                HumanApprovalEvidence.model_validate_json(item.model_dump_json())
            )
        if not checked_approvals:
            raise ValueError("approval governance requires at least one approval")

        checked_delegations: list[ApprovalDelegation] = []
        for item in delegations:
            _require_exact(item, ApprovalDelegation, "approval delegation")
            checked_delegations.append(
                ApprovalDelegation.model_validate_json(item.model_dump_json())
            )

        ids = [item.approval_id for item in checked_approvals]
        if len(set(ids)) != len(ids):
            raise ValueError("human approval IDs must be unique")
        scenario_ids = {item.scenario_identity for item in checked_approvals}
        invocation_ids = {item.invocation_sha256 for item in checked_approvals}
        decisions = {item.decision for item in checked_approvals}
        if len(scenario_ids) != 1 or len(invocation_ids) != 1 or len(decisions) != 1:
            raise ValueError("approval quorum must bind one scenario, invocation, and decision")

        valid: list[HumanApprovalEvidence] = []
        for approval in checked_approvals:
            if not approval.authentication_verified:
                continue
            if approval.authentication_method not in checked_policy.allowed_authentication_methods:
                continue
            if approval.approval_id in revoked_approval_ids:
                continue
            age = evaluated_at_unix_ms - approval.observed_at_unix_ms
            if age < 0 or age > checked_policy.max_age_ms:
                continue
            if checked_policy.require_separation_of_duties and approval.signer_id == requester_id:
                continue
            if approval.delegated_by is not None:
                if not checked_policy.allow_delegation:
                    continue
                matching = [
                    delegation
                    for delegation in checked_delegations
                    if delegation.delegator_id == approval.delegated_by
                    and delegation.delegate_id == approval.signer_id
                    and delegation.scenario_identity == approval.scenario_identity
                    and delegation.invocation_sha256 == approval.invocation_sha256
                    and delegation.expires_at_unix_ms >= evaluated_at_unix_ms
                    and delegation.externally_verified
                ]
                if len(matching) != 1:
                    continue
            valid.append(approval)

        signers = tuple(sorted({item.signer_id for item in valid}))
        sessions = {item.session_id for item in valid}
        quorum_met = len(signers) >= checked_policy.quorum
        distinct_sessions_met = (
            not checked_policy.require_distinct_sessions or len(sessions) >= checked_policy.quorum
        )
        escalation_met = not checked_policy.require_escalation_approver or any(
            item.role is ApprovalRole.ESCALATION_APPROVER for item in valid
        )
        accepted = quorum_met and distinct_sessions_met and escalation_met

        material = {
            "schema_version": _RECEIPT_SCHEMA,
            "policy": checked_policy.model_dump(mode="json"),
            "requester_id": requester_id,
            "evaluated_at_unix_ms": evaluated_at_unix_ms,
            "approvals": [item.model_dump(mode="json") for item in checked_approvals],
            "delegations": [item.model_dump(mode="json") for item in checked_delegations],
            "revoked_approval_ids": sorted(revoked_approval_ids),
            "effective_signers": list(signers),
            "accepted": accepted,
        }
        return validate_receipt_construction(
            cls,
            policy=checked_policy,
            requester_id=requester_id,
            evaluated_at_unix_ms=evaluated_at_unix_ms,
            approvals=tuple(checked_approvals),
            delegations=tuple(checked_delegations),
            revoked_approval_ids=revoked_approval_ids,
            effective_signers=signers,
            accepted=accepted,
            receipt_root=_domain_root(_RECEIPT_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_receipt(self, info: ValidationInfo) -> Self:
        if is_receipt_construction(info):
            return self
        rebuilt = type(self).create(
            policy=self.policy,
            requester_id=self.requester_id,
            evaluated_at_unix_ms=self.evaluated_at_unix_ms,
            approvals=self.approvals,
            delegations=self.delegations,
            revoked_approval_ids=self.revoked_approval_ids,
        )
        if (
            self.effective_signers != rebuilt.effective_signers
            or self.accepted != rebuilt.accepted
            or not hmac.compare_digest(self.receipt_root, rebuilt.receipt_root)
        ):
            raise ValueError("approval governance receipt does not recompute")
        return self


class HITLResumeCheckpoint(BaseModel):
    """Durable content-addressed checkpoint for one paused exact invocation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/hitl-resume-checkpoint/v1"] = _CHECKPOINT_SCHEMA
    run_id: str = Field(min_length=1, max_length=512)
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    invocation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approval_receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    generation: int = Field(ge=0, le=1_000_000, strict=True)
    checkpoint_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        scenario_identity: str,
        invocation_sha256: str,
        approval_receipt_root: str,
        generation: int,
    ) -> Self:
        material = {
            "schema_version": _CHECKPOINT_SCHEMA,
            "run_id": run_id,
            "scenario_identity": scenario_identity,
            "invocation_sha256": invocation_sha256,
            "approval_receipt_root": approval_receipt_root,
            "generation": generation,
        }
        return cls(**material, checkpoint_root=_domain_root(_CHECKPOINT_DOMAIN, material))

    @model_validator(mode="after")
    def verify_root(self) -> Self:
        expected = _domain_root(
            _CHECKPOINT_DOMAIN,
            self.model_dump(mode="json", exclude={"checkpoint_root"}),
        )
        if not hmac.compare_digest(self.checkpoint_root, expected):
            raise ValueError("HITL resume checkpoint root mismatch")
        return self


class HITLResumeAttempt(BaseModel):
    """One worker attempt to resume a durable checkpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    checkpoint_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    resume_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    worker_id: str = Field(min_length=1, max_length=256)
    outcome: HITLResumeOutcome
    continuation_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.outcome is HITLResumeOutcome.COMPLETED and self.continuation_sha256 is None:
            raise ValueError("completed HITL resume requires continuation digest")
        if self.outcome is not HITLResumeOutcome.COMPLETED and self.continuation_sha256 is not None:
            raise ValueError("non-completed HITL resume cannot carry continuation digest")
        return self


class HITLResumeReceipt(BaseModel):
    """Crash-safe/duplicate-safe resume evidence: exactly one completion, duplicates rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/hitl-resume-receipt/v1"] = _RESUME_RECEIPT_SCHEMA
    checkpoint: HITLResumeCheckpoint
    attempts: tuple[HITLResumeAttempt, ...] = Field(min_length=1, max_length=10_000)
    completed_resume_id: str | None = None
    duplicate_rejections: int = Field(ge=0, strict=True)
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        checkpoint: HITLResumeCheckpoint,
        attempts: tuple[HITLResumeAttempt, ...],
    ) -> Self:
        _require_exact(checkpoint, HITLResumeCheckpoint, "HITL resume checkpoint")
        checked_checkpoint = HITLResumeCheckpoint.model_validate_json(checkpoint.model_dump_json())
        checked: list[HITLResumeAttempt] = []
        for item in attempts:
            _require_exact(item, HITLResumeAttempt, "HITL resume attempt")
            value = HITLResumeAttempt.model_validate_json(item.model_dump_json())
            if value.checkpoint_root != checked_checkpoint.checkpoint_root:
                raise ValueError("HITL resume attempt references a different checkpoint")
            checked.append(value)
        ids = [item.resume_id for item in checked]
        if len(set(ids)) != len(ids):
            raise ValueError("HITL resume IDs must be unique")
        completed = [item for item in checked if item.outcome is HITLResumeOutcome.COMPLETED]
        duplicate_rejections = sum(
            item.outcome is HITLResumeOutcome.DUPLICATE_REJECTED for item in checked
        )
        accepted = len(completed) == 1 and all(
            item.outcome in {HITLResumeOutcome.COMPLETED, HITLResumeOutcome.DUPLICATE_REJECTED}
            for item in checked
        )
        completed_id = completed[0].resume_id if len(completed) == 1 else None
        material = {
            "schema_version": _RESUME_RECEIPT_SCHEMA,
            "checkpoint": checked_checkpoint.model_dump(mode="json"),
            "attempts": [item.model_dump(mode="json") for item in checked],
            "completed_resume_id": completed_id,
            "duplicate_rejections": duplicate_rejections,
            "accepted": accepted,
        }
        return validate_receipt_construction(
            cls,
            checkpoint=checked_checkpoint,
            attempts=tuple(checked),
            completed_resume_id=completed_id,
            duplicate_rejections=duplicate_rejections,
            accepted=accepted,
            receipt_root=_domain_root(_RESUME_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_receipt(self, info: ValidationInfo) -> Self:
        if is_receipt_construction(info):
            return self
        rebuilt = type(self).create(checkpoint=self.checkpoint, attempts=self.attempts)
        if (
            self.completed_resume_id != rebuilt.completed_resume_id
            or self.duplicate_rejections != rebuilt.duplicate_rejections
            or self.accepted != rebuilt.accepted
            or not hmac.compare_digest(self.receipt_root, rebuilt.receipt_root)
        ):
            raise ValueError("HITL resume receipt does not recompute")
        return self


def _require_exact(value: object, expected: type[object], label: str) -> None:
    if type(value) is not expected:
        raise ValueError(f"{label} requires exact {expected.__name__}")


def _domain_root(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + _canonical_json_bytes(value)).hexdigest()


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
        raise ValueError("HITL assurance material must be finite JSON-compatible data") from exc


__all__ = [
    "ApprovalAuthenticationMethod",
    "ApprovalDelegation",
    "ApprovalGovernancePolicy",
    "ApprovalGovernanceReceipt",
    "ApprovalRole",
    "HITLResumeAttempt",
    "HITLResumeCheckpoint",
    "HITLResumeOutcome",
    "HITLResumeReceipt",
    "HumanApprovalEvidence",
]
