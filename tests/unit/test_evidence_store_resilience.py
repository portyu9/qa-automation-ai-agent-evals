from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_evals.evidence import store as store_module
from agent_evals.evidence.models import TrialEvidence
from agent_evals.evidence.resilience import (
    EvidenceLockObservation,
    EvidenceStorePlatformCapabilities,
    EvidenceStorePlatformMode,
    detect_platform_capabilities,
    inspect_record_lock,
    quarantine_record_lock,
    require_platform_mode,
)
from agent_evals.evidence.store import (
    EvidenceIntegrityError,
    EvidenceStoreBusyError,
    EvidenceStoreError,
    IncompleteEvidenceRecordError,
    LocalEvidenceStore,
    evidence_record_key,
)

SUBJECT = "a" * 64
SCENARIO = "b" * 64


def _evidence(trial_id: str = "resilience-trial") -> TrialEvidence:
    return TrialEvidence(
        trial_id=trial_id,
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        final_state={"status": "ok", "trial": trial_id},
    )


def test_platform_contract_is_runtime_derived_and_portable_mode_always_explicit() -> None:
    capabilities = detect_platform_capabilities()

    assert capabilities.os_name == os.name
    assert capabilities.posix is (os.name == "posix")
    assert require_platform_mode(EvidenceStorePlatformMode.PORTABLE) == capabilities


def test_hardened_platform_request_fails_closed_when_capability_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unavailable = EvidenceStorePlatformCapabilities(
        os_name="controlled",
        posix=False,
        o_directory=False,
        o_nofollow=False,
        open_dir_fd=False,
        mkdir_dir_fd=False,
        stat_dir_fd=False,
        stat_nofollow=False,
        link_dir_fd=False,
        link_nofollow=False,
        unlink_dir_fd=False,
        rename_dir_fd=False,
    )
    monkeypatch.setattr(
        "agent_evals.evidence.resilience.detect_platform_capabilities",
        lambda: unavailable,
    )

    with pytest.raises(EvidenceStoreError, match="hardened_posix"):
        require_platform_mode(EvidenceStorePlatformMode.HARDENED_POSIX)


def test_lock_quarantine_requires_exact_reviewed_identity_and_preserves_audit_copy(
    tmp_path: Path,
) -> None:
    store = LocalEvidenceStore(tmp_path / "store")
    item = _evidence()
    key = evidence_record_key(item)
    paths = store._paths(key, create_bucket=True)
    fd = store._acquire_lock(paths.lock)
    os.close(fd)

    observation = inspect_record_lock(store, key)
    receipt = quarantine_record_lock(
        store,
        observation,
        confirm_observation_root=observation.observation_root,
    )

    assert receipt.record_key == key
    assert receipt.observation_root == observation.observation_root
    assert not paths.lock.exists()
    quarantine = store.root / "quarantine" / "locks" / receipt.quarantine_name
    assert quarantine.is_file()
    assert quarantine.stat().st_ino == observation.inode


def test_lock_quarantine_refuses_confirmation_mismatch_and_changed_lock(
    tmp_path: Path,
) -> None:
    store = LocalEvidenceStore(tmp_path / "store")
    key = evidence_record_key(_evidence())
    paths = store._paths(key, create_bucket=True)
    fd = store._acquire_lock(paths.lock)
    os.close(fd)
    observation = inspect_record_lock(store, key)

    with pytest.raises(ValueError, match="exact observation-root"):
        quarantine_record_lock(
            store,
            observation,
            confirm_observation_root="0" * 64,
        )
    assert paths.lock.exists()

    paths.lock.unlink()
    paths.lock.write_bytes(b"replacement")
    with pytest.raises(EvidenceIntegrityError, match="changed after operator observation"):
        quarantine_record_lock(
            store,
            observation,
            confirm_observation_root=observation.observation_root,
        )
    assert paths.lock.read_bytes() == b"replacement"


def test_lock_recovery_roots_have_stable_nul_domain_separation() -> None:
    observation = EvidenceLockObservation.create(
        record_key="a" * 64,
        device=1,
        inode=2,
        size_bytes=3,
        mtime_ns=4,
    )
    assert (
        observation.observation_root
        == "6abfd55ed35c54033756fc4f5d9bf2ff6443340f4fe180bbfe8153bca6e00ccb"
    )

    from agent_evals.evidence.resilience import EvidenceLockQuarantineReceipt

    receipt = EvidenceLockQuarantineReceipt.create(
        record_key="a" * 64,
        observation_root=observation.observation_root,
        quarantine_name=(
            "a" * 64 + "." + observation.observation_root[:16] + ".lock"
        ),
    )
    assert (
        receipt.receipt_root
        == "e062f639d4f9b07498eb05fe1426e1a421c2d798d3fb3890affef1346df8f8fa"
    )


def test_lock_observation_root_detects_tampering(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "store")
    key = evidence_record_key(_evidence())
    paths = store._paths(key, create_bucket=True)
    fd = store._acquire_lock(paths.lock)
    os.close(fd)
    observation = inspect_record_lock(store, key)

    with pytest.raises(ValueError, match="observation root mismatch"):
        EvidenceLockObservation.model_validate(
            {
                **observation.model_dump(mode="json"),
                "size_bytes": observation.size_bytes + 1,
            }
        )


