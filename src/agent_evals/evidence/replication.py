"""Verified backup snapshots and replication over immutable evidence blob backends.

These contracts build on ContentAddressedEvidenceStore without turning a backend into a trust
authority. Replication credit requires exact readback. Optional WORM credit requires an observed
failed deletion of a valid synthetic evidence blob followed by exact post-delete readback.

Hashes and receipts in this module establish integrity relationships only. They do not authenticate
a storage provider, prove provider-side retention policy, establish legal hold, or prove physical
immutability/durability.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.evidence.blob_store import ContentAddressedEvidenceStore, EvidenceBlobBackend
from agent_evals.evidence.models import TrialEvidence
from agent_evals.evidence.store import EvidenceConflictError, EvidenceIntegrityError

_BACKUP_SCHEMA: Literal["agent-evals/evidence-backup-snapshot/v1"] = (
    "agent-evals/evidence-backup-snapshot/v1"
)
_PROBE_SCHEMA: Literal["agent-evals/evidence-backend-probe/v1"] = (
    "agent-evals/evidence-backend-probe/v1"
)
_TARGET_SCHEMA: Literal["agent-evals/evidence-replica-target/v1"] = (
    "agent-evals/evidence-replica-target/v1"
)
_REPLICATION_SCHEMA: Literal["agent-evals/evidence-replication/v1"] = (
    "agent-evals/evidence-replication/v1"
)
_BACKUP_DOMAIN = b"agent-evals/evidence-backup-snapshot/v1\x00"
_PROBE_DOMAIN = b"agent-evals/evidence-backend-probe/v1\x00"
_TARGET_DOMAIN = b"agent-evals/evidence-replica-target/v1\x00"
_REPLICATION_DOMAIN = b"agent-evals/evidence-replication/v1\x00"
_PROBE_SUBJECT = hashlib.sha256(b"agent-evals/backend-probe/subject/v1").hexdigest()
_PROBE_SCENARIO = hashlib.sha256(b"agent-evals/backend-probe/scenario/v1").hexdigest()
_TARGET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_OBJECTS = 100_000
_MAX_TARGETS = 64


class BackupObjectRecord(BaseModel):
    """Integrity facts for one exact stored evidence envelope in a backup snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    envelope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    envelope_bytes: int = Field(ge=0, strict=True)


