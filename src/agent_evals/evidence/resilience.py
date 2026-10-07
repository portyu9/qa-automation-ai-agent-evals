"""Explicit local evidence-store resilience and operator recovery contracts.

The helpers in this module are additive to LocalEvidenceStore. They do not change historical
evidence, manifest, or record-key identities. Platform capabilities are derived from the running
Python/OS rather than supplied by a backend, and lock recovery requires an exact operator-confirmed
observation. A lock observation is filesystem identity evidence only; it does not authenticate a
writer or prove that a lock is stale.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.evidence.store import (
    EvidenceConflictError,
    EvidenceIntegrityError,
    EvidenceStoreError,
    LocalEvidenceStore,
    _ensure_store_directory,
    _fsync_directory,
    _validate_record_key,
)

_LOCK_OBSERVATION_SCHEMA: Literal["agent-evals/evidence-lock-observation/v1"] = (
    "agent-evals/evidence-lock-observation/v1"
)
_LOCK_QUARANTINE_SCHEMA: Literal["agent-evals/evidence-lock-quarantine/v1"] = (
    "agent-evals/evidence-lock-quarantine/v1"
)
_LOCK_OBSERVATION_DOMAIN = b"agent-evals/evidence-lock-observation/v1\\x00"
_LOCK_QUARANTINE_DOMAIN = b"agent-evals/evidence-lock-quarantine/v1\\x00"


class EvidenceStorePlatformMode(StrEnum):
    """Requested local-filesystem assurance mode."""

    PORTABLE = "portable"
    HARDENED_POSIX = "hardened_posix"


class EvidenceStorePlatformCapabilities(BaseModel):
    """Runtime-derived filesystem capabilities; never a backend trust assertion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    os_name: str
    posix: bool
    o_directory: bool
    o_nofollow: bool
    open_dir_fd: bool
    mkdir_dir_fd: bool
    stat_dir_fd: bool
    stat_nofollow: bool
    link_dir_fd: bool
    link_nofollow: bool
    unlink_dir_fd: bool
    rename_dir_fd: bool

    @property
    def hardened_posix_available(self) -> bool:
        return (
            self.posix
            and self.o_directory
            and self.o_nofollow
            and self.open_dir_fd
            and self.mkdir_dir_fd
            and self.stat_dir_fd
            and self.stat_nofollow
            and self.link_dir_fd
            and self.link_nofollow
            and self.unlink_dir_fd
            and self.rename_dir_fd
        )


def detect_platform_capabilities() -> EvidenceStorePlatformCapabilities:
    """Derive the exact filesystem primitives available to this Python runtime."""

    supports_dir_fd = getattr(os, "supports_dir_fd", set())
    supports_follow_symlinks = getattr(os, "supports_follow_symlinks", set())
    return EvidenceStorePlatformCapabilities(
        os_name=os.name,
        posix=os.name == "posix",
        o_directory=bool(getattr(os, "O_DIRECTORY", 0)),
        o_nofollow=bool(getattr(os, "O_NOFOLLOW", 0)),
        open_dir_fd=os.open in supports_dir_fd,
        mkdir_dir_fd=os.mkdir in supports_dir_fd,
        stat_dir_fd=os.stat in supports_dir_fd,
        stat_nofollow=os.stat in supports_follow_symlinks,
        link_dir_fd=os.link in supports_dir_fd,
        link_nofollow=os.link in supports_follow_symlinks,
        unlink_dir_fd=os.unlink in supports_dir_fd,
        rename_dir_fd=os.rename in supports_dir_fd,
    )


def require_platform_mode(
    mode: EvidenceStorePlatformMode | str,
) -> EvidenceStorePlatformCapabilities:
    """Fail closed when requested hardened POSIX guarantees are unavailable."""

    requested = EvidenceStorePlatformMode(mode)
    capabilities = detect_platform_capabilities()
    if (
        requested is EvidenceStorePlatformMode.HARDENED_POSIX
        and not capabilities.hardened_posix_available
    ):
        raise EvidenceStoreError(
            "hardened_posix evidence-store mode requires POSIX O_DIRECTORY/O_NOFOLLOW "
            "and dir_fd/no-follow support for open/mkdir/stat/link/unlink/rename"
        )
    return capabilities


