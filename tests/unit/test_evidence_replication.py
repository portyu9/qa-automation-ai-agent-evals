from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

import pytest
from pydantic import ValidationError

from agent_evals.evidence.blob_store import ContentAddressedEvidenceStore, EvidenceBlobBackend
from agent_evals.evidence.models import TrialEvidence
from agent_evals.evidence.replication import (
    BackendProbeReceipt,
    EvidenceBackupSnapshot,
    EvidenceReplicationReceipt,
    create_backup_snapshot,
    probe_backend,
    replicate_backup,
)
from agent_evals.evidence.store import EvidenceConflictError, EvidenceIntegrityError

SUBJECT = "a" * 64
SCENARIO = "b" * 64


def _evidence(trial_id: str) -> TrialEvidence:
    return TrialEvidence(
        trial_id=trial_id,
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        final_state={"trial": trial_id, "status": "verified"},
    )


@dataclass
class _MemoryBackend(EvidenceBlobBackend):
    objects: dict[str, bytes] = field(default_factory=dict)
    deletion_resistant: bool = False
    advertised_worm: bool = False
    corrupt_put_call: int | None = None
    drop_put_call: int | None = None
    put_calls: int = 0

    def put_if_absent(self, key: str, content: bytes) -> bool:
        self.put_calls += 1
        if key in self.objects:
            return False
        if self.drop_put_call == self.put_calls:
            return True
        stored = bytes(content)
        if self.corrupt_put_call == self.put_calls:
            stored += b"controlled-corruption"
        self.objects[key] = stored
        return True

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def list_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.objects))

    def delete(self, key: str) -> bool:
        if self.deletion_resistant:
            return False
        return self.objects.pop(key, None) is not None


@dataclass
class _ClobberBackend(_MemoryBackend):
    def put_if_absent(self, key: str, content: bytes) -> bool:
        self.put_calls += 1
        self.objects[key] = bytes(content)
        return True


def _source(
    *trial_ids: str,
    compression: Literal["none", "gzip"] = "gzip",
) -> tuple[_MemoryBackend, ContentAddressedEvidenceStore]:
    backend = _MemoryBackend()
    store = ContentAddressedEvidenceStore(backend, compression=compression)
    for trial_id in trial_ids:
        store.write(_evidence(trial_id))
    return backend, store


def test_backup_snapshot_binds_sorted_exact_verified_envelopes() -> None:
    backend, store = _source("zeta", "alpha")

    snapshot = create_backup_snapshot(store)

    expected_keys = tuple(sorted(backend.objects))
    assert tuple(item.logical_sha256 for item in snapshot.objects) == expected_keys
    assert len(snapshot.objects) == 2
    for item in snapshot.objects:
        assert item.envelope_bytes == len(backend.objects[item.logical_sha256])
        assert store.read(item.logical_sha256).evidence_root == item.evidence_root

    revalidated = EvidenceBackupSnapshot.model_validate(snapshot.model_dump(mode="json"))
    assert revalidated == snapshot


def test_backup_snapshot_rejects_corrupted_source_envelope() -> None:
    backend, store = _source("corrupt-source")
    key = store.keys()[0]
    backend.objects[key] += b"tamper"

    with pytest.raises(EvidenceIntegrityError):
        create_backup_snapshot(store)


def test_backend_probe_observes_no_clobber_and_deletable_backend() -> None:
    backend = _MemoryBackend(advertised_worm=True)

    receipt = probe_backend(
        backend,
        target_label="replica-a",
        challenge="probe-1",
    )

    assert receipt.read_after_write_observed is True
    assert receipt.no_clobber_observed is True
    assert receipt.deletion_resistance_observed is False
    assert backend.objects == {}
    assert receipt.target_label == "replica-a"


def test_backend_probe_credits_worm_only_from_failed_delete_and_exact_readback() -> None:
    backend = _MemoryBackend(deletion_resistant=True)

    receipt = probe_backend(
        backend,
        target_label="worm-a",
        challenge="probe-2",
    )

    assert receipt.deletion_resistance_observed is True
    assert receipt.sentinel_sha256 in backend.objects
    assert (
        receipt.sentinel_envelope_sha256
        == hashlib.sha256(backend.objects[receipt.sentinel_sha256]).hexdigest()
    )
    assert (
        ContentAddressedEvidenceStore(backend)
        .read(receipt.sentinel_sha256)
        .final_state["backend_probe"]
        is True
    )


