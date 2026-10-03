from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_evals.evidence.store as store_module
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.evidence.store import (
    EvidenceConflictError,
    EvidenceIntegrityError,
    EvidenceStoreError,
    EvidenceStoreResourceError,
    IncompleteEvidenceRecordError,
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


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
def test_new_store_owned_directories_are_private_on_posix(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    store = LocalEvidenceStore(root)

    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "records").stat().st_mode) == 0o700

    store.write(_evidence())
    bucket = next(path for path in (root / "records").iterdir() if path.is_dir())
    assert stat.S_IMODE(bucket.stat().st_mode) == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode contract")
def test_preexisting_directory_permissions_are_not_silently_changed(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    root.mkdir(mode=0o755)
    root.chmod(0o755)

    LocalEvidenceStore(root)

    assert stat.S_IMODE(root.stat().st_mode) == 0o755
    assert stat.S_IMODE((root / "records").stat().st_mode) == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX open-file replacement semantics")
def test_lock_release_refuses_to_unlink_replacement_file(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    lock_path = store.root / "records" / "replacement.lock"
    lock_fd = store._acquire_lock(lock_path)
    acquired = os.fstat(lock_fd)

    lock_path.unlink()
    lock_path.write_text("replacement", encoding="utf-8")
    replacement = lock_path.stat()
    assert (replacement.st_dev, replacement.st_ino) != (acquired.st_dev, acquired.st_ino)

    with pytest.raises(EvidenceIntegrityError, match="lock ownership changed"):
        store_module._release_lock(lock_path, lock_fd)

    assert lock_path.read_text(encoding="utf-8") == "replacement"


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

    with pytest.raises(
        EvidenceIntegrityError, match="stored evidence identity does not match manifest"
    ):
        store.read(manifest.record_key)


def test_coherently_rehashed_payload_root_mismatch_is_rejected(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    manifest = store.write(_evidence())
    payload_path, manifest_path = _artifact_paths(store)
    payload_data = json.loads(payload_path.read_text(encoding="utf-8"))
    payload_data["final_output"] = "tampered-but-valid"
    _rewrite_payload_and_manifest(payload_path, manifest_path, payload_data)

    with pytest.raises(
        EvidenceIntegrityError, match="stored evidence root does not match manifest"
    ):
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
    calls = 0

    def short_write(fd: int, data: bytes) -> int:
        nonlocal calls
        del fd, data
        calls += 1
        if calls == 1:
            return 0
        raise AssertionError("zero-byte evidence write was retried")

    monkeypatch.setattr(store_module.os, "write", short_write)

    with pytest.raises(EvidenceStoreError, match="short write while materializing"):
        store.write(_evidence())

    assert calls == 1
    assert not tuple(store.root.rglob("*.lock"))
    assert not tuple(store.root.rglob("*.tmp"))


def test_atomic_materialize_advances_after_full_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "artifact.json"
    real_write = os.write
    calls = 0

    def write_once(fd: int, data: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AssertionError("completed evidence write was retried")
        return real_write(fd, data)

    monkeypatch.setattr(store_module.os, "write", write_once)

    store_module._atomic_materialize(path, b"x")

    assert calls == 1
    assert path.read_bytes() == b"x"


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


def test_store_scalar_record_key_and_validation_contracts_are_exact(tmp_path: Path) -> None:
    with pytest.raises(ValueError) as captured:
        LocalEvidenceStore(tmp_path / "invalid", max_payload_bytes=0)
    assert str(captured.value) == "evidence-store byte ceilings must be positive integers"

    assert store_module._is_positive_byte_ceiling(1) is True
    assert store_module._is_positive_byte_ceiling(True) is False

    trial_id = "record-key-contract"
    expected = hashlib.sha256(
        _json_bytes(
            {
                "trial_id": trial_id,
                "subject_identity": _SUBJECT,
                "scenario_identity": _SCENARIO,
            }
        )
    ).hexdigest()
    assert (
        store_module._record_key(
            trial_id=trial_id,
            subject_identity=_SUBJECT,
            scenario_identity=_SCENARIO,
        )
        == expected
    )

    with pytest.raises(EvidenceIntegrityError) as captured:
        store_module._validate_record_key("A" * 64)
    assert str(captured.value) == ("record key must be exactly 64 lowercase hexadecimal characters")


def test_presence_and_lock_creation_use_exact_filesystem_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = store_module._RecordPaths(
        payload=tmp_path / "payload",
        manifest=tmp_path / "manifest",
        lock=tmp_path / "lock",
    )
    assert LocalEvidenceStore._presence(paths) == "absent"

    real_open = os.open
    observed: list[tuple[object, int, int | None]] = []

    def checked_open(
        path: object,
        flags: int,
        mode: int | None = None,
    ) -> int:
        observed.append((path, flags, mode))
        assert flags == os.O_CREAT | os.O_EXCL | os.O_WRONLY
        assert mode == 0o600
        return real_open(path, flags, mode)

    monkeypatch.setattr(store_module.os, "open", checked_open)
    fd = LocalEvidenceStore._acquire_lock(paths.lock)
    try:
        assert observed == [(paths.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)]
    finally:
        os.close(fd)
        paths.lock.unlink()


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory contract")
def test_store_directory_creation_uses_exact_private_creation_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "private"
    real_mkdir = Path.mkdir
    real_chmod = Path.chmod
    mkdir_calls: list[tuple[int, bool, bool]] = []
    chmod_calls: list[int] = []

    def checked_mkdir(
        path: Path,
        mode: int = 0o777,
        parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        if path == target:
            mkdir_calls.append((mode, parents, exist_ok))
            assert (mode, parents, exist_ok) == (0o700, True, False)
        real_mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    def checked_chmod(path: Path, mode: int, *args: object, **kwargs: object) -> None:
        if path == target:
            chmod_calls.append(mode)
            assert mode == 0o700
        real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", checked_mkdir)
    monkeypatch.setattr(Path, "chmod", checked_chmod)

    store_module._ensure_store_directory(target)

    assert mkdir_calls == [(0o700, True, False)]
    assert chmod_calls == [0o700]
    assert stat.S_IMODE(target.stat().st_mode) == 0o700


def test_payload_and_manifest_exact_ceiling_are_accepted(tmp_path: Path) -> None:
    evidence = _evidence()
    payload = store_module._canonical_json_bytes(evidence.snapshot().model_dump(mode="json"))
    probe = LocalEvidenceStore(tmp_path / "payload-exact", max_payload_bytes=len(payload))
    manifest = probe.write(evidence)
    assert manifest.payload_bytes == len(payload)

    roomy = LocalEvidenceStore(tmp_path / "manifest-probe")
    expected_manifest = roomy.write(evidence)
    _, manifest_path = _artifact_paths(roomy)
    manifest_size = len(manifest_path.read_bytes())

    exact = LocalEvidenceStore(
        tmp_path / "manifest-exact",
        max_manifest_bytes=manifest_size,
    )
    exact_manifest = exact.write(evidence)
    assert exact_manifest.payload_sha256 == expected_manifest.payload_sha256


def test_immutable_write_requires_all_three_existing_identity_bindings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    evidence = _evidence()
    original = store.write(evidence)
    forged_manifest = original.model_copy(update={"payload_sha256": "0" * 64})

    monkeypatch.setattr(
        store,
        "read",
        lambda _key: store_module.StoredEvidence(
            manifest=forged_manifest,
            evidence=evidence,
        ),
    )

    with pytest.raises(EvidenceConflictError) as captured:
        store.write(evidence)
    assert str(captured.value) == (
        f"record key {original.record_key} already exists with different immutable evidence"
    )


def test_read_passes_exact_noncreating_path_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    key = "a" * 64

    def checked_paths(record_key: str, *, create_bucket: bool) -> store_module._RecordPaths:
        assert record_key == key
        assert create_bucket is False
        raise RuntimeError("path contract observed")

    monkeypatch.setattr(store, "_paths", checked_paths)
    with pytest.raises(RuntimeError, match="path contract observed"):
        store.read(key)


def test_safe_read_uses_nofollow_exact_bounds_and_chunk_sizes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "large.bin"
    content = b"a" * (70 * 1024)
    path.write_bytes(content)
    real_open = os.open
    real_read = os.read
    read_sizes: list[int] = []

    def checked_open(path_arg: object, flags: int, *args: object) -> int:
        assert flags == os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        return real_open(path_arg, flags, *args)

    def checked_read(fd: int, size: int) -> bytes:
        read_sizes.append(size)
        return real_read(fd, size)

    monkeypatch.setattr(store_module.os, "open", checked_open)
    monkeypatch.setattr(store_module.os, "read", checked_read)

    observed = store_module._safe_read_regular_file(path, len(content))

    assert observed == content
    assert read_sizes[0] == 64 * 1024
    assert read_sizes[-1] == 1


def test_safe_read_detects_growth_beyond_initial_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "growth.bin"
    path.write_bytes(b"abcd")
    real_fstat = os.fstat

    def short_metadata(fd: int) -> object:
        current = real_fstat(fd)
        return SimpleNamespace(st_mode=current.st_mode, st_size=3)

    monkeypatch.setattr(store_module.os, "fstat", short_metadata)

    with pytest.raises(EvidenceIntegrityError) as captured:
        store_module._safe_read_regular_file(path, 4)
    assert str(captured.value) == ("evidence artifact changed during bounded read: growth.bin")


def test_atomic_materialize_refuses_existing_regular_file_with_exact_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "existing.json"
    path.write_bytes(b"old")

    with pytest.raises(EvidenceConflictError) as captured:
        store_module._atomic_materialize(path, b"new")
    assert str(captured.value) == ("refusing to replace existing evidence artifact: existing.json")
    assert path.read_bytes() == b"old"


def test_atomic_materialize_uses_exact_temp_contract_and_accumulates_partial_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "artifact.json"
    real_mkstemp = store_module.tempfile.mkstemp
    real_write = os.write
    mkstemp_calls: list[tuple[str | None, str | None, object]] = []
    write_calls = 0

    def checked_mkstemp(
        *,
        prefix: str | None = None,
        suffix: str | None = None,
        dir: object = None,
    ) -> tuple[int, str]:
        mkstemp_calls.append((prefix, suffix, dir))
        assert prefix == ".artifact.json."
        assert suffix == ".tmp"
        assert dir == tmp_path
        return real_mkstemp(prefix=prefix, suffix=suffix, dir=dir)

    def one_byte_write(fd: int, data: bytes) -> int:
        nonlocal write_calls
        write_calls += 1
        if write_calls > 3:
            raise AssertionError("partial-write offset did not advance")
        return real_write(fd, data[:1])

    monkeypatch.setattr(store_module.tempfile, "mkstemp", checked_mkstemp)
    monkeypatch.setattr(store_module.os, "write", one_byte_write)

    store_module._atomic_materialize(path, b"abc")

    assert mkstemp_calls == [(".artifact.json.", ".tmp", tmp_path)]
    assert write_calls == 3
    assert path.read_bytes() == b"abc"


def test_release_lock_uses_exact_path_for_both_identity_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "record.lock"
    fd = LocalEvidenceStore._acquire_lock(path)
    real_verify = store_module._verify_lock_identity
    observed: list[Path] = []

    def checked_verify(
        observed_path: Path,
        acquired: os.stat_result,
        current: os.stat_result,
    ) -> None:
        observed.append(observed_path)
        assert observed_path == path
        real_verify(observed_path, acquired, current)

    monkeypatch.setattr(store_module, "_verify_lock_identity", checked_verify)
    store_module._release_lock(path, fd)

    assert observed == [path, path]
    assert not path.exists()


def test_release_lock_failure_diagnostics_are_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disappeared = tmp_path / "disappeared.lock"
    fd = LocalEvidenceStore._acquire_lock(disappeared)
    disappeared.unlink()
    with pytest.raises(EvidenceIntegrityError) as captured:
        store_module._release_lock(disappeared, fd)
    assert str(captured.value) == ("record lock disappeared before release: disappeared.lock")

    path = tmp_path / "unlink-failure.lock"
    fd = LocalEvidenceStore._acquire_lock(path)
    real_unlink = Path.unlink

    def fail_unlink(candidate: Path, *args: object, **kwargs: object) -> None:
        if candidate == path:
            raise OSError("controlled unlink failure")
        real_unlink(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_unlink)
    with pytest.raises(EvidenceIntegrityError) as captured:
        store_module._release_lock(path, fd)
    assert str(captured.value) == "cannot release record lock: unlink-failure.lock"


def test_lock_identity_failure_diagnostic_is_exact(tmp_path: Path) -> None:
    first = tmp_path / "first.lock"
    second = tmp_path / "second.lock"
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    with pytest.raises(EvidenceIntegrityError) as captured:
        store_module._verify_lock_identity(first, first.stat(), second.stat())
    assert str(captured.value) == (
        "record lock ownership changed before release: first.lock; refusing cleanup"
    )


def test_read_integrity_diagnostics_are_exact(tmp_path: Path) -> None:
    empty = LocalEvidenceStore(tmp_path / "empty")
    key = "a" * 64
    with pytest.raises(IncompleteEvidenceRecordError) as captured:
        empty.read(key)
    assert str(captured.value) == (f"record key {key} does not have both payload and manifest")

    store = LocalEvidenceStore(tmp_path / "schema")
    manifest = store.write(_evidence())
    payload_path, manifest_path = _artifact_paths(store)

    manifest_path.write_bytes(b"{}")
    with pytest.raises(EvidenceIntegrityError) as captured:
        store.read(manifest.record_key)
    assert str(captured.value) == "evidence manifest failed schema validation"

    # Restore a valid record before mutating one binding at a time.
    manifest_path.unlink()
    payload_path.unlink()
    store = LocalEvidenceStore(tmp_path / "schema-fresh")
    manifest = store.write(_evidence())
    payload_path, manifest_path = _artifact_paths(store)
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

    altered = dict(manifest_data)
    altered["record_key"] = "c" * 64
    manifest_path.write_bytes(_json_bytes(altered))
    with pytest.raises(EvidenceIntegrityError) as captured:
        store.read(manifest.record_key)
    assert str(captured.value) == "manifest record key does not match requested record"

    manifest_path.write_bytes(_json_bytes(manifest_data))
    altered = dict(manifest_data)
    altered["trial_id"] = "different-trial"
    manifest_path.write_bytes(_json_bytes(altered))
    with pytest.raises(EvidenceIntegrityError) as captured:
        store.read(manifest.record_key)
    assert str(captured.value) == ("manifest identity does not derive the requested record key")

    manifest_path.write_bytes(_json_bytes(manifest_data))
    altered = dict(manifest_data)
    altered["payload_bytes"] = manifest.payload_bytes + 1
    manifest_path.write_bytes(_json_bytes(altered))
    with pytest.raises(EvidenceIntegrityError) as captured:
        store.read(manifest.record_key)
    assert str(captured.value) == "manifest payload length does not match stored bytes"

    manifest_path.write_bytes(_json_bytes(manifest_data))
    altered = dict(manifest_data)
    altered["payload_sha256"] = "0" * 64
    manifest_path.write_bytes(_json_bytes(altered))
    with pytest.raises(EvidenceIntegrityError) as captured:
        store.read(manifest.record_key)
    assert str(captured.value) == ("stored evidence payload hash does not match manifest")


def test_bucket_symlink_diagnostic_is_exact(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    key = "a" * 64
    target = tmp_path / "target"
    target.mkdir()
    bucket = store.root / "records" / key[:2]
    bucket.symlink_to(target, target_is_directory=True)

    with pytest.raises(EvidenceIntegrityError) as captured:
        store.read(key)
    assert str(captured.value) == "evidence record bucket cannot be a symlink"


@pytest.mark.skipif(
    not getattr(os, "O_DIRECTORY", 0),
    reason="platform has no O_DIRECTORY durability contract",
)
def test_directory_fsync_uses_exact_open_flags_and_error_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = os.open
    expected_flags = os.O_RDONLY | os.O_DIRECTORY
    calls: list[int] = []

    def checked_open(path: object, flags: int, *args: object) -> int:
        calls.append(flags)
        assert flags == expected_flags
        return real_open(path, flags, *args)

    monkeypatch.setattr(store_module.os, "open", checked_open)
    store_module._fsync_directory(tmp_path)
    assert calls == [expected_flags]

    def failed_open(path: object, flags: int, *args: object) -> int:
        del path, flags, args
        raise OSError("controlled open failure")

    monkeypatch.setattr(store_module.os, "open", failed_open)
    with pytest.raises(EvidenceStoreError) as captured:
        store_module._fsync_directory(tmp_path)
    assert str(captured.value) == (
        f"cannot open evidence directory for durability sync: {tmp_path}"
    )


def test_subject_only_identity_mismatch_reports_identity_error_exactly(
    tmp_path: Path,
) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    manifest = store.write(_evidence())
    payload_path, manifest_path = _artifact_paths(store)
    payload_data = json.loads(payload_path.read_text(encoding="utf-8"))
    payload_data["subject_identity"] = "c" * 64
    _rewrite_payload_and_manifest(payload_path, manifest_path, payload_data)

    with pytest.raises(EvidenceIntegrityError) as captured:
        store.read(manifest.record_key)

    assert str(captured.value) == "stored evidence identity does not match manifest"


def test_payload_schema_failure_diagnostic_is_exact(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    manifest = store.write(_evidence())
    payload_path, manifest_path = _artifact_paths(store)
    payload_data = json.loads(payload_path.read_text(encoding="utf-8"))
    payload_data["input_tokens"] = -1
    _rewrite_payload_and_manifest(payload_path, manifest_path, payload_data)

    with pytest.raises(EvidenceIntegrityError) as captured:
        store.read(manifest.record_key)

    assert str(captured.value) == "stored evidence payload failed schema validation"


def test_payload_root_failure_diagnostic_is_exact(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    manifest = store.write(_evidence())
    payload_path, manifest_path = _artifact_paths(store)
    payload_data = json.loads(payload_path.read_text(encoding="utf-8"))
    payload_data["final_output"] = "valid-but-different"
    _rewrite_payload_and_manifest(payload_path, manifest_path, payload_data)

    with pytest.raises(EvidenceIntegrityError) as captured:
        store.read(manifest.record_key)

    assert str(captured.value) == "stored evidence root does not match manifest"


def test_directory_inspection_oserror_diagnostic_is_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "existing"
    root.mkdir()
    real_is_symlink = Path.is_symlink
    real_lstat = Path.lstat

    def is_symlink(path: Path) -> bool:
        if path == root:
            return False
        return real_is_symlink(path)

    def fail_root_lstat(path: Path) -> os.stat_result:
        if path == root:
            raise OSError("controlled inspection failure")
        return real_lstat(path)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)
    monkeypatch.setattr(Path, "lstat", fail_root_lstat)

    with pytest.raises(EvidenceIntegrityError) as captured:
        store_module._ensure_store_directory(root)

    assert str(captured.value) == f"cannot inspect evidence-store directory: {root}"


@pytest.mark.skipif(os.name != "posix", reason="POSIX private-directory contract")
def test_directory_chmod_oserror_diagnostic_is_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "private-root"
    real_chmod = Path.chmod

    def fail_root_chmod(path: Path, mode: int) -> None:
        if path == root:
            raise OSError("controlled chmod failure")
        real_chmod(path, mode)

    monkeypatch.setattr(Path, "chmod", fail_root_chmod)

    with pytest.raises(EvidenceIntegrityError) as captured:
        store_module._ensure_store_directory(root)

    assert str(captured.value) == (
        f"cannot set private permissions on evidence-store directory: {root}"
    )


def test_release_lock_inspection_oserror_diagnostic_is_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    lock_path = store.root / "records" / "inspect-error.lock"
    lock_fd = store._acquire_lock(lock_path)
    real_lstat = Path.lstat

    def fail_lock_lstat(path: Path) -> os.stat_result:
        if path == lock_path:
            raise OSError("controlled lock inspection failure")
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", fail_lock_lstat)

    with pytest.raises(EvidenceIntegrityError) as captured:
        store_module._release_lock(lock_path, lock_fd)

    assert str(captured.value) == ("cannot inspect record lock before release: inspect-error.lock")


def test_release_lock_disappearance_diagnostic_is_exact(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    lock_path = store.root / "records" / "disappeared.lock"
    lock_fd = store._acquire_lock(lock_path)
    lock_path.unlink()

    with pytest.raises(EvidenceIntegrityError) as captured:
        store_module._release_lock(lock_path, lock_fd)

    assert str(captured.value) == ("record lock disappeared before release: disappeared.lock")


def test_nonregular_lock_identity_diagnostic_is_exact(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    lock_path = store.root / "records" / "identity.lock"
    lock_fd = store._acquire_lock(lock_path)
    try:
        acquired = os.fstat(lock_fd)
        current = tmp_path.stat()

        with pytest.raises(EvidenceIntegrityError) as captured:
            store_module._verify_lock_identity(lock_path, acquired, current)

        assert str(captured.value) == (
            "record lock ownership changed before release: identity.lock; refusing cleanup"
        )
    finally:
        os.close(lock_fd)
        lock_path.unlink()


def test_safe_open_oserror_diagnostic_is_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "blocked.evidence.json"
    artifact.write_bytes(b"{}")
    real_open = store_module.os.open

    def denied_open(path: object, flags: int, *args: object) -> int:
        if path == artifact:
            raise PermissionError("controlled safe-open denial")
        return real_open(path, flags, *args)  # type: ignore[arg-type]

    monkeypatch.setattr(store_module.os, "open", denied_open)

    with pytest.raises(EvidenceIntegrityError) as captured:
        store_module._safe_read_regular_file(artifact, 1024)

    assert str(captured.value) == ("cannot safely open evidence artifact: blocked.evidence.json")


@pytest.mark.skipif(
    not getattr(os, "O_DIRECTORY", 0),
    reason="platform has no directory-open flag",
)
def test_directory_sync_open_oserror_diagnostic_is_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = store_module.os.open

    def denied_open(path: object, flags: int, *args: object) -> int:
        if path == tmp_path:
            raise PermissionError("controlled directory-open denial")
        return real_open(path, flags, *args)  # type: ignore[arg-type]

    monkeypatch.setattr(store_module.os, "open", denied_open)

    with pytest.raises(EvidenceStoreError) as captured:
        store_module._fsync_directory(tmp_path)

    assert str(captured.value) == (
        f"cannot open evidence directory for durability sync: {tmp_path}"
    )
