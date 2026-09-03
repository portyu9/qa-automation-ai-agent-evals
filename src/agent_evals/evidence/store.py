"""Integrity-checked local persistence for immutable trial evidence.

The local store provides deterministic identity binding, bounded reads, exclusive same-record
writers, atomic no-clobber publication, and a manifest-last commit marker. It is an integrity
mechanism, not a writer-authentication, signature, WORM, or remote-attestation mechanism.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_evals.evidence.models import TrialEvidence

_MANIFEST_SCHEMA: Literal["agent-evals-evidence-manifest/v1"] = "agent-evals-evidence-manifest/v1"
_EVIDENCE_SCHEMA: Literal["agent-evals/trial-evidence/v2"] = "agent-evals/trial-evidence/v2"
_RECORD_KEY_RE = re.compile(r"^[0-9a-f]{64}$")


class EvidenceStoreError(RuntimeError):
    """Base class for local evidence-store failures."""


class EvidenceIntegrityError(EvidenceStoreError):
    """Persisted bytes, identity, type, or structure failed verification."""


class EvidenceConflictError(EvidenceStoreError):
    """The immutable record identity already exists with different evidence."""


class IncompleteEvidenceRecordError(EvidenceStoreError):
    """Only part of a committed evidence record exists."""


class EvidenceStoreBusyError(EvidenceStoreError):
    """Another writer, or a stale fail-closed lock, owns the record key."""


class EvidenceStoreResourceError(EvidenceStoreError):
    """A persisted object exceeds the configured local resource ceiling."""


class ArtifactManifest(BaseModel):
    """Commit marker binding one immutable payload to its evaluation identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals-evidence-manifest/v1"] = _MANIFEST_SCHEMA
    evidence_schema: Literal["agent-evals/trial-evidence/v2"] = _EVIDENCE_SCHEMA
    record_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    trial_id: str = Field(min_length=1)
    subject_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    payload_bytes: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class StoredEvidence:
    manifest: ArtifactManifest
    evidence: TrialEvidence


def evidence_record_key(evidence: TrialEvidence) -> str:
    """Derive a path-safe immutable key without embedding operator-controlled trial text."""
    return _record_key(
        trial_id=evidence.trial_id,
        subject_identity=evidence.subject_identity,
        scenario_identity=evidence.scenario_identity,
    )