def test_backend_probe_rejects_no_clobber_violation() -> None:
    backend = _ClobberBackend()

    with pytest.raises(EvidenceIntegrityError, match="no-clobber"):
        probe_backend(
            backend,
            target_label="clobber",
            challenge="probe-3",
        )


def test_backend_probe_receipt_detects_tampering() -> None:
    receipt = probe_backend(
        _MemoryBackend(),
        target_label="replica-b",
        challenge="probe-4",
    )
    raw = receipt.model_dump(mode="json")
    raw["deletion_resistance_observed"] = True

    with pytest.raises(ValidationError, match="probe receipt root mismatch"):
        BackendProbeReceipt.model_validate(raw)


def test_replication_verifies_multiple_targets_and_is_idempotent() -> None:
    source_backend, source = _source("one", "two")
    left = _MemoryBackend()
    right = _MemoryBackend()
    targets: dict[str, EvidenceBlobBackend] = {
        "replica-a": left,
        "replica-b": right,
    }

    first = replicate_backup(
        source,
        targets,
        challenge="replication-1",
        minimum_verified_targets=2,
    )
    second = replicate_backup(
        source,
        targets,
        challenge="replication-1",
        minimum_verified_targets=2,
    )

    assert first == second
    assert first.minimum_verified_targets == 2
    assert tuple(item.target_label for item in first.targets) == ("replica-a", "replica-b")
    assert all(item.verified_objects == 2 for item in first.targets)
    source_keys = set(source_backend.objects)
    assert set(left.objects) == source_keys
    assert set(right.objects) == source_keys
    for key in source_keys:
        assert left.objects[key] == source_backend.objects[key]
        assert right.objects[key] == source_backend.objects[key]


def test_worm_required_replication_succeeds_only_with_observed_resistance() -> None:
    source_backend, source = _source("worm-copy", compression="none")
    target = _MemoryBackend(deletion_resistant=True)

    receipt = replicate_backup(
        source,
        {"archive": target},
        challenge="worm-required",
        require_worm=True,
    )

    assert receipt.require_worm is True
    assert receipt.targets[0].worm_observed is True
    for key, envelope in source_backend.objects.items():
        assert target.objects[key] == envelope


def test_worm_required_replication_fails_before_copy_on_deletable_target() -> None:
    source_backend, source = _source("do-not-copy")
    target = _MemoryBackend(advertised_worm=True)

    with pytest.raises(EvidenceIntegrityError, match="lacks observed deletion resistance"):
        replicate_backup(
            source,
            {"claimed-worm": target},
            challenge="worm-rejected",
            require_worm=True,
        )

    assert set(source_backend.objects).isdisjoint(target.objects)


def test_replication_refuses_existing_conflicting_replica_bytes() -> None:
    source_backend, source = _source("conflict")
    source_key = next(iter(source_backend.objects))
    target = _MemoryBackend(objects={source_key: b"foreign-bytes"})

    with pytest.raises(EvidenceConflictError, match="different immutable envelope"):
        replicate_backup(
            source,
            {"replica-conflict": target},
            challenge="conflict-check",
        )

    assert target.objects[source_key] == b"foreign-bytes"


def test_replication_rejects_corrupted_target_readback() -> None:
    _, source = _source("corrupt-target")
    target = _MemoryBackend(corrupt_put_call=3)

    with pytest.raises(EvidenceIntegrityError, match="readback differs"):
        replicate_backup(
            source,
            {"replica-corrupt": target},
            challenge="corrupt-check",
        )


def test_replication_rejects_missing_target_readback() -> None:
    _, source = _source("missing-target")
    target = _MemoryBackend(drop_put_call=3)

    with pytest.raises(EvidenceIntegrityError, match="replica readback backend read failed"):
        replicate_backup(
            source,
            {"replica-missing": target},
            challenge="missing-check",
        )


def test_replication_threshold_fails_before_target_probe_or_copy() -> None:
    _, source = _source("threshold")
    target = _MemoryBackend()

    with pytest.raises(ValueError, match="below the required replication threshold"):
        replicate_backup(
            source,
            {"only-one": target},
            challenge="threshold-check",
            minimum_verified_targets=2,
        )

    assert target.put_calls == 0
    assert target.objects == {}


def test_replication_receipt_detects_cross_snapshot_tampering() -> None:
    _, source = _source("receipt")
    target = _MemoryBackend()
    receipt = replicate_backup(
        source,
        {"replica": target},
        challenge="receipt-check",
    )
    raw = receipt.model_dump(mode="json")
    raw["snapshot_root"] = "0" * 64

    with pytest.raises(ValidationError):
        EvidenceReplicationReceipt.model_validate(raw)
