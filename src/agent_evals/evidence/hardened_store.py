"""Opt-in POSIX directory-handle evidence store.

This store preserves the LocalEvidenceStore record key, manifest, payload, and TrialEvidence/v2
semantics while anchoring trust-critical artifact operations to opened directory descriptors. It is
available only when the runtime exposes the required POSIX dir_fd and no-follow primitives.

The mode reduces path-re-resolution TOCTOU exposure on a hostile local filesystem. It does not
authenticate writers, provide distributed/NFS locking, prove crash consistency for arbitrary
filesystems, or turn inode/device values into identities outside the local filesystem instance.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from pydantic import ValidationError

from agent_evals._strict_json import StrictJsonError, strict_json_loads
from agent_evals.evidence.models import TrialEvidence
from agent_evals.evidence.resilience import (
    EvidenceStorePlatformMode,
    require_platform_mode,
)
from agent_evals.evidence.store import (
    ArtifactManifest,
    EvidenceConflictError,
    EvidenceIntegrityError,
    EvidenceStoreBusyError,
    EvidenceStoreError,
    EvidenceStoreResourceError,
    IncompleteEvidenceRecordError,
    StoredEvidence,
    _canonical_json_bytes,
    _ensure_store_directory,
    _is_positive_byte_ceiling,
    _record_key,
    _validate_record_key,
    evidence_record_key,
)


class HardenedPosixEvidenceStore:
    """Immutable local store using opened directory handles for artifact operations."""

    def __init__(
        self,
        root: str | Path,
        *,
        max_payload_bytes: int = 8 * 1024 * 1024,
        max_manifest_bytes: int = 64 * 1024,
    ) -> None:
        require_platform_mode(EvidenceStorePlatformMode.HARDENED_POSIX)
        if not _is_positive_byte_ceiling(max_payload_bytes) or not _is_positive_byte_ceiling(
            max_manifest_bytes
        ):
            raise ValueError("evidence-store byte ceilings must be positive integers")
        self._root = Path(root)
        self._records = self._root / "records"
        self._max_payload_bytes = max_payload_bytes
        self._max_manifest_bytes = max_manifest_bytes
        _ensure_store_directory(self._root)
        _ensure_store_directory(self._records)
        # Fail during construction rather than first write if the anchored directories cannot be
        # opened under the requested hardened contract.
        with self._records_fd():
            pass

    @property
    def root(self) -> Path:
        return self._root

    def write(self, evidence: TrialEvidence) -> ArtifactManifest:
        evidence = evidence.snapshot()
        payload = _canonical_json_bytes(evidence.model_dump(mode="json"))
        if len(payload) > self._max_payload_bytes:
            raise EvidenceStoreResourceError(
                f"evidence payload is {len(payload)} bytes; maximum is {self._max_payload_bytes}"
            )

        key = evidence_record_key(evidence)
        with self._bucket_fd(key, create=True) as bucket_fd:
            lock_name = f"{key}.lock"
            lock_fd = _acquire_lock_fd(bucket_fd, lock_name)
            try:
                presence = _presence_fd(bucket_fd, key)
                if presence == "complete":
                    existing = self._read_from_bucket(bucket_fd, key)
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

                manifest = ArtifactManifest(
                    record_key=key,
                    trial_id=evidence.trial_id,
                    subject_identity=evidence.subject_identity,
                    scenario_identity=evidence.scenario_identity,
                    evidence_root=evidence.evidence_root,
                    payload_sha256=hashlib.sha256(payload).hexdigest(),
                    payload_bytes=len(payload),
                )
                manifest_bytes = _canonical_json_bytes(manifest.model_dump(mode="json"))
                if len(manifest_bytes) > self._max_manifest_bytes:
                    raise EvidenceStoreResourceError(
                        "evidence manifest is "
                        f"{len(manifest_bytes)} bytes; maximum is {self._max_manifest_bytes}"
                    )

                _atomic_materialize_fd(bucket_fd, f"{key}.evidence.json", payload)
                _atomic_materialize_fd(bucket_fd, f"{key}.manifest.json", manifest_bytes)
                return manifest
            finally:
                _release_lock_fd(bucket_fd, lock_name, lock_fd)

    def read(self, record_key: str) -> StoredEvidence:
        _validate_record_key(record_key)
        try:
            with self._bucket_fd(record_key, create=False) as bucket_fd:
                return self._read_from_bucket(bucket_fd, record_key)
        except FileNotFoundError as exc:
            raise IncompleteEvidenceRecordError(
                f"record key {record_key} does not have both payload and manifest"
            ) from exc

    def _read_from_bucket(self, bucket_fd: int, record_key: str) -> StoredEvidence:
        if _presence_fd(bucket_fd, record_key) != "complete":
            raise IncompleteEvidenceRecordError(
                f"record key {record_key} does not have both payload and manifest"
            )
        manifest_bytes = _safe_read_fd(
            bucket_fd,
            f"{record_key}.manifest.json",
            self._max_manifest_bytes,
        )
        payload = _safe_read_fd(
            bucket_fd,
            f"{record_key}.evidence.json",
            self._max_payload_bytes,
        )
        return _decode_record(record_key, manifest_bytes, payload)

    @contextmanager
    def _records_fd(self) -> Iterator[int]:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            fd = os.open(self._records, flags)
        except OSError as exc:
            raise EvidenceIntegrityError("cannot open hardened evidence records directory") from exc
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISDIR(metadata.st_mode):
                raise EvidenceIntegrityError("hardened evidence records handle is not a directory")
            yield fd
        finally:
            os.close(fd)

    @contextmanager
    def _bucket_fd(self, record_key: str, *, create: bool) -> Iterator[int]:
        _validate_record_key(record_key)
        bucket_name = record_key[:2]
        with self._records_fd() as records_fd:
            if create:
                try:
                    os.mkdir(bucket_name, mode=0o700, dir_fd=records_fd)
                    os.fsync(records_fd)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise EvidenceIntegrityError(
                        "cannot create hardened evidence record bucket"
                    ) from exc
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            try:
                bucket_fd = os.open(bucket_name, flags, dir_fd=records_fd)
            except FileNotFoundError:
                raise
            except OSError as exc:
                raise EvidenceIntegrityError("cannot open hardened evidence record bucket") from exc
            try:
                metadata = os.fstat(bucket_fd)
                if not stat.S_ISDIR(metadata.st_mode):
                    raise EvidenceIntegrityError(
                        "hardened evidence record bucket is not a directory"
                    )
                yield bucket_fd
            finally:
                os.close(bucket_fd)


def _presence_fd(bucket_fd: int, record_key: str) -> str:
    payload = _entry_exists_fd(bucket_fd, f"{record_key}.evidence.json")
    manifest = _entry_exists_fd(bucket_fd, f"{record_key}.manifest.json")
    if payload and manifest:
        return "complete"
    if payload or manifest:
        return "partial"
    return "absent"


def _entry_exists_fd(bucket_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=bucket_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise EvidenceIntegrityError(f"cannot inspect hardened evidence artifact: {name}") from exc
    return True


def _acquire_lock_fd(bucket_fd: int, lock_name: str) -> int:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
    try:
        return os.open(lock_name, flags, 0o600, dir_fd=bucket_fd)
    except FileExistsError as exc:
        raise EvidenceStoreBusyError(
            f"record lock already exists: {lock_name}; stale locks require explicit operator review"
        ) from exc
    except OSError as exc:
        raise EvidenceStoreError("cannot create hardened evidence record lock") from exc


def _release_lock_fd(bucket_fd: int, lock_name: str, fd: int) -> None:
    try:
        acquired = os.fstat(fd)
        current = os.stat(lock_name, dir_fd=bucket_fd, follow_symlinks=False)
        _verify_identity(lock_name, acquired, current)
    except FileNotFoundError as exc:
        raise EvidenceIntegrityError(
            f"record lock disappeared before release: {lock_name}"
        ) from exc
    finally:
        os.close(fd)

    try:
        current = os.stat(lock_name, dir_fd=bucket_fd, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise EvidenceIntegrityError(
            f"record lock disappeared before release: {lock_name}"
        ) from exc
    _verify_identity(lock_name, acquired, current)
    try:
        os.unlink(lock_name, dir_fd=bucket_fd)
        os.fsync(bucket_fd)
    except FileNotFoundError as exc:
        raise EvidenceIntegrityError(
            f"record lock disappeared during release: {lock_name}"
        ) from exc
    except OSError as exc:
        raise EvidenceIntegrityError(f"cannot release record lock: {lock_name}") from exc


def _verify_identity(
    name: str,
    acquired: os.stat_result,
    current: os.stat_result,
) -> None:
    if not stat.S_ISREG(current.st_mode) or (
        current.st_dev,
        current.st_ino,
    ) != (
        acquired.st_dev,
        acquired.st_ino,
    ):
        raise EvidenceIntegrityError(
            f"record lock ownership changed before release: {name}; refusing cleanup"
        )


def _safe_read_fd(bucket_fd: int, name: str, max_bytes: int) -> bytes:
    flags = os.O_RDONLY | os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=bucket_fd)
    except OSError as exc:
        raise EvidenceIntegrityError(
            f"cannot safely open hardened evidence artifact: {name}"
        ) from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise EvidenceIntegrityError(
                f"hardened evidence artifact is not a regular file: {name}"
            )
        if metadata.st_size > max_bytes:
            raise EvidenceStoreResourceError(
                f"evidence artifact {name} is {metadata.st_size} bytes; maximum is {max_bytes}"
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
            raise EvidenceIntegrityError(f"evidence artifact changed during bounded read: {name}")
        return data
    finally:
        os.close(fd)


def _atomic_materialize_fd(bucket_fd: int, name: str, content: bytes) -> None:
    if _entry_exists_fd(bucket_fd, name):
        raise EvidenceConflictError(f"refusing to replace existing evidence artifact: {name}")

    temporary_name = f".{name}.{secrets.token_hex(16)}.tmp"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
    fd = -1
    try:
        fd = os.open(temporary_name, flags, 0o600, dir_fd=bucket_fd)
        offset = 0
        while offset < len(content):
            written = os.write(fd, content[offset:])
            if written <= 0:
                raise EvidenceStoreError(
                    f"short write while materializing evidence artifact: {name}"
                )
            offset += written
        os.fsync(fd)
        os.close(fd)
        fd = -1
        try:
            os.link(
                temporary_name,
                name,
                src_dir_fd=bucket_fd,
                dst_dir_fd=bucket_fd,
                follow_symlinks=False,
            )
        except FileExistsError as exc:
            raise EvidenceConflictError(
                f"evidence artifact appeared during publication: {name}"
            ) from exc
        except OSError as exc:
            raise EvidenceStoreError(
                f"cannot atomically publish hardened evidence artifact: {name}"
            ) from exc
        os.fsync(bucket_fd)
        os.unlink(temporary_name, dir_fd=bucket_fd)
        os.fsync(bucket_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        with suppress(FileNotFoundError):
            os.unlink(temporary_name, dir_fd=bucket_fd)


def _decode_record(
    record_key: str,
    manifest_bytes: bytes,
    payload: bytes,
) -> StoredEvidence:
    try:
        manifest_raw = strict_json_loads(
            manifest_bytes,
            label="evidence manifest",
            require_object=True,
        )
        manifest = ArtifactManifest.model_validate(manifest_raw)
    except StrictJsonError as exc:
        raise EvidenceIntegrityError("evidence manifest failed strict JSON decoding") from exc
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
        raise EvidenceIntegrityError("manifest identity does not derive the requested record key")
    if manifest.payload_bytes != len(payload):
        raise EvidenceIntegrityError("manifest payload length does not match stored bytes")
    if manifest.payload_sha256 != hashlib.sha256(payload).hexdigest():
        raise EvidenceIntegrityError("stored evidence payload hash does not match manifest")

    try:
        evidence_raw = strict_json_loads(
            payload,
            label="stored evidence payload",
            require_object=True,
        )
        evidence = TrialEvidence.model_validate(evidence_raw)
    except StrictJsonError as exc:
        raise EvidenceIntegrityError("stored evidence payload failed strict JSON decoding") from exc
    except ValidationError as exc:
        raise EvidenceIntegrityError("stored evidence payload failed schema validation") from exc

    if (
        evidence.trial_id != manifest.trial_id
        or evidence.subject_identity != manifest.subject_identity
        or evidence.scenario_identity != manifest.scenario_identity
    ):
        raise EvidenceIntegrityError("stored evidence identity does not match manifest")
    if evidence.evidence_root != manifest.evidence_root:
        raise EvidenceIntegrityError("stored evidence root does not match manifest")
    return StoredEvidence(manifest=manifest, evidence=evidence)
