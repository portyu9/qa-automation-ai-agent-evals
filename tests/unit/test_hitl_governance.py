from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from agent_evals.contracts.models import ApprovalDecision
from agent_evals.hitl import (
    ApprovalAuthenticationMethod,
    ApprovalDelegation,
    ApprovalGovernancePolicy,
    ApprovalGovernanceReceipt,
    ApprovalRole,
    HITLResumeAttempt,
    HITLResumeCheckpoint,
    HITLResumeOutcome,
    HITLResumeReceipt,
    HumanApprovalEvidence,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _approval(
    *,
    approval_id: str,
    signer: str,
    session: str,
    observed_at: int,
    role: ApprovalRole = ApprovalRole.APPROVER,
    delegated_by: str | None = None,
    verified: bool = True,
) -> HumanApprovalEvidence:
    return HumanApprovalEvidence.create(
        approval_id=approval_id,
        scenario_identity="a" * 64,
        invocation_sha256="b" * 64,
        signer_id=signer,
        session_id=session,
        observed_at_unix_ms=observed_at,
        decision=ApprovalDecision.APPROVE,
        authentication_method=ApprovalAuthenticationMethod.WEBAUTHN,
        credential_fingerprint_sha256=_sha(f"credential:{signer}"),
        authentication_verified=verified,
        role=role,
        delegated_by=delegated_by,
    )


def test_authenticated_approval_governance_quorum_delegation_escalation_and_sod() -> None:
    direct = _approval(
        approval_id="approval.direct",
        signer="approver-a",
        session="session-a",
        observed_at=1_500,
    )
    delegated = _approval(
        approval_id="approval.delegated",
        signer="approver-b",
        session="session-b",
        observed_at=1_600,
        role=ApprovalRole.ESCALATION_APPROVER,
        delegated_by="manager",
    )
    delegation = ApprovalDelegation(
        delegator_id="manager",
        delegate_id="approver-b",
        scenario_identity="a" * 64,
        invocation_sha256="b" * 64,
        expires_at_unix_ms=2_500,
        externally_verified=True,
    )
    policy = ApprovalGovernancePolicy(
        quorum=2,
        max_age_ms=1_000,
        allow_delegation=True,
        require_escalation_approver=True,
    )

    receipt = ApprovalGovernanceReceipt.create(
        policy=policy,
        requester_id="requester",
        evaluated_at_unix_ms=2_000,
        approvals=(direct, delegated),
        delegations=(delegation,),
    )

    assert receipt.accepted is True
    assert receipt.effective_signers == ("approver-a", "approver-b")

    revoked = ApprovalGovernanceReceipt.create(
        policy=policy,
        requester_id="requester",
        evaluated_at_unix_ms=2_000,
        approvals=(direct, delegated),
        delegations=(delegation,),
        revoked_approval_ids=frozenset({"approval.delegated"}),
    )
    assert revoked.accepted is False

    expired = ApprovalGovernanceReceipt.create(
        policy=policy,
        requester_id="requester",
        evaluated_at_unix_ms=3_000,
        approvals=(direct, delegated),
        delegations=(delegation,),
    )
    assert expired.accepted is False


def test_unverified_or_requester_self_approval_cannot_satisfy_governance() -> None:
    unverified = _approval(
        approval_id="approval.unverified",
        signer="approver",
        session="session-a",
        observed_at=100,
        verified=False,
    )
    requester = _approval(
        approval_id="approval.requester",
        signer="requester",
        session="session-b",
        observed_at=100,
    )

    receipt = ApprovalGovernanceReceipt.create(
        policy=ApprovalGovernancePolicy(quorum=1),
        requester_id="requester",
        evaluated_at_unix_ms=200,
        approvals=(unverified, requester),
    )

    assert receipt.effective_signers == ()
    assert receipt.accepted is False


def test_crash_safe_hitl_resume_accepts_exactly_one_completion_and_rejects_duplicates() -> None:
    checkpoint = HITLResumeCheckpoint.create(
        run_id="run-7",
        scenario_identity="a" * 64,
        invocation_sha256="b" * 64,
        approval_receipt_root="c" * 64,
        generation=3,
    )
    attempts = (
        HITLResumeAttempt(
            checkpoint_root=checkpoint.checkpoint_root,
            resume_id="resume.primary",
            worker_id="worker-a",
            outcome=HITLResumeOutcome.COMPLETED,
            continuation_sha256="d" * 64,
        ),
        HITLResumeAttempt(
            checkpoint_root=checkpoint.checkpoint_root,
            resume_id="resume.duplicate",
            worker_id="worker-b",
            outcome=HITLResumeOutcome.DUPLICATE_REJECTED,
        ),
    )

    receipt = HITLResumeReceipt.create(checkpoint=checkpoint, attempts=attempts)

    assert receipt.accepted is True
    assert receipt.completed_resume_id == "resume.primary"
    assert receipt.duplicate_rejections == 1

    double_completion = HITLResumeReceipt.create(
        checkpoint=checkpoint,
        attempts=(
            attempts[0],
            HITLResumeAttempt(
                checkpoint_root=checkpoint.checkpoint_root,
                resume_id="resume.second",
                worker_id="worker-b",
                outcome=HITLResumeOutcome.COMPLETED,
                continuation_sha256="e" * 64,
            ),
        ),
    )
    assert double_completion.accepted is False
    assert double_completion.completed_resume_id is None

    with pytest.raises(ValueError, match="different checkpoint"):
        HITLResumeReceipt.create(
            checkpoint=checkpoint,
            attempts=(
                HITLResumeAttempt(
                    checkpoint_root="f" * 64,
                    resume_id="resume.foreign",
                    worker_id="worker-x",
                    outcome=HITLResumeOutcome.DUPLICATE_REJECTED,
                ),
            ),
        )


def test_receipt_validation_context_cannot_self_declare_trusted_construction() -> None:
    approval = _approval(
        approval_id="approval.context",
        signer="approver",
        session="session",
        observed_at=100,
    )
    receipt = ApprovalGovernanceReceipt.create(
        policy=ApprovalGovernancePolicy(),
        requester_id="requester",
        evaluated_at_unix_ms=200,
        approvals=(approval,),
    )
    tampered = receipt.model_dump(mode="json")
    tampered["accepted"] = False

    with pytest.raises(ValidationError, match="does not recompute"):
        ApprovalGovernanceReceipt.model_validate(
            tampered,
            context={"agent_evals_receipt_construction": True},
        )


def test_unordered_governance_material_is_root_stable_and_round_trips() -> None:
    methods = list(ApprovalAuthenticationMethod)
    policy_a = ApprovalGovernancePolicy(
        allowed_authentication_methods=frozenset(methods),
    )
    policy_b = ApprovalGovernancePolicy(
        allowed_authentication_methods=frozenset(reversed(methods)),
    )
    approval = _approval(
        approval_id="approval.canonical",
        signer="approver",
        session="session-canonical",
        observed_at=100,
    )
    revoked_a = frozenset(("approval.z", "approval.a"))
    revoked_b = frozenset(("approval.a", "approval.z"))

    receipt_a = ApprovalGovernanceReceipt.create(
        policy=policy_a,
        requester_id="requester",
        evaluated_at_unix_ms=200,
        approvals=(approval,),
        revoked_approval_ids=revoked_a,
    )
    receipt_b = ApprovalGovernanceReceipt.create(
        policy=policy_b,
        requester_id="requester",
        evaluated_at_unix_ms=200,
        approvals=(approval,),
        revoked_approval_ids=revoked_b,
    )

    assert policy_a.model_dump_json() == policy_b.model_dump_json()
    assert receipt_a.receipt_root == receipt_b.receipt_root
    round_tripped = ApprovalGovernanceReceipt.model_validate_json(receipt_a.model_dump_json())
    assert round_tripped.receipt_root == receipt_a.receipt_root
