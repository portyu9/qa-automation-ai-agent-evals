from __future__ import annotations

import hashlib

import pytest

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


def _attempt(
    *,
    index: int,
    cause: SideEffectAttemptCause,
    outcome: SideEffectAttemptOutcome,
) -> DistributedSideEffectAttempt:
    committed = outcome is SideEffectAttemptOutcome.COMMITTED
    return DistributedSideEffectAttempt(
        operation_identity="a" * 64,
        idempotency_key_sha256="b" * 64,
        attempt_id=f"attempt.{index}",
        worker_id=f"worker-{index}",
        delivery_id=f"delivery-{index}",
        cause=cause,
        outcome=outcome,
        transaction_id=f"tx-{index}" if committed else None,
        mutation_sha256="c" * 64 if committed else None,
        started_tick=index,
        completed_tick=index + 1,
    )


def test_distributed_side_effect_assurance_covers_retry_redelivery_crash_and_races() -> None:
    attempts = (
        _attempt(
            index=0,
            cause=SideEffectAttemptCause.INITIAL,
            outcome=SideEffectAttemptOutcome.COMMITTED,
        ),
        _attempt(
            index=1,
            cause=SideEffectAttemptCause.CONCURRENT_DUPLICATE,
            outcome=SideEffectAttemptOutcome.DUPLICATE_REJECTED,
        ),
        _attempt(
            index=2,
            cause=SideEffectAttemptCause.TIMEOUT_RETRY,
            outcome=SideEffectAttemptOutcome.DUPLICATE_REJECTED,
        ),
        _attempt(
            index=3,
            cause=SideEffectAttemptCause.CANCELLATION_RETRY,
            outcome=SideEffectAttemptOutcome.CANCELLED,
        ),
        _attempt(
            index=4,
            cause=SideEffectAttemptCause.CRASH_RECOVERY,
            outcome=SideEffectAttemptOutcome.DUPLICATE_REJECTED,
        ),
        _attempt(
            index=5,
            cause=SideEffectAttemptCause.QUEUE_REDELIVERY,
            outcome=SideEffectAttemptOutcome.DUPLICATE_REJECTED,
        ),
        _attempt(
            index=6,
            cause=SideEffectAttemptCause.MULTI_WORKER_RACE,
            outcome=SideEffectAttemptOutcome.ROLLED_BACK,
        ),
    )
    receipt = DistributedSideEffectReceipt.create(
        policy=DistributedSideEffectPolicy(),
        attempts=attempts,
    )

    assert receipt.committed_mutations == 1
    assert receipt.accepted is True
    assert set(receipt.covered_causes) == set(SideEffectAttemptCause)

    second_commit = list(attempts)
    second_commit[1] = _attempt(
        index=1,
        cause=SideEffectAttemptCause.CONCURRENT_DUPLICATE,
        outcome=SideEffectAttemptOutcome.COMMITTED,
    )
    rejected = DistributedSideEffectReceipt.create(
        policy=DistributedSideEffectPolicy(),
        attempts=tuple(second_commit),
    )
    assert rejected.committed_mutations == 2
    assert rejected.accepted is False


def test_target_system_acknowledgement_requires_external_crypto_verification_and_exact_effect() -> (
    None
):
    receipt = DistributedSideEffectReceipt.create(
        policy=DistributedSideEffectPolicy(),
        attempts=(
            _attempt(
                index=0,
                cause=SideEffectAttemptCause.INITIAL,
                outcome=SideEffectAttemptOutcome.COMMITTED,
            ),
        ),
    )
    acknowledgement = TargetEffectAcknowledgement.create(
        target_system_identity="ledger-primary",
        operation_identity="a" * 64,
        effect_sha256="c" * 64,
        acknowledgement_id="ack-7",
        verification_key_sha256=_sha("target-key"),
        algorithm="ed25519",
        cryptographically_verified=True,
        observed_at_unix_ms=1_000,
    )

    verify_target_acknowledgement(receipt=receipt, acknowledgement=acknowledgement)

    unverified = TargetEffectAcknowledgement.create(
        target_system_identity="ledger-primary",
        operation_identity="a" * 64,
        effect_sha256="c" * 64,
        acknowledgement_id="ack-8",
        verification_key_sha256=_sha("target-key"),
        algorithm="ed25519",
        cryptographically_verified=False,
        observed_at_unix_ms=1_000,
    )
    with pytest.raises(ValueError, match="external cryptographic verification"):
        verify_target_acknowledgement(receipt=receipt, acknowledgement=unverified)

    wrong_effect = TargetEffectAcknowledgement.create(
        target_system_identity="ledger-primary",
        operation_identity="a" * 64,
        effect_sha256="d" * 64,
        acknowledgement_id="ack-9",
        verification_key_sha256=_sha("target-key"),
        algorithm="ed25519",
        cryptographically_verified=True,
        observed_at_unix_ms=1_000,
    )
    with pytest.raises(ValueError, match="does not bind"):
        verify_target_acknowledgement(receipt=receipt, acknowledgement=wrong_effect)


def test_timeout_retry_can_be_the_single_successful_commit() -> None:
    attempts = (
        _attempt(
            index=0,
            cause=SideEffectAttemptCause.INITIAL,
            outcome=SideEffectAttemptOutcome.TIMED_OUT,
        ),
        _attempt(
            index=1,
            cause=SideEffectAttemptCause.TIMEOUT_RETRY,
            outcome=SideEffectAttemptOutcome.COMMITTED,
        ),
    )

    receipt = DistributedSideEffectReceipt.create(
        policy=DistributedSideEffectPolicy(
            required_causes=frozenset(
                {SideEffectAttemptCause.INITIAL, SideEffectAttemptCause.TIMEOUT_RETRY}
            )
        ),
        attempts=attempts,
    )

    assert receipt.committed_mutations == 1
    assert receipt.accepted is True