class LocalEvidenceStore:
    """Persist and verify immutable local evidence records.

    A record is committed only when both payload and manifest exist and the manifest verifies the
    payload. The manifest is materialized last. Crashed writers leave either no record, an explicit
    incomplete record, or a stale lock; none are silently promoted to valid evidence.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        max_payload_bytes: int = 8 * 1024 * 1024,
        max_manifest_bytes: int = 64 * 1024,
    ) -> None:
        if max_payload_bytes < 1 or max_manifest_bytes < 1:
            raise ValueError("evidence-store byte ceilings must be positive")
        self._root = Path(root)
        self._max_payload_bytes = max_payload_bytes
        self._max_manifest_bytes = max_manifest_bytes
        self._records = self._root / "records"
        _ensure_store_directory(self._root)
        _ensure_store_directory(self._records)

    @property
    def root(self) -> Path:
        return self._root

    def write(self, evidence: TrialEvidence) -> ArtifactManifest:
        payload = _canonical_json_bytes(evidence.model_dump(mode="json"))
        if len(payload) > self._max_payload_bytes:
            raise EvidenceStoreResourceError(
                f"evidence payload is {len(payload)} bytes; maximum is {self._max_payload_bytes}"
            )

        key = evidence_record_key(evidence)
        paths = self._paths(key, create_bucket=True)
        lock_fd = self._acquire_lock(paths.lock)
        try:
            presence = self._presence(paths)
            if presence == "complete":
                existing = self.read(key)
                proposed_hash = hashlib.sha256(payload).hexdigest()
                if (
                    existing.manifest.payload_sha256 == proposed_hash
                    and existing.manifest.evidence_root == evidence.evidence_root
                    and existing.evidence == evidence
                ):
                    return existing.manifest
                raise EvidenceConflictError(
                    f"record key {key} already exists with different immutable evidence"
                )
            if presence == "partial":
                raise IncompleteEvidenceRecordError(
                    f"record key {key} is incomplete; refusing automatic overwrite or repair"
                )

            payload_hash = hashlib.sha256(payload).hexdigest()
            manifest = ArtifactManifest(
                record_key=key,
                trial_id=evidence.trial_id,
                subject_identity=evidence.subject_identity,
                scenario_identity=evidence.scenario_identity,
                evidence_root=evidence.evidence_root,
                payload_sha256=payload_hash,
                payload_bytes=len(payload),
            )
            manifest_bytes = _canonical_json_bytes(manifest.model_dump(mode="json"))
            if len(manifest_bytes) > self._max_manifest_bytes:
                raise EvidenceStoreResourceError(
                    f"evidence manifest is {len(manifest_bytes)} bytes; maximum is {self._max_manifest_bytes}"
                )

            _atomic_materialize(paths.payload, payload)
            _atomic_materialize(paths.manifest, manifest_bytes)
            return manifest
        finally:
            os.close(lock_fd)
            with suppress(FileNotFoundError):
                paths.lock.unlink()

    def read(self, record_key: str) -> StoredEvidence:
        _validate_record_key(record_key)
        paths = self._paths(record_key, create_bucket=False)
        if self._presence(paths) != "complete":
            raise IncompleteEvidenceRecordError(
                f"record key {record_key} does not have both payload and manifest"
            )

        manifest_bytes = _safe_read_regular_file(paths.manifest, self._max_manifest_bytes)
        payload = _safe_read_regular_file(paths.payload, self._max_payload_bytes)

        try:
            manifest = ArtifactManifest.model_validate_json(manifest_bytes)
        except ValidationError as exc:
            raise EvidenceIntegrityError("evidence manifest failed schema validation") from exc

        if manifest.record_key != record_key:
            raise EvidenceIntegrityError("manifest record key does not match requested record")
        expected_key = _record_key(
            trial_id=manifest.trial_id,
            subject_identity=manifest.subject_identity,
            scenario_identity=manifest.scenario_identity,
        )
        if expected_key != record_key:
            raise EvidenceIntegrityError(
                "manifest identity does not derive the requested record key"
            )
        if manifest.payload_bytes != len(payload):
            raise EvidenceIntegrityError("manifest payload length does not match stored bytes")
        if manifest.payload_sha256 != hashlib.sha256(payload).hexdigest():
            raise EvidenceIntegrityError("stored evidence payload hash does not match manifest")

        try:
            evidence = TrialEvidence.model_validate_json(payload)
        except ValidationError as exc:
            raise EvidenceIntegrityError(
                "stored evidence payload failed schema validation"
            ) from exc

        if (
            evidence.trial_id != manifest.trial_id
            or evidence.subject_identity != manifest.subject_identity
            or evidence.scenario_identity != manifest.scenario_identity
        ):
            raise EvidenceIntegrityError("stored evidence identity does not match manifest")
        if evidence.evidence_root != manifest.evidence_root:
            raise EvidenceIntegrityError("stored evidence root does not match manifest")
        return StoredEvidence(manifest=manifest, evidence=evidence)

    def _paths(self, record_key: str, *, create_bucket: bool) -> _RecordPaths:
        _validate_record_key(record_key)
        bucket = self._records / record_key[:2]
        if create_bucket:
            _ensure_store_directory(bucket)
        elif bucket.is_symlink():
            raise EvidenceIntegrityError("evidence record bucket cannot be a symlink")
        return _RecordPaths(
            payload=bucket / f"{record_key}.evidence.json",
            manifest=bucket / f"{record_key}.manifest.json",
            lock=bucket / f"{record_key}.lock",
        )

    @staticmethod
    def _presence(paths: _RecordPaths) -> str:
        payload = paths.payload.exists() or paths.payload.is_symlink()
        manifest = paths.manifest.exists() or paths.manifest.is_symlink()
        if payload and manifest:
            return "complete"
        if payload or manifest:
            return "partial"
        return "absent"

    @staticmethod
    def _acquire_lock(path: Path) -> int:
        try:
            return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise EvidenceStoreBusyError(
                f"record lock already exists: {path.name}; stale locks require explicit operator review"
            ) from exc


@dataclass(frozen=True, slots=True)
class _RecordPaths:
    payload: Path
    manifest: Path
    lock: Path


def _record_key(*, trial_id: str, subject_identity: str, scenario_identity: str) -> str:
    material = _canonical_json_bytes(
        {
            "trial_id": trial_id,
            "subject_identity": subject_identity,
            "scenario_identity": scenario_identity,
        }
    )
    return hashlib.sha256(material).hexdigest()


def _validate_record_key(record_key: str) -> None:
    if _RECORD_KEY_RE.fullmatch(record_key) is None:
        raise EvidenceIntegrityError(
            "record key must be exactly 64 lowercase hexadecimal characters"
        )


def _ensure_store_directory(path: Path) -> None:
    if path.is_symlink():
        raise EvidenceIntegrityError(f"evidence-store directory cannot be a symlink: {path}")
    path.mkdir(parents=True, exist_ok=True)
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise EvidenceIntegrityError(f"cannot inspect evidence-store directory: {path}") from exc
    if not stat.S_ISDIR(mode):
        raise EvidenceIntegrityError(f"evidence-store path is not a directory: {path}")


def _safe_read_regular_file(path: Path, max_bytes: int) -> bytes:
    if path.is_symlink():
        raise EvidenceIntegrityError(f"evidence artifact cannot be a symlink: {path.name}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise EvidenceIntegrityError(f"cannot safely open evidence artifact: {path.name}") from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise EvidenceIntegrityError(f"evidence artifact is not a regular file: {path.name}")
        if metadata.st_size > max_bytes:
            raise EvidenceStoreResourceError(
                f"evidence artifact {path.name} is {metadata.st_size} bytes; maximum is {max_bytes}"
            )
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(fd, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        extra = os.read(fd, 1)
        data = b"".join(chunks)
        if remaining != 0 or extra or len(data) != metadata.st_size:
            raise EvidenceIntegrityError(
                f"evidence artifact changed during bounded read: {path.name}"
            )
        return data
    finally:
        os.close(fd)


def _atomic_materialize(path: Path, content: bytes) -> None:
    if path.is_symlink() or path.exists():
        raise EvidenceConflictError(f"refusing to replace existing evidence artifact: {path.name}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        offset = 0
        while offset < len(content):
            written = os.write(fd, content[offset:])
            if written <= 0:
                raise EvidenceStoreError(
                    f"short write while materializing evidence artifact: {path.name}"
                )
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = -1
        try:
            path.hardlink_to(temporary)
        except FileExistsError as exc:
            raise EvidenceConflictError(
                f"evidence artifact appeared during publication: {path.name}"
            ) from exc
        except OSError as exc:
            raise EvidenceStoreError(
                f"cannot atomically publish evidence artifact without clobbering: {path.name}"
            ) from exc
        _fsync_directory(path.parent)
        temporary.unlink()
        _fsync_directory(path.parent)
    finally:
        if fd >= 0:
            os.close(fd)
        with suppress(FileNotFoundError):
            temporary.unlink()


def _fsync_directory(path: Path) -> None:
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if not directory_flag:
        return
    try:
        fd = os.open(path, os.O_RDONLY | directory_flag)
    except OSError as exc:
        raise EvidenceStoreError(
            f"cannot open evidence directory for durability sync: {path}"
        ) from exc
    try:
        os.fsync(fd)
    except OSError as exc:
        raise EvidenceStoreError(f"cannot durability-sync evidence directory: {path}") from exc
    finally:
        os.close(fd)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
