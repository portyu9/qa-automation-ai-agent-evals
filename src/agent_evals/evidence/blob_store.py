"""Content-addressed immutable evidence blobs over a no-clobber backend.

Identity is SHA-256 over canonical uncompressed TrialEvidence bytes. Compression is storage-only.
Backends must never overwrite an existing key. Hashes provide integrity, not authentication.
"""

from __future__ import annotations

import gzip
import hashlib
import hmac
import io
import json
import os
import re
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from agent_evals._strict_json import StrictJsonError, strict_json_loads
from agent_evals.evidence.minimization import (
    EvidenceMinimizationPolicy,
    EvidenceMinimizationReceipt,
    minimize_evidence_for_persistence,
)
from agent_evals.evidence.models import TrialEvidence
from agent_evals.evidence.store import EvidenceConflictError, EvidenceIntegrityError

_SCHEMA: Literal["agent-evals/evidence-blob/v1"] = "agent-evals/evidence-blob/v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class EvidenceBlobBackend(Protocol):
    def put_if_absent(self, key: str, content: bytes) -> bool: ...
    def get(self, key: str) -> bytes: ...
    def list_keys(self) -> tuple[str, ...]: ...
    def delete(self, key: str) -> bool: ...


class EvidenceBlobManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/evidence-blob/v1"] = _SCHEMA
    logical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    logical_bytes: int = Field(ge=0, strict=True)
    stored_bytes: int = Field(ge=0, strict=True)
    compression: Literal["none", "gzip"]


