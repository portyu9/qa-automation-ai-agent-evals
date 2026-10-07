from __future__ import annotations

import hashlib
import os
import subprocess
import sys

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


def test_unordered_side_effect_policy_is_root_stable_across_json_and_hash_seeds() -> None:
    causes = list(SideEffectAttemptCause)
    policy_a = DistributedSideEffectPolicy(required_causes=frozenset(causes))
    policy_b = DistributedSideEffectPolicy(required_causes=frozenset(reversed(causes)))
    attempts = (
        _attempt(
            index=0,
            cause=SideEffectAttemptCause.INITIAL,
            outcome=SideEffectAttemptOutcome.COMMITTED,
        ),
    )

    receipt_a = DistributedSideEffectReceipt.create(policy=policy_a, attempts=attempts)
    receipt_b = DistributedSideEffectReceipt.create(policy=policy_b, attempts=attempts)
    expected_root = "41121b3e301914ee8e1a1076e6453be72ff8e5f66921d548ab63adc505e21460"

    assert policy_a.model_dump_json() == policy_b.model_dump_json()
    assert receipt_a.receipt_root == receipt_b.receipt_root == expected_root
    round_tripped = DistributedSideEffectReceipt.model_validate_json(receipt_a.model_dump_json())
    assert round_tripped.receipt_root == expected_root

    script = """
from agent_evals.side_effect.distributed import (
    DistributedSideEffectAttempt,
    DistributedSideEffectPolicy,
    DistributedSideEffectReceipt,
    SideEffectAttemptCause,
    SideEffectAttemptOutcome,
)

attempt = DistributedSideEffectAttempt(
    operation_identity="a" * 64,
    idempotency_key_sha256="b" * 64,
    attempt_id="attempt.0",
    worker_id="worker-0",
    delivery_id="delivery-0",
    cause=SideEffectAttemptCause.INITIAL,
    outcome=SideEffectAttemptOutcome.COMMITTED,
    transaction_id="tx-0",
    mutation_sha256="c" * 64,
    started_tick=0,
    completed_tick=1,
)
receipt = DistributedSideEffectReceipt.create(
    policy=DistributedSideEffectPolicy(),
    attempts=(attempt,),
)
print(receipt.receipt_root)
"""
    roots = {
        subprocess.check_output(
            [sys.executable, "-c", script],
            env={**os.environ, "PYTHONHASHSEED": seed},
            text=True,
        ).strip()
        for seed in ("1", "2", "31337")
    }
    assert roots == {expected_root}
