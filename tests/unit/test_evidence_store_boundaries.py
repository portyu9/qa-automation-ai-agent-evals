from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

import agent_evals.evidence.store as store_module
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.evidence.store import (
    EvidenceConflictError,
    EvidenceIntegrityError,
    EvidenceStoreError,
    EvidenceStoreResourceError,
    LocalEvidenceStore,
)

_SUBJECT = "a" * 64
_SCENARIO = "b" * 64


def _evidence(*, final_state: dict[str, object] | None = None) -> TrialEvidence:
    return TrialEvidence(
        trial_id="boundary-trial",
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.STATE,
                source="environment",
                payload={"observed": True},
            ),
        ),
        final_state=final_state or {"status": "ok"},
        final_output="done",
        input_tokens=7,
        output_tokens=3,
    )


def _artifact_paths(store: LocalEvidenceStore) -> tuple[Path, Path]:
    payload = next(store.root.rglob("*.evidence.json"))
    manifest = next(store.root.rglob("*.manifest.json"))
    return payload, manifest


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _rewrite_payload_and_manifest(
    payload_path: Path,
    manifest_path: Path,
    payload_data: dict[str, object],
) -> None:
    payload_bytes = _json_bytes(payload_data)
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_data["payload_bytes"] = len(payload_bytes)
    manifest_data["payload_sha256"] = hashlib.sha256(payload_bytes).hexdigest()
    payload_path.write_bytes(payload_bytes)
    manifest_path.write_bytes(_json_bytes(manifest_data))


def test_regular_file_store_root_is_normalized_to_integrity_error(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    root.write_text("not-a-directory", encoding="utf-8")

    with pytest.raises(EvidenceIntegrityError, match="path is not a directory"):
        LocalEvidenceStore(root)


def test_regular_file_records_path_is_normalized_to_integrity_error(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "records").write_text("not-a-directory", encoding="utf-8")

    with pytest.raises(EvidenceIntegrityError, match="path is not a directory"):
        LocalEvidenceStore(root)


def test_directory_creation_oserror_is_normalized_to_integrity_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "evidence"
    real_mkdir = Path.mkdir

    def denied(path: Path, *args: object, **kwargs: object) -> None:
        if path == root:
            raise PermissionError("controlled denial")
        real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", denied)

    with pytest.raises(EvidenceIntegrityError, match="cannot create evidence-store directory"):
        LocalEvidenceStore(root)


@pytest.mark.parametrize("ceiling", [True, 1.5])
def test_non_integer_resource_ceilings_fail_closed(tmp_path: Path, ceiling: object) -> None:
    with pytest.raises(ValueError, match="byte ceilings must be positive integers"):
        LocalEvidenceStore(tmp_path / "evidence", max_payload_bytes=ceiling)  # type: ignore[arg-type]


def test_coherently_rehashed_invalid_payload_schema_is_rejected(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    manifest = store.write(_evidence())
    payload_path, manifest_path = _artifact_paths(store)
    payload_data = json.loads(payload_path.read_text(encoding="utf-8"))
    payload_data["input_tokens"] = -1
    _rewrite_payload_and_manifest(payload_path, manifest_path, payload_data)

    with pytest.raises(EvidenceIntegrityError, match="payload failed schema validation"):
        store.read(manifest.record_key)


def test_coherently_rehashed_payload_identity_mismatch_is_rejected(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    manifest = store.write(_evidence())
    payload_path, manifest_path = _artifact_paths(store)
    payload_data = json.loads(payload_path.read_text(encoding="utf-8"))
    payload_data["trial_id"] = "different-trial"
    _rewrite_payload_and_manifest(payload_path, manifest_path, payload_data)

    with pytest.raises(EvidenceIntegrityError, match="stored evidence identity does not match manifest"):
        store.read(manifest.record_key)


def test_coherently_rehashed_payload_root_mismatch_is_rejected(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    manifest = store.write(_evidence())
    payload_path, manifest_path = _artifact_paths(store)
    payload_data = json.loads(payload_path.read_text(encoding="utf-8"))
    payload_data["final_output"] = "tampered-but-valid"
    _rewrite_payload_and_manifest(payload_path, manifest_path, payload_data)

    with pytest.raises(EvidenceIntegrityError, match="stored evidence root does not match manifest"):
        store.read(manifest.record_key)


def test_non_regular_payload_artifact_is_rejected(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    manifest = store.write(_evidence())
    payload_path, _ = _artifact_paths(store)
    payload_path.unlink()
    payload_path.mkdir()

    with pytest.raises(EvidenceIntegrityError, match="artifact is not a regular file"):
        store.read(manifest.record_key)


def test_persisted_payload_resource_ceiling_is_enforced_on_read(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    writer = LocalEvidenceStore(root)
    manifest = writer.write(_evidence(final_state={"large": "x" * 1_024}))
    reader = LocalEvidenceStore(root, max_payload_bytes=128)

    with pytest.raises(EvidenceStoreResourceError, match=r"evidence artifact .* maximum is 128"):
        reader.read(manifest.record_key)


def test_bounded_read_detects_short_read_or_mid_read_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    manifest = store.write(_evidence())
    real_read = os.read
    first = True

    def short_once(fd: int, size: int) -> bytes:
        nonlocal first
        if first:
            first = False
            return b""
        return real_read(fd, size)

    monkeypatch.setattr(store_module.os, "read", short_once)

    with pytest.raises(EvidenceIntegrityError, match="changed during bounded read"):
        store.read(manifest.record_key)


def test_publication_race_does_not_clobber_existing_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")

    def raced_hardlink(self: Path, target: Path) -> None:
        del self, target
        raise FileExistsError("controlled publication race")

    monkeypatch.setattr(Path, "hardlink_to", raced_hardlink)

    with pytest.raises(EvidenceConflictError, match="appeared during publication"):
        store.write(_evidence())

    assert not tuple(store.root.rglob("*.lock"))
    assert not tuple(store.root.rglob("*.tmp"))


def test_publication_oserror_is_wrapped_without_leaking_raw_filesystem_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")

    def failed_hardlink(self: Path, target: Path) -> None:
        del self, target
        raise OSError("controlled hardlink failure")

    monkeypatch.setattr(Path, "hardlink_to", failed_hardlink)

    with pytest.raises(EvidenceStoreError, match="cannot atomically publish evidence artifact"):
        store.write(_evidence())

    assert not tuple(store.root.rglob("*.lock"))
    assert not tuple(store.root.rglob("*.tmp"))


def test_short_write_is_wrapped_and_temporary_state_is_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")

    def short_write(fd: int, data: bytes) -> int:
        del fd, data
        return 0

    monkeypatch.setattr(store_module.os, "write", short_write)

    with pytest.raises(EvidenceStoreError, match="short write while materializing"):
        store.write(_evidence())

    assert not tuple(store.root.rglob("*.lock"))
    assert not tuple(store.root.rglob("*.tmp"))


def test_directory_fsync_failure_is_wrapped_and_record_remains_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    real_fsync = os.fsync

    def fail_directory_fsync(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("controlled directory fsync failure")
        real_fsync(fd)

    monkeypatch.setattr(store_module.os, "fsync", fail_directory_fsync)

    with pytest.raises(EvidenceStoreError, match="cannot durability-sync evidence directory"):
        store.write(_evidence())

    assert not tuple(store.root.rglob("*.lock"))
