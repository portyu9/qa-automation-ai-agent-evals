from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

import agent_evals.hitl as hitl
import agent_evals.memory as memory
import agent_evals.retrieval.production as retrieval_production
import agent_evals.runtime.chaos as chaos
import agent_evals.side_effect.distributed as distributed

from agent_evals.contracts.models import ApprovalDecision
from agent_evals.hitl import (
    ApprovalAuthenticationMethod,
    ApprovalDelegation,
    ApprovalGovernancePolicy,
    ApprovalGovernanceReceipt,
    HITLResumeAttempt,
    HITLResumeCheckpoint,
    HITLResumeOutcome,
    HITLResumeReceipt,
    HumanApprovalEvidence,
)
from agent_evals.memory import (
    MemoryAssurancePolicy,
    MemoryAssuranceReceipt,
    MemoryObservation,
    MemoryOperationKind,
)
from agent_evals.retrieval.production import (
    RetrievalDocumentLifecycle,
    RetrievalMode,
    RetrievalPipelinePolicy,
    RetrievalPipelineReceipt,
    RetrievalPipelineViolation,
    RetrievedDocumentObservation,
)
from agent_evals.runtime.chaos import (
    ChaosAssuranceReceipt,
    ChaosDomain,
    ChaosObservation,
    ChaosOutcome,
    ChaosPolicy,
)
from agent_evals.side_effect.distributed import (
    DistributedSideEffectAttempt,
    DistributedSideEffectPolicy,
    DistributedSideEffectReceipt,
    SideEffectAttemptCause,
    SideEffectAttemptOutcome,
    TargetEffectAcknowledgement,
    verify_target_acknowledgement,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _approval(
    *,
    approval_id: str = "approval.boundary",
    signer: str = "approver",
    session: str = "session",
    scenario: str = "a" * 64,
    invocation: str = "b" * 64,
    decision: ApprovalDecision = ApprovalDecision.APPROVE,
    verified: bool = True,
    delegated_by: str | None = None,
) -> HumanApprovalEvidence:
    return HumanApprovalEvidence.create(
        approval_id=approval_id,
        scenario_identity=scenario,
        invocation_sha256=invocation,
        signer_id=signer,
        session_id=session,
        observed_at_unix_ms=100,
        decision=decision,
        authentication_method=ApprovalAuthenticationMethod.WEBAUTHN,
        credential_fingerprint_sha256=_sha(f"credential:{signer}"),
        authentication_verified=verified,
        delegated_by=delegated_by,
    )


def test_hitl_evidence_and_delegation_validators_fail_closed() -> None:
    with pytest.raises(ValidationError, match="must be trimmed"):
        _approval(signer=" approver")
    with pytest.raises(ValidationError, match="self-delegation"):
        _approval(delegated_by="approver")
    with pytest.raises(ValidationError, match="change signer identity"):
        ApprovalDelegation(
            delegator_id="same",
            delegate_id="same",
            scenario_identity="a" * 64,
            invocation_sha256="b" * 64,
            expires_at_unix_ms=1_000,
            externally_verified=True,
        )

    approval = _approval()
    tampered = approval.model_dump(mode="json")
    tampered["evidence_root"] = "0" * 64
    with pytest.raises(ValidationError, match="root mismatch"):
        HumanApprovalEvidence.model_validate(tampered)


def test_approval_governance_rejects_bad_inputs_and_mixed_quorums() -> None:
    policy = ApprovalGovernancePolicy()
    approval = _approval()

    with pytest.raises(ValueError, match="requester identity"):
        ApprovalGovernanceReceipt.create(
            policy=policy,
            requester_id=" requester",
            evaluated_at_unix_ms=200,
            approvals=(approval,),
        )
    with pytest.raises(ValueError, match="timestamp"):
        ApprovalGovernanceReceipt.create(
            policy=policy,
            requester_id="requester",
            evaluated_at_unix_ms=True,
            approvals=(approval,),
        )
    with pytest.raises(ValueError, match="at least one approval"):
        ApprovalGovernanceReceipt.create(
            policy=policy,
            requester_id="requester",
            evaluated_at_unix_ms=200,
            approvals=(),
        )
    with pytest.raises(ValueError, match="IDs must be unique"):
        ApprovalGovernanceReceipt.create(
            policy=policy,
            requester_id="requester",
            evaluated_at_unix_ms=200,
            approvals=(approval, approval),
        )

    mixed_decision = _approval(
        approval_id="approval.reject",
        signer="other",
        session="other-session",
        decision=ApprovalDecision.REJECT,
    )
    with pytest.raises(ValueError, match="one scenario, invocation, and decision"):
        ApprovalGovernanceReceipt.create(
            policy=ApprovalGovernancePolicy(quorum=2),
            requester_id="requester",
            evaluated_at_unix_ms=200,
            approvals=(approval, mixed_decision),
        )

    wrong_scenario = _approval(
        approval_id="approval.other-scenario",
        signer="other",
        session="other-session",
        scenario="c" * 64,
    )
    with pytest.raises(ValueError, match="one scenario, invocation, and decision"):
        ApprovalGovernanceReceipt.create(
            policy=ApprovalGovernancePolicy(quorum=2),
            requester_id="requester",
            evaluated_at_unix_ms=200,
            approvals=(approval, wrong_scenario),
        )


def test_approval_governance_filters_untrusted_auth_and_delegation() -> None:
    oidc_only = ApprovalGovernancePolicy(
        allowed_authentication_methods=frozenset({ApprovalAuthenticationMethod.OIDC})
    )
    receipt = ApprovalGovernanceReceipt.create(
        policy=oidc_only,
        requester_id="requester",
        evaluated_at_unix_ms=200,
        approvals=(_approval(),),
    )
    assert receipt.accepted is False

    delegated = _approval(delegated_by="manager")
    no_delegation = ApprovalGovernanceReceipt.create(
        policy=ApprovalGovernancePolicy(allow_delegation=False),
        requester_id="requester",
        evaluated_at_unix_ms=200,
        approvals=(delegated,),
    )
    assert no_delegation.accepted is False

    missing_evidence = ApprovalGovernanceReceipt.create(
        policy=ApprovalGovernancePolicy(allow_delegation=True),
        requester_id="requester",
        evaluated_at_unix_ms=200,
        approvals=(delegated,),
    )
    assert missing_evidence.accepted is False

    expired = ApprovalGovernanceReceipt.create(
        policy=ApprovalGovernancePolicy(max_age_ms=10),
        requester_id="requester",
        evaluated_at_unix_ms=200,
        approvals=(_approval(),),
    )
    assert expired.accepted is False


def _checkpoint() -> HITLResumeCheckpoint:
    return HITLResumeCheckpoint.create(
        run_id="run-boundary",
        scenario_identity="a" * 64,
        invocation_sha256="b" * 64,
        approval_receipt_root="c" * 64,
        generation=1,
    )


def test_hitl_resume_validators_and_tamper_checks() -> None:
    checkpoint = _checkpoint()

    with pytest.raises(ValidationError, match="requires continuation"):
        HITLResumeAttempt(
            checkpoint_root=checkpoint.checkpoint_root,
            resume_id="resume.missing",
            worker_id="worker",
            outcome=HITLResumeOutcome.COMPLETED,
        )
    with pytest.raises(ValidationError, match="cannot carry continuation"):
        HITLResumeAttempt(
            checkpoint_root=checkpoint.checkpoint_root,
            resume_id="resume.extra",
            worker_id="worker",
            outcome=HITLResumeOutcome.ABORTED,
            continuation_sha256="d" * 64,
        )

    completed = HITLResumeAttempt(
        checkpoint_root=checkpoint.checkpoint_root,
        resume_id="resume.completed",
        worker_id="worker",
        outcome=HITLResumeOutcome.COMPLETED,
        continuation_sha256="d" * 64,
    )
    with pytest.raises(ValueError, match="IDs must be unique"):
        HITLResumeReceipt.create(
            checkpoint=checkpoint,
            attempts=(completed, completed),
        )

    aborted = HITLResumeReceipt.create(
        checkpoint=checkpoint,
        attempts=(
            HITLResumeAttempt(
                checkpoint_root=checkpoint.checkpoint_root,
                resume_id="resume.aborted",
                worker_id="worker",
                outcome=HITLResumeOutcome.ABORTED,
            ),
        ),
    )
    assert aborted.accepted is False

    tampered_checkpoint = checkpoint.model_dump(mode="json")
    tampered_checkpoint["checkpoint_root"] = "0" * 64
    with pytest.raises(ValidationError, match="root mismatch"):
        HITLResumeCheckpoint.model_validate(tampered_checkpoint)


def _memory_policy(**overrides: object) -> MemoryAssurancePolicy:
    values: dict[str, object] = {
        "record_id": "memory-boundary",
        "owner_tenant_id": "tenant-a",
        "owner_user_id": "user-a",
        "content_sha256": "a" * 64,
    }
    values.update(overrides)
    return MemoryAssurancePolicy.model_validate(values)


def _memory_observation(
    *,
    operation: MemoryOperationKind,
    tick: int,
    allowed: bool,
    actor_tenant: str = "tenant-a",
    actor_user: str = "user-a",
    returned: str | None = None,
    poison: bool = False,
    created_tick: int = 0,
    expires_tick: int = 10,
) -> MemoryObservation:
    return MemoryObservation(
        record_id="memory-boundary",
        owner_tenant_id="tenant-a",
        owner_user_id="user-a",
        actor_tenant_id=actor_tenant,
        actor_user_id=actor_user,
        operation=operation,
        tick=tick,
        created_tick=created_tick,
        expires_tick=expires_tick,
        content_sha256="a" * 64,
        allowed=allowed,
        returned_content_sha256=returned,
        poison_marker=poison,
    )


def test_memory_observation_shape_is_fail_closed() -> None:
    with pytest.raises(ValidationError, match="expiry cannot precede"):
        _memory_observation(
            operation=MemoryOperationKind.WRITE,
            tick=0,
            allowed=True,
            created_tick=2,
            expires_tick=1,
        )
    with pytest.raises(ValidationError, match="cannot precede"):
        _memory_observation(
            operation=MemoryOperationKind.READ,
            tick=0,
            allowed=False,
            created_tick=1,
        )
    with pytest.raises(ValidationError, match="requires returned"):
        _memory_observation(
            operation=MemoryOperationKind.READ,
            tick=1,
            allowed=True,
        )
    with pytest.raises(ValidationError, match="cannot expose"):
        _memory_observation(
            operation=MemoryOperationKind.READ,
            tick=1,
            allowed=False,
            returned="a" * 64,
        )
    with pytest.raises(ValidationError, match="non-read"):
        _memory_observation(
            operation=MemoryOperationKind.WRITE,
            tick=0,
            allowed=True,
            returned="a" * 64,
        )
    with pytest.raises(ValidationError, match="explicitly marked"):
        _memory_observation(
            operation=MemoryOperationKind.POISON_ATTEMPT,
            tick=1,
            allowed=False,
        )


def test_memory_receipt_orders_observations_and_supports_optional_policy() -> None:
    write = _memory_observation(
        operation=MemoryOperationKind.WRITE,
        tick=0,
        allowed=True,
    )
    read = _memory_observation(
        operation=MemoryOperationKind.READ,
        tick=2,
        allowed=True,
        returned="a" * 64,
    )
    with pytest.raises(ValueError, match="ordered"):
        MemoryAssuranceReceipt.create(
            policy=_memory_policy(),
            observations=(read, write),
        )

    optional = MemoryAssuranceReceipt.create(
        policy=_memory_policy(
            require_cross_user_isolation=False,
            require_delete_enforcement=False,
            require_ttl_enforcement=False,
            require_poison_rejection=False,
        ),
        observations=(write, read),
    )
    assert optional.persistence_observed is True
    assert optional.accepted is True

    tampered = optional.model_dump(mode="json")
    tampered["accepted"] = False
    with pytest.raises(ValidationError, match="metrics do not recompute"):
        MemoryAssuranceReceipt.model_validate(tampered)


def _retrieval_policy(**overrides: object) -> RetrievalPipelinePolicy:
    values: dict[str, object] = {
        "tenant_id": "tenant-a",
        "mode": RetrievalMode.HYBRID,
        "top_k": 2,
        "allowed_collections": frozenset({"docs"}),
        "required_labels": frozenset({"prod"}),
        "require_query_rewrite": True,
        "require_reranker": True,
        "require_citations": True,
    }
    values.update(overrides)
    return RetrievalPipelinePolicy.model_validate(values)


def _document(
    *,
    document_id: str = "doc-1",
    rank: int = 1,
    tenant: str = "tenant-a",
    collection: str = "docs",
    labels: frozenset[str] = frozenset({"prod"}),
    lifecycle: RetrievalDocumentLifecycle = RetrievalDocumentLifecycle.ACTIVE,
    lexical: int | None = 5,
    vector: int | None = 100,
    rerank: int | None = 20,
    citation: str | None = "https://docs.example.test/1",
) -> RetrievedDocumentObservation:
    return RetrievedDocumentObservation(
        document_id=document_id,
        tenant_id=tenant,
        collection=collection,
        labels=labels,
        lifecycle=lifecycle,
        rank=rank,
        lexical_score=lexical,
        vector_score_micros=vector,
        rerank_score=rerank,
        content_sha256=_sha(document_id),
        citation_uri=citation,
    )


def test_retrieval_validation_and_structural_errors() -> None:
    with pytest.raises(ValidationError, match="trimmed"):
        _retrieval_policy(allowed_collections=frozenset({" docs"}))
    with pytest.raises(ValidationError, match="trimmed"):
        _document(labels=frozenset({" prod"}))

    policy = _retrieval_policy(top_k=1)
    with pytest.raises(ValueError, match="more documents than top_k"):
        RetrievalPipelineReceipt.create(
            policy=policy,
            documents=(_document(), _document(document_id="doc-2", rank=2)),
            query_sha256="a" * 64,
        )

    with pytest.raises(ValueError, match="IDs must be unique"):
        RetrievalPipelineReceipt.create(
            policy=_retrieval_policy(),
            documents=(_document(), _document(rank=2)),
            query_sha256="a" * 64,
        )

    with pytest.raises(ValueError, match="contiguous"):
        RetrievalPipelineReceipt.create(
            policy=_retrieval_policy(),
            documents=(_document(rank=2),),
            query_sha256="a" * 64,
        )


def test_retrieval_violation_matrix_is_non_compensatory() -> None:
    bad = _document(
        tenant="tenant-b",
        collection="other",
        labels=frozenset(),
        lifecycle=RetrievalDocumentLifecycle.TOMBSTONED,
        lexical=None,
        vector=None,
        rerank=None,
        citation=None,
    )
    receipt = RetrievalPipelineReceipt.create(
        policy=_retrieval_policy(),
        documents=(bad,),
        query_sha256="a" * 64,
    )

    assert receipt.accepted is False
    assert set(receipt.violations) == {
        RetrievalPipelineViolation.FILTER_MISMATCH,
        RetrievalPipelineViolation.INACTIVE_DOCUMENT,
        RetrievalPipelineViolation.MISSING_CITATION,
        RetrievalPipelineViolation.MISSING_LEXICAL_SCORE,
        RetrievalPipelineViolation.MISSING_RERANKER,
        RetrievalPipelineViolation.MISSING_REWRITE,
        RetrievalPipelineViolation.MISSING_VECTOR_SCORE,
        RetrievalPipelineViolation.RERANK_ORDER,
        RetrievalPipelineViolation.WRONG_COLLECTION,
        RetrievalPipelineViolation.WRONG_TENANT,
    }


def test_retrieval_rerank_order_and_mode_specific_scores() -> None:
    first = _document(document_id="doc-1", rank=1, rerank=10)
    second = _document(document_id="doc-2", rank=2, rerank=20)
    receipt = RetrievalPipelineReceipt.create(
        policy=_retrieval_policy(),
        documents=(first, second),
        query_sha256="a" * 64,
        rewritten_query_sha256="b" * 64,
        reranker_identity="reranker-v1",
    )
    assert receipt.violations == (RetrievalPipelineViolation.RERANK_ORDER,)

    lexical = RetrievalPipelineReceipt.create(
        policy=_retrieval_policy(
            mode=RetrievalMode.LEXICAL,
            require_query_rewrite=False,
            require_reranker=False,
            require_citations=False,
            required_labels=frozenset(),
        ),
        documents=(_document(vector=None, rerank=None, citation=None),),
        query_sha256="a" * 64,
    )
    assert lexical.accepted is True

    vector = RetrievalPipelineReceipt.create(
        policy=_retrieval_policy(
            mode=RetrievalMode.VECTOR,
            require_query_rewrite=False,
            require_reranker=False,
            require_citations=False,
            required_labels=frozenset(),
        ),
        documents=(_document(lexical=None, rerank=None, citation=None),),
        query_sha256="a" * 64,
    )
    assert vector.accepted is True


def _chaos_observation(
    *,
    domain: ChaosDomain = ChaosDomain.CLOCK,
    injection_id: str = "chaos.clock",
    outcome: ChaosOutcome = ChaosOutcome.RECOVERED,
    recovery_ticks: int | None = 10,
    resource_peak_bytes: int = 100,
    secret_exposed: bool = False,
    error_code: str | None = None,
    injected: bool = True,
) -> ChaosObservation:
    return ChaosObservation(
        domain=domain,
        injection_id=injection_id,
        injected=injected,
        outcome=outcome,
        recovery_ticks=recovery_ticks,
        resource_peak_bytes=resource_peak_bytes,
        secret_exposed=secret_exposed,
        error_code=error_code,
    )


def test_chaos_observation_shape_and_receipt_limits() -> None:
    with pytest.raises(ValidationError, match="prove disturbance"):
        _chaos_observation(injected=False)
    with pytest.raises(ValidationError, match="requires recovery"):
        _chaos_observation(recovery_ticks=None)
    with pytest.raises(ValidationError, match="cannot carry evaluator"):
        _chaos_observation(error_code="unexpected")
    with pytest.raises(ValidationError, match="requires evaluator"):
        _chaos_observation(
            outcome=ChaosOutcome.BLOCKED,
            recovery_ticks=None,
            error_code=None,
        )

    observation = _chaos_observation()
    with pytest.raises(ValueError, match="IDs must be unique"):
        ChaosAssuranceReceipt.create(
            policy=ChaosPolicy(required_domains=frozenset({ChaosDomain.CLOCK})),
            observations=(observation, observation),
        )

    over_resource = ChaosAssuranceReceipt.create(
        policy=ChaosPolicy(
            required_domains=frozenset({ChaosDomain.CLOCK}),
            max_resource_bytes=50,
        ),
        observations=(observation,),
    )
    assert over_resource.qualification_complete is False

    slow = ChaosAssuranceReceipt.create(
        policy=ChaosPolicy(
            required_domains=frozenset({ChaosDomain.CLOCK}),
            max_recovery_ticks=5,
        ),
        observations=(observation,),
    )
    assert slow.qualification_complete is False

    secret = ChaosAssuranceReceipt.create(
        policy=ChaosPolicy(required_domains=frozenset({ChaosDomain.CLOCK})),
        observations=(_chaos_observation(secret_exposed=True),),
    )
    assert secret.qualification_complete is False


def _side_attempt(
    *,
    attempt_id: str,
    cause: SideEffectAttemptCause,
    outcome: SideEffectAttemptOutcome,
    delivery_id: str,
    operation: str = "a" * 64,
    key: str = "b" * 64,
    transaction: str | None = None,
    mutation: str | None = None,
    start: int = 0,
    end: int = 1,
) -> DistributedSideEffectAttempt:
    return DistributedSideEffectAttempt(
        operation_identity=operation,
        idempotency_key_sha256=key,
        attempt_id=attempt_id,
        worker_id=f"worker-{attempt_id}",
        delivery_id=delivery_id,
        cause=cause,
        outcome=outcome,
        transaction_id=transaction,
        mutation_sha256=mutation,
        started_tick=start,
        completed_tick=end,
    )


def test_distributed_side_effect_attempt_and_policy_validation() -> None:
    with pytest.raises(ValidationError, match="attempt-cause coverage"):
        DistributedSideEffectPolicy(required_causes=frozenset())
    with pytest.raises(ValidationError, match="cannot complete before"):
        _side_attempt(
            attempt_id="attempt.order",
            cause=SideEffectAttemptCause.INITIAL,
            outcome=SideEffectAttemptOutcome.TIMED_OUT,
            delivery_id="delivery-order",
            start=2,
            end=1,
        )
    with pytest.raises(ValidationError, match="requires transaction"):
        _side_attempt(
            attempt_id="attempt.commit",
            cause=SideEffectAttemptCause.INITIAL,
            outcome=SideEffectAttemptOutcome.COMMITTED,
            delivery_id="delivery-commit",
        )
    with pytest.raises(ValidationError, match="cannot claim physical"):
        _side_attempt(
            attempt_id="attempt.noncommit",
            cause=SideEffectAttemptCause.INITIAL,
            outcome=SideEffectAttemptOutcome.TIMED_OUT,
            delivery_id="delivery-noncommit",
            mutation="c" * 64,
        )


def test_distributed_side_effect_receipt_rejects_identity_and_delivery_ambiguity() -> None:
    first = _side_attempt(
        attempt_id="attempt.one",
        cause=SideEffectAttemptCause.INITIAL,
        outcome=SideEffectAttemptOutcome.TIMED_OUT,
        delivery_id="delivery-one",
    )
    with pytest.raises(ValueError, match="one operation and idempotency key"):
        DistributedSideEffectReceipt.create(
            policy=DistributedSideEffectPolicy(
                required_causes=frozenset({SideEffectAttemptCause.INITIAL})
            ),
            attempts=(
                first,
                _side_attempt(
                    attempt_id="attempt.two",
                    cause=SideEffectAttemptCause.INITIAL,
                    outcome=SideEffectAttemptOutcome.TIMED_OUT,
                    delivery_id="delivery-two",
                    operation="c" * 64,
                ),
            ),
        )

    with pytest.raises(ValueError, match="attempt IDs must be unique"):
        DistributedSideEffectReceipt.create(
            policy=DistributedSideEffectPolicy(
                required_causes=frozenset({SideEffectAttemptCause.INITIAL})
            ),
            attempts=(first, first.model_copy(update={"delivery_id": "delivery-two"})),
        )

    with pytest.raises(ValueError, match="delivery IDs must be unique"):
        DistributedSideEffectReceipt.create(
            policy=DistributedSideEffectPolicy(
                required_causes=frozenset({SideEffectAttemptCause.INITIAL})
            ),
            attempts=(
                first,
                _side_attempt(
                    attempt_id="attempt.two",
                    cause=SideEffectAttemptCause.INITIAL,
                    outcome=SideEffectAttemptOutcome.TIMED_OUT,
                    delivery_id="delivery-one",
                ),
            ),
        )


def test_target_acknowledgement_integrity_and_unique_commit_requirement() -> None:
    policy = DistributedSideEffectPolicy(
        required_causes=frozenset({SideEffectAttemptCause.INITIAL})
    )
    no_commit = DistributedSideEffectReceipt.create(
        policy=policy,
        attempts=(
            _side_attempt(
                attempt_id="attempt.none",
                cause=SideEffectAttemptCause.INITIAL,
                outcome=SideEffectAttemptOutcome.TIMED_OUT,
                delivery_id="delivery-none",
            ),
        ),
    )
    acknowledgement = TargetEffectAcknowledgement.create(
        target_system_identity="target",
        operation_identity="a" * 64,
        effect_sha256="c" * 64,
        acknowledgement_id="ack-boundary",
        verification_key_sha256="d" * 64,
        algorithm="ed25519",
        cryptographically_verified=True,
        observed_at_unix_ms=100,
    )
    with pytest.raises(ValueError, match="exactly one committed"):
        verify_target_acknowledgement(
            receipt=no_commit,
            acknowledgement=acknowledgement,
        )

    tampered = acknowledgement.model_dump(mode="json")
    tampered["acknowledgement_root"] = "0" * 64
    with pytest.raises(ValidationError, match="root mismatch"):
        TargetEffectAcknowledgement.model_validate(tampered)


@pytest.mark.parametrize(
    ("module", "message"),
    (
        (hitl, "HITL assurance material"),
        (memory, "memory assurance material"),
        (retrieval_production, "retrieval pipeline material"),
        (chaos, "chaos assurance material"),
        (distributed, "side-effect assurance material"),
    ),
)
def test_assurance_canonical_json_helpers_reject_non_finite_material(
    module: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        module._canonical_json_bytes({"value": float("nan")})  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("require_exact", "expected"),
    (
        (hitl._require_exact, HITLResumeCheckpoint),
        (memory._require_exact, MemoryAssurancePolicy),
        (retrieval_production._require_exact, RetrievalPipelinePolicy),
        (chaos._require_exact, ChaosPolicy),
        (distributed._require_exact, DistributedSideEffectPolicy),
    ),
)
def test_assurance_exact_type_helpers_reject_untrusted_substitutes(
    require_exact: object,
    expected: type[object],
) -> None:
    with pytest.raises(ValueError, match="requires exact"):
        require_exact(object(), expected, "boundary")  # type: ignore[operator]


def test_remaining_assurance_receipts_reject_tampered_derived_fields() -> None:
    chaos_receipt = ChaosAssuranceReceipt.create(
        policy=ChaosPolicy(required_domains=frozenset({ChaosDomain.CLOCK})),
        observations=(_chaos_observation(),),
    )
    chaos_tampered = chaos_receipt.model_dump(mode="json")
    chaos_tampered["qualification_complete"] = False
    with pytest.raises(ValidationError, match="metrics do not recompute"):
        ChaosAssuranceReceipt.model_validate(chaos_tampered)

    retrieval_receipt = RetrievalPipelineReceipt.create(
        policy=_retrieval_policy(
            require_query_rewrite=False,
            require_reranker=False,
            require_citations=False,
        ),
        documents=(_document(),),
        query_sha256="a" * 64,
    )
    retrieval_tampered = retrieval_receipt.model_dump(mode="json")
    retrieval_tampered["accepted"] = False
    with pytest.raises(ValidationError, match="does not recompute"):
        RetrievalPipelineReceipt.model_validate(retrieval_tampered)

    side_effect_receipt = DistributedSideEffectReceipt.create(
        policy=DistributedSideEffectPolicy(
            required_causes=frozenset({SideEffectAttemptCause.INITIAL})
        ),
        attempts=(
            _side_attempt(
                attempt_id="attempt.tamper",
                cause=SideEffectAttemptCause.INITIAL,
                outcome=SideEffectAttemptOutcome.TIMED_OUT,
                delivery_id="delivery-tamper",
            ),
        ),
    )
    side_effect_tampered = side_effect_receipt.model_dump(mode="json")
    side_effect_tampered["accepted"] = not side_effect_tampered["accepted"]
    with pytest.raises(ValidationError, match="does not recompute"):
        DistributedSideEffectReceipt.model_validate(side_effect_tampered)

    checkpoint = _checkpoint()
    resume_receipt = HITLResumeReceipt.create(
        checkpoint=checkpoint,
        attempts=(
            HITLResumeAttempt(
                checkpoint_root=checkpoint.checkpoint_root,
                resume_id="resume.tamper",
                worker_id="worker",
                outcome=HITLResumeOutcome.ABORTED,
            ),
        ),
    )
    resume_tampered = resume_receipt.model_dump(mode="json")
    resume_tampered["duplicate_rejections"] = 1
    with pytest.raises(ValidationError, match="does not recompute"):
        HITLResumeReceipt.model_validate(resume_tampered)
