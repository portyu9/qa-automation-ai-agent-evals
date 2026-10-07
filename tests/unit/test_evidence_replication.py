from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

import pytest
from pydantic import ValidationError

import agent_evals.evidence.replication as replication_module
from agent_evals.evidence.blob_store import ContentAddressedEvidenceStore, EvidenceBlobBackend
from agent_evals.evidence.models import TrialEvidence
from agent_evals.evidence.replication import (
    BackendProbeReceipt,
    EvidenceBackupSnapshot,
    EvidenceReplicationReceipt,
    ReplicaTargetReceipt,
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
    non_bool_put_call: int | None = None
    put_calls: int = 0

    def put_if_absent(self, key: str, content: bytes) -> bool:
        self.put_calls += 1
        if key in self.objects:
            return False
        if self.drop_put_call == self.put_calls:
            return True
        if self.non_bool_put_call == self.put_calls:
            return 1  # type: ignore[return-value]
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


@dataclass
class _FalseClobberBackend(_MemoryBackend):
    def put_if_absent(self, key: str, content: bytes) -> bool:
        self.put_calls += 1
        if key in self.objects:
            self.objects[key] = bytes(content)
            return False
        self.objects[key] = bytes(content)
        return True


@dataclass
class _DeleteBehaviorBackend(_MemoryBackend):
    behavior: Literal[
        "raise",
        "non_bool",
        "success_keep",
        "success_change",
        "refuse_change",
    ] = "raise"

    def delete(self, key: str) -> bool:
        if self.behavior == "raise":
            raise RuntimeError("controlled delete failure")
        if self.behavior == "non_bool":
            return 1  # type: ignore[return-value]
        if self.behavior == "success_keep":
            return True
        if self.behavior == "success_change":
            self.objects[key] += b"changed"
            return True
        if self.behavior == "refuse_change":
            self.objects[key] += b"changed"
            return False
        raise AssertionError("unexpected test behavior")


@dataclass
class _NonBytesReadBackend(_MemoryBackend):
    def get(self, key: str) -> bytes:
        if key not in self.objects:
            raise KeyError(key)
        return "not-bytes"  # type: ignore[return-value]


@dataclass
class _SecondReadMutatingBackend(_MemoryBackend):
    mutation: Literal["append", "same_length"] = "append"
    get_counts: dict[str, int] = field(default_factory=dict)

    def get(self, key: str) -> bytes:
        content = super().get(key)
        count = self.get_counts.get(key, 0) + 1
        self.get_counts[key] = count
        if count < 2:
            return content
        if self.mutation == "append":
            return content + b"x"
        return content[:-1] + bytes([content[-1] ^ 1])


class _DuplicateTargetMapping:
    def __init__(self, backend: EvidenceBlobBackend) -> None:
        self.backend = backend

    def __bool__(self) -> bool:
        return True

    def __len__(self) -> int:
        return 2

    def items(self) -> tuple[tuple[str, EvidenceBlobBackend], ...]:
        return (("duplicate", self.backend), ("duplicate", self.backend))


def test_backup_snapshot_rejects_order_and_root_tampering() -> None:
    _, store = _source("snapshot-a", "snapshot-b")
    snapshot = create_backup_snapshot(store)
    raw = snapshot.model_dump(mode="json")

    reversed_raw = dict(raw)
    reversed_raw["objects"] = list(reversed(raw["objects"]))
    with pytest.raises(ValidationError, match="sorted and unique"):
        EvidenceBackupSnapshot.model_validate(reversed_raw)

    root_raw = dict(raw)
    root_raw["snapshot_root"] = "0" * 64
    with pytest.raises(ValidationError, match="snapshot root mismatch"):
        EvidenceBackupSnapshot.model_validate(root_raw)


def test_backup_snapshot_enforces_object_count_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    _, store = _source("ceiling-a", "ceiling-b")
    monkeypatch.setattr(replication_module, "_MAX_OBJECTS", 1)

    with pytest.raises(EvidenceIntegrityError, match="object-count ceiling"):
        create_backup_snapshot(store)


def test_backend_probe_rejects_non_boolean_conflict_result() -> None:
    backend = _MemoryBackend(non_bool_put_call=2)

    with pytest.raises(EvidenceIntegrityError, match="put_if_absent must return an exact boolean"):
        probe_backend(backend, target_label="non-bool-put", challenge="probe-non-bool-put")


def test_backend_probe_rejects_false_no_clobber_that_changes_bytes() -> None:
    backend = _FalseClobberBackend()

    with pytest.raises(EvidenceIntegrityError, match="changed existing bytes"):
        probe_backend(backend, target_label="false-clobber", challenge="probe-false-clobber")


@pytest.mark.parametrize(
    ("behavior", "message"),
    (
        ("raise", "deletion probe failed"),
        ("non_bool", "delete must return an exact boolean"),
        ("success_keep", "reported success but the exact sentinel remains readable"),
        ("success_change", "reported success but changed sentinel bytes remain readable"),
        ("refuse_change", "refused deletion but exact sentinel bytes were not preserved"),
    ),
)
def test_backend_probe_rejects_ambiguous_or_contradictory_deletion_behavior(
    behavior: str,
    message: str,
) -> None:
    backend = _DeleteBehaviorBackend(behavior=behavior)  # type: ignore[arg-type]

    with pytest.raises(EvidenceIntegrityError, match=message):
        probe_backend(backend, target_label="delete-check", challenge=f"delete-{behavior}")


def test_backend_probe_rejects_non_bytes_readback() -> None:
    backend = _NonBytesReadBackend()

    with pytest.raises(EvidenceIntegrityError, match="backend read must return exact bytes"):
        probe_backend(backend, target_label="non-bytes", challenge="probe-non-bytes")


def test_replica_target_receipt_binds_probe_label_and_detects_root_tampering() -> None:
    _, source = _source("target-receipt")
    snapshot = create_backup_snapshot(source)
    probe = probe_backend(_MemoryBackend(), target_label="target-a", challenge="probe-target-a")

    with pytest.raises(ValueError, match="does not match backend probe label"):
        ReplicaTargetReceipt.create(
            target_label="target-b",
            snapshot=snapshot,
            probe=probe,
        )

    receipt = replicate_backup(
        source,
        {"target-a": _MemoryBackend()},
        challenge="target-receipt",
    ).targets[0]
    raw = receipt.model_dump(mode="json")
    raw["receipt_root"] = "0" * 64
    with pytest.raises(ValidationError, match="replica target receipt root mismatch"):
        ReplicaTargetReceipt.model_validate(raw)


def test_replication_receipt_rejects_order_threshold_worm_and_root_tampering() -> None:
    _, source = _source("overall-receipt")
    receipt = replicate_backup(
        source,
        {"target-a": _MemoryBackend(), "target-b": _MemoryBackend()},
        challenge="overall-receipt",
        minimum_verified_targets=2,
    )
    raw = receipt.model_dump(mode="json")

    reversed_raw = dict(raw)
    reversed_raw["targets"] = list(reversed(raw["targets"]))
    with pytest.raises(ValidationError, match="sorted and unique"):
        EvidenceReplicationReceipt.model_validate(reversed_raw)

    threshold_raw = dict(raw)
    threshold_raw["minimum_verified_targets"] = 3
    with pytest.raises(ValidationError, match="below the required replication threshold"):
        EvidenceReplicationReceipt.model_validate(threshold_raw)

    worm_raw = dict(raw)
    worm_raw["require_worm"] = True
    with pytest.raises(ValidationError, match="without observed resistance"):
        EvidenceReplicationReceipt.model_validate(worm_raw)

    root_raw = dict(raw)
    root_raw["receipt_root"] = "0" * 64
    with pytest.raises(ValidationError, match="replication receipt root mismatch"):
        EvidenceReplicationReceipt.model_validate(root_raw)


@pytest.mark.parametrize("minimum", (True, 0, 65))
def test_replication_rejects_invalid_exact_target_threshold(minimum: object) -> None:
    _, source = _source("invalid-threshold")

    with pytest.raises(ValueError, match="exact integer from 1 through 64"):
        replicate_backup(
            source,
            {"target": _MemoryBackend()},
            challenge="invalid-threshold",
            minimum_verified_targets=minimum,  # type: ignore[arg-type]
        )


def test_replication_rejects_non_boolean_worm_policy() -> None:
    _, source = _source("invalid-worm")

    with pytest.raises(ValueError, match="require_worm must be an exact boolean"):
        replicate_backup(
            source,
            {"target": _MemoryBackend()},
            challenge="invalid-worm",
            require_worm=1,  # type: ignore[arg-type]
        )


def test_replication_rejects_empty_or_excessive_target_sets_before_probe() -> None:
    _, source = _source("target-count")

    with pytest.raises(ValueError, match="at least one target"):
        replicate_backup(source, {}, challenge="empty-targets")

    targets = {f"target-{index}": _MemoryBackend() for index in range(65)}
    with pytest.raises(ValueError, match="target count exceeds"):
        replicate_backup(source, targets, challenge="too-many-targets")
    assert all(target.put_calls == 0 for target in targets.values())


def test_replication_rejects_duplicate_items_from_adversarial_mapping() -> None:
    _, source = _source("duplicate-targets")
    target = _MemoryBackend()

    with pytest.raises(ValueError, match="target labels must be unique"):
        replicate_backup(
            source,
            _DuplicateTargetMapping(target),  # type: ignore[arg-type]
            challenge="duplicate-targets",
        )
    assert target.put_calls == 0


@pytest.mark.parametrize("label", ("", "-leading", "space target", "é"))
def test_replication_rejects_invalid_target_labels_before_snapshot(label: str) -> None:
    _, source = _source("invalid-label")
    target = _MemoryBackend()

    with pytest.raises(ValueError, match="replication target label"):
        replicate_backup(source, {label: target}, challenge="invalid-label")
    assert target.put_calls == 0


@pytest.mark.parametrize(
    ("challenge", "message"),
    (
        ("", "must be non-empty"),
        ("\ud800", "valid UTF-8 text"),
        ("x" * 513, "at most 512 UTF-8 bytes"),
    ),
)
def test_replication_rejects_invalid_probe_challenge_before_snapshot(
    challenge: str,
    message: str,
) -> None:
    _, source = _source("invalid-challenge")
    target = _MemoryBackend()

    with pytest.raises(ValueError, match=message):
        replicate_backup(source, {"target": target}, challenge=challenge)
    assert target.put_calls == 0


@pytest.mark.parametrize("mutation", ("append", "same_length"))
def test_replication_rejects_source_change_after_snapshot(mutation: str) -> None:
    backend = _SecondReadMutatingBackend(mutation=mutation)  # type: ignore[arg-type]
    source = ContentAddressedEvidenceStore(backend, compression="none")
    source.write(_evidence(f"source-{mutation}"))

    expected = "length changed" if mutation == "append" else "source envelope changed"
    with pytest.raises(EvidenceIntegrityError, match=expected):
        replicate_backup(
            source,
            {"target": _MemoryBackend()},
            challenge=f"source-{mutation}",
        )


def test_replication_rejects_non_boolean_target_put_result() -> None:
    _, source = _source("target-non-bool")
    target = _MemoryBackend(non_bool_put_call=3)

    with pytest.raises(EvidenceIntegrityError, match="target put_if_absent must return"):
        replicate_backup(
            source,
            {"target": target},
            challenge="target-non-bool",
        )