@pytest.mark.parametrize(
    ("fail_call", "after_publish", "expected_presence"),
    [
        (1, False, "absent"),
        (1, True, "partial"),
        (2, False, "partial"),
        (2, True, "complete"),
    ],
)
def test_record_publication_crash_simulation_is_absent_partial_or_verified_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_call: int,
    after_publish: bool,
    expected_presence: str,
) -> None:
    store = LocalEvidenceStore(tmp_path / "store")
    item = _evidence()
    key = evidence_record_key(item)
    real_materialize = store_module._atomic_materialize
    calls = 0

    def controlled_materialize(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == fail_call and not after_publish:
            raise EvidenceStoreError("controlled publication crash")
        real_materialize(path, content)
        if calls == fail_call and after_publish:
            raise EvidenceStoreError("controlled publication crash")

    monkeypatch.setattr(store_module, "_atomic_materialize", controlled_materialize)

    with pytest.raises(EvidenceStoreError, match="controlled publication crash"):
        store.write(item)

    paths = store._paths(key, create_bucket=False)
    assert store._presence(paths) == expected_presence
    assert not paths.lock.exists()
    if expected_presence == "complete":
        assert store.read(key).evidence == item
    else:
        with pytest.raises(IncompleteEvidenceRecordError):
            store.read(key)


def test_concurrent_same_key_writers_never_clobber_and_finish_verified(
    tmp_path: Path,
) -> None:
    store = LocalEvidenceStore(tmp_path / "store")
    item = _evidence()
    results: list[str] = []
    result_lock = threading.Lock()

    def write_once() -> None:
        try:
            manifest = store.write(item)
            outcome = f"ok:{manifest.evidence_root}"
        except EvidenceStoreBusyError:
            outcome = "busy"
        with result_lock:
            results.append(outcome)

    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda _: write_once(), range(48)))

    assert len(results) == 48
    assert any(result.startswith("ok:") for result in results)
    assert all(result == "busy" or result.endswith(item.evidence_root) for result in results)
    assert store.read(evidence_record_key(item)).evidence == item


def test_concurrent_independent_key_writers_all_publish_without_cross_record_interference(
    tmp_path: Path,
) -> None:
    store = LocalEvidenceStore(tmp_path / "store")
    items = tuple(_evidence(f"trial-{index}") for index in range(32))

    with ThreadPoolExecutor(max_workers=12) as pool:
        manifests = tuple(pool.map(store.write, items))

    assert len({manifest.record_key for manifest in manifests}) == len(items)
    for item, manifest in zip(items, manifests, strict=True):
        assert store.read(manifest.record_key).evidence == item


def test_reader_observes_explicit_partial_state_during_payload_before_manifest_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalEvidenceStore(tmp_path / "store")
    item = _evidence()
    key = evidence_record_key(item)
    real_materialize = store_module._atomic_materialize
    payload_published = threading.Event()
    allow_manifest = threading.Event()
    calls = 0

    def paused_materialize(path: Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        real_materialize(path, content)
        if calls == 1:
            payload_published.set()
            assert allow_manifest.wait(timeout=10)

    monkeypatch.setattr(store_module, "_atomic_materialize", paused_materialize)

    failure: list[BaseException] = []

    def writer() -> None:
        try:
            store.write(item)
        except BaseException as exc:  # pragma: no cover - surfaced by assertion below
            failure.append(exc)

    thread = threading.Thread(target=writer)
    thread.start()
    assert payload_published.wait(timeout=10)

    with pytest.raises(IncompleteEvidenceRecordError):
        store.read(key)

    allow_manifest.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert failure == []
    assert store.read(key).evidence == item


@pytest.mark.parametrize(
    ("failure_stage", "published"),
    [
        ("write", False),
        ("file_fsync", False),
        ("link", False),
        ("post_link_directory_fsync", True),
        ("temporary_unlink", True),
        ("post_unlink_directory_fsync", True),
    ],
)
def test_atomic_materialize_failure_boundaries_never_create_ambiguous_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
    published: bool,
) -> None:
    target = tmp_path / "artifact.bin"
    content = b"immutable-evidence"
    real_fsync = store_module.os.fsync
    real_unlink = Path.unlink
    fsync_calls = 0
    unlink_failed = False

    if failure_stage == "write":

        def fail_write(fd: int, data: bytes) -> int:
            del fd, data
            raise OSError("controlled write failure")

        monkeypatch.setattr(store_module.os, "write", fail_write)

    if failure_stage in {
        "file_fsync",
        "post_link_directory_fsync",
        "post_unlink_directory_fsync",
    }:
        target_call = {
            "file_fsync": 1,
            "post_link_directory_fsync": 2,
            "post_unlink_directory_fsync": 3,
        }[failure_stage]

        def fail_selected_fsync(fd: int) -> None:
            nonlocal fsync_calls
            fsync_calls += 1
            if fsync_calls == target_call:
                raise OSError("controlled fsync failure")
            real_fsync(fd)

        monkeypatch.setattr(store_module.os, "fsync", fail_selected_fsync)

    if failure_stage == "link":

        def fail_link(destination: Path, source: Path) -> None:
            del destination, source
            raise OSError("controlled link failure")

        monkeypatch.setattr(Path, "hardlink_to", fail_link)

    if failure_stage == "temporary_unlink":

        def fail_first_temp_unlink(
            candidate: Path,
            *args: object,
            **kwargs: object,
        ) -> None:
            nonlocal unlink_failed
            if candidate.name.startswith(".artifact.bin.") and not unlink_failed:
                unlink_failed = True
                raise OSError("controlled temp unlink failure")
            real_unlink(candidate, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", fail_first_temp_unlink)

    with pytest.raises((OSError, EvidenceStoreError)):
        store_module._atomic_materialize(target, content)

    assert target.exists() is published
    if published:
        assert target.read_bytes() == content
    assert tuple(tmp_path.glob(".artifact.bin.*.tmp")) == ()