class EvidenceBackupSnapshot(BaseModel):
    """Canonical snapshot of exact verified source objects."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/evidence-backup-snapshot/v1"] = _BACKUP_SCHEMA
    objects: tuple[BackupObjectRecord, ...] = Field(max_length=_MAX_OBJECTS)
    snapshot_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, objects: tuple[BackupObjectRecord, ...]) -> Self:
        canonical = tuple(sorted(objects, key=lambda item: item.logical_sha256))
        return cls(objects=canonical, snapshot_root=_backup_root(canonical))

    @model_validator(mode="after")
    def verify_snapshot(self) -> Self:
        keys = tuple(item.logical_sha256 for item in self.objects)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("backup snapshot objects must be sorted and unique by logical key")
        if not hmac.compare_digest(_backup_root(self.objects), self.snapshot_root):
            raise ValueError("backup snapshot root mismatch")
        return self


class BackendProbeReceipt(BaseModel):
    """Observed backend behavior for one expendable valid evidence sentinel."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/evidence-backend-probe/v1"] = _PROBE_SCHEMA
    target_label: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    sentinel_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sentinel_envelope_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    read_after_write_observed: Literal[True] = True
    no_clobber_observed: Literal[True] = True
    deletion_resistance_observed: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        target_label: str,
        sentinel_sha256: str,
        sentinel_envelope_sha256: str,
        deletion_resistance_observed: bool,
    ) -> Self:
        material = {
            "schema_version": _PROBE_SCHEMA,
            "target_label": target_label,
            "sentinel_sha256": sentinel_sha256,
            "sentinel_envelope_sha256": sentinel_envelope_sha256,
            "read_after_write_observed": True,
            "no_clobber_observed": True,
            "deletion_resistance_observed": deletion_resistance_observed,
        }
        return cls(
            target_label=target_label,
            sentinel_sha256=sentinel_sha256,
            sentinel_envelope_sha256=sentinel_envelope_sha256,
            deletion_resistance_observed=deletion_resistance_observed,
            receipt_root=_root(_PROBE_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_receipt(self) -> Self:
        material = {
            "schema_version": self.schema_version,
            "target_label": self.target_label,
            "sentinel_sha256": self.sentinel_sha256,
            "sentinel_envelope_sha256": self.sentinel_envelope_sha256,
            "read_after_write_observed": self.read_after_write_observed,
            "no_clobber_observed": self.no_clobber_observed,
            "deletion_resistance_observed": self.deletion_resistance_observed,
        }
        if not hmac.compare_digest(_root(_PROBE_DOMAIN, material), self.receipt_root):
            raise ValueError("backend probe receipt root mismatch")
        return self


class ReplicaTargetReceipt(BaseModel):
    """Verification receipt for one explicitly named replication target."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/evidence-replica-target/v1"] = _TARGET_SCHEMA
    target_label: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
    snapshot_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    probe_receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    worm_observed: bool = Field(strict=True)
    verified_objects: int = Field(ge=0, le=_MAX_OBJECTS, strict=True)
    verified_object_set_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        target_label: str,
        snapshot: EvidenceBackupSnapshot,
        probe: BackendProbeReceipt,
    ) -> Self:
        if probe.target_label != target_label:
            raise ValueError("replica target label does not match backend probe label")
        object_set_root = _object_set_root(snapshot.objects)
        material = {
            "schema_version": _TARGET_SCHEMA,
            "target_label": target_label,
            "snapshot_root": snapshot.snapshot_root,
            "probe_receipt_root": probe.receipt_root,
            "worm_observed": probe.deletion_resistance_observed,
            "verified_objects": len(snapshot.objects),
            "verified_object_set_root": object_set_root,
        }
        return cls(
            target_label=target_label,
            snapshot_root=snapshot.snapshot_root,
            probe_receipt_root=probe.receipt_root,
            worm_observed=probe.deletion_resistance_observed,
            verified_objects=len(snapshot.objects),
            verified_object_set_root=object_set_root,
            receipt_root=_root(_TARGET_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_receipt(self) -> Self:
        material = {
            "schema_version": self.schema_version,
            "target_label": self.target_label,
            "snapshot_root": self.snapshot_root,
            "probe_receipt_root": self.probe_receipt_root,
            "worm_observed": self.worm_observed,
            "verified_objects": self.verified_objects,
            "verified_object_set_root": self.verified_object_set_root,
        }
        if not hmac.compare_digest(_root(_TARGET_DOMAIN, material), self.receipt_root):
            raise ValueError("replica target receipt root mismatch")
        return self


class EvidenceReplicationReceipt(BaseModel):
    """Integrity-bound result for a fully verified replication operation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/evidence-replication/v1"] = _REPLICATION_SCHEMA
    snapshot_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    require_worm: bool = Field(strict=True)
    minimum_verified_targets: int = Field(ge=1, le=_MAX_TARGETS, strict=True)
    targets: tuple[ReplicaTargetReceipt, ...] = Field(min_length=1, max_length=_MAX_TARGETS)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        snapshot: EvidenceBackupSnapshot,
        require_worm: bool,
        minimum_verified_targets: int,
        targets: tuple[ReplicaTargetReceipt, ...],
    ) -> Self:
        canonical = tuple(sorted(targets, key=lambda item: item.target_label))
        material = {
            "schema_version": _REPLICATION_SCHEMA,
            "snapshot_root": snapshot.snapshot_root,
            "require_worm": require_worm,
            "minimum_verified_targets": minimum_verified_targets,
            "targets": [item.model_dump(mode="json") for item in canonical],
        }
        return cls(
            snapshot_root=snapshot.snapshot_root,
            require_worm=require_worm,
            minimum_verified_targets=minimum_verified_targets,
            targets=canonical,
            receipt_root=_root(_REPLICATION_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_receipt(self) -> Self:
        labels = tuple(item.target_label for item in self.targets)
        if labels != tuple(sorted(set(labels))):
            raise ValueError("replication targets must be sorted and unique")
        if len(self.targets) < self.minimum_verified_targets:
            raise ValueError("verified target count is below the required replication threshold")
        if any(item.snapshot_root != self.snapshot_root for item in self.targets):
            raise ValueError("replica target receipt binds a different backup snapshot")
        if self.require_worm and any(not item.worm_observed for item in self.targets):
            raise ValueError(
                "WORM-required replication contains a target without observed resistance"
            )
        material = {
            "schema_version": self.schema_version,
            "snapshot_root": self.snapshot_root,
            "require_worm": self.require_worm,
            "minimum_verified_targets": self.minimum_verified_targets,
            "targets": [item.model_dump(mode="json") for item in self.targets],
        }
        if not hmac.compare_digest(_root(_REPLICATION_DOMAIN, material), self.receipt_root):
            raise ValueError("evidence replication receipt root mismatch")
        return self


def create_backup_snapshot(store: ContentAddressedEvidenceStore) -> EvidenceBackupSnapshot:
    """Bind the exact verified envelopes currently reachable from one source store."""

    keys = store.keys()
    if len(keys) > _MAX_OBJECTS:
        raise EvidenceIntegrityError("backup snapshot exceeds configured object-count ceiling")
    records: list[BackupObjectRecord] = []
    for key in keys:
        envelope = _backend_get(store.backend, key, operation="backup source")
        evidence = _verify_exact_envelope(
            key,
            envelope,
            max_logical_bytes=store.max_logical_bytes,
        )
        records.append(
            BackupObjectRecord(
                logical_sha256=key,
                evidence_root=evidence.evidence_root,
                envelope_sha256=hashlib.sha256(envelope).hexdigest(),
                envelope_bytes=len(envelope),
            )
        )
    return EvidenceBackupSnapshot.create(tuple(records))


def probe_backend(
    backend: EvidenceBlobBackend,
    *,
    target_label: str,
    challenge: str,
) -> BackendProbeReceipt:
    """Observe read-after-write, no-clobber, and optional deletion resistance.

    A backend receives WORM credit only when delete() explicitly returns False while the exact
    sentinel remains readable. Exceptions, timeouts, capability flags, or backend metadata never
    count as deletion-resistance evidence.
    """

    _validate_target_label(target_label)
    challenge_digest = _challenge_digest(target_label, challenge)
    sentinel = TrialEvidence(
        trial_id=f"backend-probe:{challenge_digest[:24]}",
        subject_identity=_PROBE_SUBJECT,
        scenario_identity=_PROBE_SCENARIO,
        final_state={"backend_probe": True, "challenge_sha256": challenge_digest},
    )
    probe_store = ContentAddressedEvidenceStore(backend, compression="none")
    manifest = probe_store.write(sentinel)
    key = manifest.logical_sha256
    envelope = _backend_get(backend, key, operation="backend probe")
    verified = _verify_exact_envelope(
        key,
        envelope,
        max_logical_bytes=probe_store.max_logical_bytes,
    )
    if verified != sentinel.snapshot():
        raise EvidenceIntegrityError("backend probe read-after-write changed sentinel evidence")

    conflicting = envelope + b"\nagent-evals-backend-probe-conflict"
    created_conflict = backend.put_if_absent(key, conflicting)
    if type(created_conflict) is not bool:
        raise EvidenceIntegrityError("backend put_if_absent must return an exact boolean")
    if created_conflict:
        raise EvidenceIntegrityError("backend violated no-clobber semantics for an existing key")
    if _backend_get(backend, key, operation="no-clobber probe") != envelope:
        raise EvidenceIntegrityError("backend changed existing bytes during no-clobber probe")

    try:
        deleted = backend.delete(key)
    except Exception as exc:
        raise EvidenceIntegrityError("backend deletion probe failed without an observation") from exc
    if type(deleted) is not bool:
        raise EvidenceIntegrityError("backend delete must return an exact boolean")
    if deleted:
        try:
            remaining = backend.get(key)
        except Exception:
            deletion_resistant = False
        else:
            if remaining == envelope:
                raise EvidenceIntegrityError(
                    "backend delete reported success but the exact sentinel remains readable"
                )
            raise EvidenceIntegrityError(
                "backend delete reported success but changed sentinel bytes remain readable"
            )
    else:
        remaining = _backend_get(
            backend,
            key,
            operation="post-delete WORM probe",
        )
        if remaining != envelope:
            raise EvidenceIntegrityError(
                "backend refused deletion but exact sentinel bytes were not preserved"
            )
        _verify_exact_envelope(key, remaining, max_logical_bytes=probe_store.max_logical_bytes)
        deletion_resistant = True

    return BackendProbeReceipt.create(
        target_label=target_label,
        sentinel_sha256=key,
        sentinel_envelope_sha256=hashlib.sha256(envelope).hexdigest(),
        deletion_resistance_observed=deletion_resistant,
    )


def replicate_backup(
    source: ContentAddressedEvidenceStore,
    targets: Mapping[str, EvidenceBlobBackend],
    *,
    challenge: str,
    require_worm: bool = False,
    minimum_verified_targets: int = 1,
) -> EvidenceReplicationReceipt:
    """Replicate one exact source snapshot and verify every named target by readback.

    All backend probes complete before any source evidence object is copied. Therefore a WORM
    requirement that is not observed fails before evidence replication begins.
    """

    if (
        type(minimum_verified_targets) is not int
        or not 1 <= minimum_verified_targets <= _MAX_TARGETS
    ):
        raise ValueError("minimum_verified_targets must be an exact integer from 1 through 64")
    if type(require_worm) is not bool:
        raise ValueError("require_worm must be an exact boolean")
    _validate_challenge(challenge)
    if not targets:
        raise ValueError("replication requires at least one target")
    if len(targets) > _MAX_TARGETS:
        raise ValueError("replication target count exceeds configured ceiling")
    if len(targets) < minimum_verified_targets:
        raise ValueError("configured target count is below the required replication threshold")

    raw_target_items = tuple(targets.items())
    for label, _ in raw_target_items:
        _validate_target_label(label)
    target_items = tuple(sorted(raw_target_items, key=lambda item: item[0]))
    labels = tuple(label for label, _ in target_items)
    if len(set(labels)) != len(labels):
        raise ValueError("replication target labels must be unique")

    snapshot = create_backup_snapshot(source)
    probes = {
        label: probe_backend(
            backend,
            target_label=label,
            challenge=challenge,
        )
        for label, backend in target_items
    }
    if require_worm:
        missing = tuple(
            label
            for label in labels
            if not probes[label].deletion_resistance_observed
        )
        if missing:
            raise EvidenceIntegrityError(
                "WORM-required replication lacks observed deletion resistance for: "
                + ", ".join(missing)
            )

    target_receipts: list[ReplicaTargetReceipt] = []
    for label, backend in target_items:
        _replicate_snapshot_to_target(source, snapshot, backend)
        target_receipts.append(
            ReplicaTargetReceipt.create(
                target_label=label,
                snapshot=snapshot,
                probe=probes[label],
            )
        )

    return EvidenceReplicationReceipt.create(
        snapshot=snapshot,
        require_worm=require_worm,
        minimum_verified_targets=minimum_verified_targets,
        targets=tuple(target_receipts),
    )


def _replicate_snapshot_to_target(
    source: ContentAddressedEvidenceStore,
    snapshot: EvidenceBackupSnapshot,
    target: EvidenceBlobBackend,
) -> None:
    for record in snapshot.objects:
        envelope = _backend_get(
            source.backend,
            record.logical_sha256,
            operation="replication source",
        )
        if len(envelope) != record.envelope_bytes:
            raise EvidenceIntegrityError("source envelope length changed after backup snapshot")
        if not hmac.compare_digest(
            hashlib.sha256(envelope).hexdigest(),
            record.envelope_sha256,
        ):
            raise EvidenceIntegrityError("source envelope changed after backup snapshot")
        source_evidence = _verify_exact_envelope(
            record.logical_sha256,
            envelope,
            max_logical_bytes=source.max_logical_bytes,
        )
        if not hmac.compare_digest(source_evidence.evidence_root, record.evidence_root):
            raise EvidenceIntegrityError("source evidence root changed after backup snapshot")

        created = target.put_if_absent(record.logical_sha256, envelope)
        if type(created) is not bool:
            raise EvidenceIntegrityError("target put_if_absent must return an exact boolean")
        readback = _backend_get(
            target,
            record.logical_sha256,
            operation="replica readback",
        )
        if readback != envelope:
            if created:
                raise EvidenceIntegrityError("replica readback differs from copied source envelope")
            raise EvidenceConflictError(
                "replica key already exists with different immutable envelope bytes"
            )
        target_evidence = _verify_exact_envelope(
            record.logical_sha256,
            readback,
            max_logical_bytes=source.max_logical_bytes,
        )
        if not hmac.compare_digest(target_evidence.evidence_root, record.evidence_root):
            raise EvidenceIntegrityError("replica evidence root differs from backup snapshot")


@dataclass(frozen=True, slots=True)
class _ReadOnlyEnvelopeBackend:
    key: str
    envelope: bytes

    def put_if_absent(self, key: str, content: bytes) -> bool:
        del key, content
        raise RuntimeError("read-only envelope verifier cannot write")

    def get(self, key: str) -> bytes:
        if key != self.key:
            raise KeyError(key)
        return self.envelope

    def list_keys(self) -> tuple[str, ...]:
        return (self.key,)

    def delete(self, key: str) -> bool:
        del key
        raise RuntimeError("read-only envelope verifier cannot delete")


def _backend_get(
    backend: EvidenceBlobBackend,
    key: str,
    *,
    operation: str,
) -> bytes:
    try:
        content = backend.get(key)
    except Exception as exc:
        raise EvidenceIntegrityError(f"{operation} backend read failed") from exc
    if type(content) is not bytes:
        raise EvidenceIntegrityError(f"{operation} backend read must return exact bytes")
    return content


def _verify_exact_envelope(
    key: str,
    envelope: bytes,
    *,
    max_logical_bytes: int,
) -> TrialEvidence:
    backend = _ReadOnlyEnvelopeBackend(key=key, envelope=bytes(envelope))
    verifier = ContentAddressedEvidenceStore(
        backend,
        max_logical_bytes=max_logical_bytes,
    )
    return verifier.read(key)


def _validate_target_label(label: str) -> None:
    if type(label) is not str or _TARGET_RE.fullmatch(label) is None:
        raise ValueError(
            "replication target label must be 1-128 ASCII letters/digits/dot/underscore/hyphen"
        )


def _validate_challenge(challenge: str) -> None:
    if type(challenge) is not str or not challenge:
        raise ValueError("backend probe challenge must be non-empty and at most 512 UTF-8 bytes")
    try:
        encoded = challenge.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("backend probe challenge must be valid UTF-8 text") from exc
    if len(encoded) > 512:
        raise ValueError("backend probe challenge must be non-empty and at most 512 UTF-8 bytes")


def _challenge_digest(target_label: str, challenge: str) -> str:
    _validate_challenge(challenge)
    material = {
        "target_label": target_label,
        "challenge": challenge,
    }
    return hashlib.sha256(
        b"agent-evals/evidence-backend-probe-challenge/v1\x00"
        + _canonical_json_bytes(material)
    ).hexdigest()


def _backup_root(objects: tuple[BackupObjectRecord, ...]) -> str:
    material = {
        "schema_version": _BACKUP_SCHEMA,
        "objects": [item.model_dump(mode="json") for item in objects],
    }
    return _root(_BACKUP_DOMAIN, material)


def _object_set_root(objects: tuple[BackupObjectRecord, ...]) -> str:
    material = [item.model_dump(mode="json") for item in objects]
    return _root(b"agent-evals/evidence-replica-object-set/v1\x00", material)


def _root(domain: bytes, material: object) -> str:
    return hashlib.sha256(domain + _canonical_json_bytes(material)).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