class EvidenceLockObservation(BaseModel):
    """Identity-bound observation of one exact local record lock."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/evidence-lock-observation/v1"] = (
        _LOCK_OBSERVATION_SCHEMA
    )
    record_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    device: int = Field(ge=0, strict=True)
    inode: int = Field(ge=0, strict=True)
    size_bytes: int = Field(ge=0, strict=True)
    mtime_ns: int = Field(ge=0, strict=True)
    observation_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        record_key: str,
        device: int,
        inode: int,
        size_bytes: int,
        mtime_ns: int,
    ) -> Self:
        _validate_record_key(record_key)
        material = {
            "schema_version": _LOCK_OBSERVATION_SCHEMA,
            "record_key": record_key,
            "device": device,
            "inode": inode,
            "size_bytes": size_bytes,
            "mtime_ns": mtime_ns,
        }
        return cls(
            **material,
            observation_root=_root(_LOCK_OBSERVATION_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_root(self) -> Self:
        material = {
            "schema_version": self.schema_version,
            "record_key": self.record_key,
            "device": self.device,
            "inode": self.inode,
            "size_bytes": self.size_bytes,
            "mtime_ns": self.mtime_ns,
        }
        expected = _root(_LOCK_OBSERVATION_DOMAIN, material)
        if not hmac.compare_digest(expected, self.observation_root):
            raise ValueError("evidence lock observation root mismatch")
        return self


class EvidenceLockQuarantineReceipt(BaseModel):
    """Audit receipt for moving one observed lock out of the active namespace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/evidence-lock-quarantine/v1"] = (
        _LOCK_QUARANTINE_SCHEMA
    )
    record_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    observation_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    quarantine_name: str = Field(min_length=1, max_length=256)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        record_key: str,
        observation_root: str,
        quarantine_name: str,
    ) -> Self:
        material = {
            "schema_version": _LOCK_QUARANTINE_SCHEMA,
            "record_key": record_key,
            "observation_root": observation_root,
            "quarantine_name": quarantine_name,
        }
        return cls(**material, receipt_root=_root(_LOCK_QUARANTINE_DOMAIN, material))

    @model_validator(mode="after")
    def verify_root(self) -> Self:
        material = {
            "schema_version": self.schema_version,
            "record_key": self.record_key,
            "observation_root": self.observation_root,
            "quarantine_name": self.quarantine_name,
        }
        expected = _root(_LOCK_QUARANTINE_DOMAIN, material)
        if not hmac.compare_digest(expected, self.receipt_root):
            raise ValueError("evidence lock quarantine receipt root mismatch")
        return self


def inspect_record_lock(
    store: LocalEvidenceStore,
    record_key: str,
) -> EvidenceLockObservation:
    """Inspect a lock without deciding whether it is stale or safe to remove."""

    if type(store) is not LocalEvidenceStore:
        raise TypeError("lock inspection requires an exact LocalEvidenceStore")
    _validate_record_key(record_key)
    path = _lock_path(store, record_key)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError as exc:
        raise EvidenceStoreError(f"record lock does not exist: {record_key}") from exc
    except OSError as exc:
        raise EvidenceIntegrityError(f"cannot safely open record lock: {record_key}") from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise EvidenceIntegrityError("record lock is not a regular file")
        try:
            current = path.lstat()
        except OSError as exc:
            raise EvidenceIntegrityError("cannot revalidate record lock path") from exc
        if (
            not stat.S_ISREG(current.st_mode)
            or (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino)
        ):
            raise EvidenceIntegrityError(
                "record lock identity changed during inspection; refusing observation"
            )
        return EvidenceLockObservation.create(
            record_key=record_key,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            size_bytes=metadata.st_size,
            mtime_ns=metadata.st_mtime_ns,
        )
    finally:
        os.close(fd)


def quarantine_record_lock(
    store: LocalEvidenceStore,
    observation: EvidenceLockObservation,
    *,
    confirm_observation_root: str,
) -> EvidenceLockQuarantineReceipt:
    """Move one exact observed lock to a private audit quarantine.

    This operation never decides staleness automatically. The caller must provide the exact
    observation root it reviewed. The source is hard-linked into quarantine first; if the active
    path changed, cleanup fails closed and the replacement is left in place.
    """

    if type(store) is not LocalEvidenceStore:
        raise TypeError("lock quarantine requires an exact LocalEvidenceStore")
    if type(observation) is not EvidenceLockObservation:
        raise TypeError("lock quarantine requires an exact EvidenceLockObservation")
    if not hmac.compare_digest(confirm_observation_root, observation.observation_root):
        raise ValueError("lock quarantine requires exact observation-root confirmation")

    current = inspect_record_lock(store, observation.record_key)
    if current != observation:
        raise EvidenceIntegrityError(
            "record lock changed after operator observation; refusing quarantine"
        )

    source = _lock_path(store, observation.record_key)
    quarantine_root = store.root / "quarantine"
    quarantine_dir = quarantine_root / "locks"
    _ensure_store_directory(quarantine_root)
    _ensure_store_directory(quarantine_dir)
    quarantine_name = f"{observation.record_key}.{observation.observation_root[:16]}.lock"
    destination = quarantine_dir / quarantine_name
    try:
        os.link(source, destination, follow_symlinks=False)
    except FileExistsError as exc:
        raise EvidenceConflictError(
            f"lock quarantine artifact already exists: {quarantine_name}"
        ) from exc
    except OSError as exc:
        raise EvidenceStoreError("cannot create no-clobber lock quarantine artifact") from exc

    source_now = source.lstat()
    destination_now = destination.lstat()
    expected_identity = (observation.device, observation.inode)
    if (
        not stat.S_ISREG(source_now.st_mode)
        or not stat.S_ISREG(destination_now.st_mode)
        or (source_now.st_dev, source_now.st_ino) != expected_identity
        or (destination_now.st_dev, destination_now.st_ino) != expected_identity
    ):
        raise EvidenceIntegrityError(
            "record lock identity changed during quarantine; refusing active cleanup"
        )

    source.unlink()
    _fsync_directory(source.parent)
    _fsync_directory(destination.parent)
    return EvidenceLockQuarantineReceipt.create(
        record_key=observation.record_key,
        observation_root=observation.observation_root,
        quarantine_name=quarantine_name,
    )


def _lock_path(store: LocalEvidenceStore, record_key: str) -> Path:
    bucket = store.root / "records" / record_key[:2]
    if bucket.is_symlink():
        raise EvidenceIntegrityError("evidence record bucket cannot be a symlink")
    return bucket / f"{record_key}.lock"


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