class FilesystemBlobBackend:
    """Filesystem implementation of the same immutable contract expected from remote stores."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        if self._root.is_symlink():
            raise EvidenceIntegrityError("blob backend root cannot be a symlink")
        self._root.mkdir(mode=0o700, parents=True, exist_ok=True)

    def put_if_absent(self, key: str, content: bytes) -> bool:
        path = self._path(key)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return False
        try:
            offset = 0
            while offset < len(content):
                written = os.write(fd, content[offset:])
                if written <= 0:
                    raise EvidenceIntegrityError("short write in immutable blob backend")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)
        return True

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if path.is_symlink():
            raise EvidenceIntegrityError("blob object cannot be a symlink")
        try:
            return path.read_bytes()
        except OSError as exc:
            raise EvidenceIntegrityError(f"cannot read immutable blob {key}") from exc

    def list_keys(self) -> tuple[str, ...]:
        keys: list[str] = []
        for path in self._root.iterdir():
            if path.is_symlink() or not path.is_file():
                raise EvidenceIntegrityError("blob backend contains a non-regular entry")
            validate_blob_key(path.name)
            keys.append(path.name)
        return tuple(sorted(keys))

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if path.is_symlink():
            raise EvidenceIntegrityError("blob object cannot be a symlink")
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        return True

    def _path(self, key: str) -> Path:
        validate_blob_key(key)
        return self._root / key


class ContentAddressedEvidenceStore:
    """Integrity-checking evidence store over any immutable object backend."""

    def __init__(
        self,
        backend: EvidenceBlobBackend,
        *,
        compression: Literal["none", "gzip"] = "none",
        max_logical_bytes: int = 8 * 1024 * 1024,
        minimization_policy: EvidenceMinimizationPolicy | None = None,
    ) -> None:
        if compression not in ("none", "gzip"):
            raise ValueError("unsupported evidence blob compression")
        if type(max_logical_bytes) is not int or max_logical_bytes <= 0:
            raise ValueError("max_logical_bytes must be a positive exact integer")
        self.backend = backend
        self.compression = compression
        self.max_logical_bytes = max_logical_bytes
        self.minimization_policy = minimization_policy or EvidenceMinimizationPolicy()
        if type(self.minimization_policy) is not EvidenceMinimizationPolicy:
            raise TypeError("minimization_policy must be an exact EvidenceMinimizationPolicy")

    def write(self, evidence: TrialEvidence) -> EvidenceBlobManifest:
        manifest, _ = self.write_with_receipt(evidence)
        return manifest

    def write_with_receipt(
        self,
        evidence: TrialEvidence,
    ) -> tuple[EvidenceBlobManifest, EvidenceMinimizationReceipt]:
        prepared = minimize_evidence_for_persistence(
            evidence,
            policy=self.minimization_policy,
        )
        return self._write_prepared(prepared.evidence), prepared.receipt

    def _write_prepared(self, evidence: TrialEvidence) -> EvidenceBlobManifest:
        evidence = evidence.snapshot()
        logical = canonical_evidence_bytes(evidence)
        if len(logical) > self.max_logical_bytes:
            raise EvidenceIntegrityError("logical evidence exceeds configured blob ceiling")
        digest = hashlib.sha256(logical).hexdigest()
        stored = logical if self.compression == "none" else gzip.compress(logical, mtime=0)
        manifest = EvidenceBlobManifest(
            logical_sha256=digest,
            evidence_root=evidence.evidence_root,
            logical_bytes=len(logical),
            stored_bytes=len(stored),
            compression=self.compression,
        )
        created = self.backend.put_if_absent(digest, encode_envelope(manifest, stored))
        if created:
            return manifest
        existing = self.read(digest)
        if existing != evidence:
            raise EvidenceConflictError("content-addressed key contains different evidence")
        return self.manifest(digest)

    def read(self, logical_sha256: str) -> TrialEvidence:
        manifest, logical = self._decode(logical_sha256)
        try:
            raw = strict_json_loads(
                logical, label="content-addressed evidence", require_object=True
            )
            evidence = TrialEvidence.model_validate(raw)
        except (StrictJsonError, ValueError) as exc:
            raise EvidenceIntegrityError("content-addressed evidence failed validation") from exc
        if not hmac.compare_digest(evidence.evidence_root, manifest.evidence_root):
            raise EvidenceIntegrityError("content-addressed evidence root mismatch")
        return evidence

    def manifest(self, logical_sha256: str) -> EvidenceBlobManifest:
        manifest, _ = self._decode(logical_sha256)
        return manifest

    def keys(self) -> tuple[str, ...]:
        keys = self.backend.list_keys()
        for key in keys:
            validate_blob_key(key)
        return tuple(sorted(keys))

    def _decode(self, logical_sha256: str) -> tuple[EvidenceBlobManifest, bytes]:
        validate_blob_key(logical_sha256)
        manifest, stored = decode_envelope(self.backend.get(logical_sha256))
        if not hmac.compare_digest(manifest.logical_sha256, logical_sha256):
            raise EvidenceIntegrityError("blob manifest does not match requested content key")
        if manifest.stored_bytes != len(stored):
            raise EvidenceIntegrityError("blob stored length does not match manifest")
        if manifest.logical_bytes > self.max_logical_bytes:
            raise EvidenceIntegrityError("blob logical length exceeds configured ceiling")
        logical = (
            stored
            if manifest.compression == "none"
            else gunzip_bounded(stored, self.max_logical_bytes)
        )
        if len(logical) != manifest.logical_bytes:
            raise EvidenceIntegrityError("blob logical length does not match manifest")
        actual = hashlib.sha256(logical).hexdigest()
        if not hmac.compare_digest(actual, logical_sha256):
            raise EvidenceIntegrityError("blob logical content hash mismatch")
        return manifest, logical


def canonical_evidence_bytes(evidence: TrialEvidence) -> bytes:
    return json.dumps(
        evidence.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def encode_envelope(manifest: EvidenceBlobManifest, stored: bytes) -> bytes:
    header = json.dumps(
        manifest.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return header + b"\n" + stored


def decode_envelope(envelope: bytes) -> tuple[EvidenceBlobManifest, bytes]:
    try:
        header, stored = envelope.split(b"\n", 1)
        raw = strict_json_loads(header, label="evidence blob manifest", require_object=True)
        manifest = EvidenceBlobManifest.model_validate(raw)
    except (ValueError, StrictJsonError) as exc:
        raise EvidenceIntegrityError("evidence blob envelope failed validation") from exc
    return manifest, stored


def gunzip_bounded(content: bytes, max_bytes: int) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(content), mode="rb") as stream:
            logical = stream.read(max_bytes + 1)
            if len(logical) > max_bytes or stream.read(1):
                raise EvidenceIntegrityError("decompressed evidence exceeds configured ceiling")
            return logical
    except (OSError, EOFError) as exc:
        raise EvidenceIntegrityError("compressed evidence blob is invalid") from exc


def validate_blob_key(key: str) -> None:
    if type(key) is not str or _SHA256_RE.fullmatch(key) is None:
        raise EvidenceIntegrityError("evidence blob key must be lowercase SHA-256 hex")
