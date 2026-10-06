from __future__ import annotations

from agent_evals.memory import (
    MemoryAssurancePolicy,
    MemoryAssuranceReceipt,
    MemoryObservation,
    MemoryOperationKind,
)


def _observation(
    *,
    operation: MemoryOperationKind,
    tick: int,
    actor_tenant: str = "tenant-a",
    actor_user: str = "user-a",
    allowed: bool,
    returned: str | None = None,
    poison: bool = False,
) -> MemoryObservation:
    return MemoryObservation(
        record_id="memory-7",
        owner_tenant_id="tenant-a",
        owner_user_id="user-a",
        actor_tenant_id=actor_tenant,
        actor_user_id=actor_user,
        operation=operation,
        tick=tick,
        created_tick=0,
        expires_tick=10,
        content_sha256="a" * 64,
        allowed=allowed,
        returned_content_sha256=returned,
        poison_marker=poison,
    )


def test_memory_assurance_covers_persistence_isolation_delete_ttl_and_poisoning() -> None:
    observations = (
        _observation(operation=MemoryOperationKind.WRITE, tick=0, allowed=True),
        _observation(
            operation=MemoryOperationKind.READ,
            tick=1,
            allowed=True,
            returned="a" * 64,
        ),
        _observation(
            operation=MemoryOperationKind.READ,
            tick=2,
            actor_tenant="tenant-a",
            actor_user="user-b",
            allowed=False,
        ),
        _observation(
            operation=MemoryOperationKind.POISON_ATTEMPT,
            tick=3,
            actor_tenant="tenant-a",
            actor_user="user-b",
            allowed=False,
            poison=True,
        ),
        _observation(operation=MemoryOperationKind.DELETE, tick=4, allowed=True),
        _observation(operation=MemoryOperationKind.READ, tick=5, allowed=False),
        _observation(operation=MemoryOperationKind.EXPIRE, tick=10, allowed=True),
        _observation(operation=MemoryOperationKind.READ, tick=10, allowed=False),
    )

    receipt = MemoryAssuranceReceipt.create(
        policy=MemoryAssurancePolicy(),
        observations=observations,
    )

    assert receipt.persistence_observed is True
    assert receipt.cross_user_isolation_observed is True
    assert receipt.deletion_enforced is True
    assert receipt.ttl_enforced is True
    assert receipt.poison_rejected is True
    assert receipt.accepted is True


def test_memory_receipt_rejects_cross_user_leakage_as_incomplete_assurance() -> None:
    observations = (
        _observation(operation=MemoryOperationKind.WRITE, tick=0, allowed=True),
        _observation(
            operation=MemoryOperationKind.READ,
            tick=1,
            allowed=True,
            returned="a" * 64,
        ),
        _observation(
            operation=MemoryOperationKind.READ,
            tick=2,
            actor_user="user-b",
            allowed=True,
            returned="a" * 64,
        ),
    )
    receipt = MemoryAssuranceReceipt.create(
        policy=MemoryAssurancePolicy(
            require_delete_enforcement=False,
            require_ttl_enforcement=False,
            require_poison_rejection=False,
        ),
        observations=observations,
    )

    assert receipt.cross_user_isolation_observed is False
    assert receipt.accepted is False
