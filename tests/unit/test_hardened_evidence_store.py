from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agent_evals.evidence.hardened_store import HardenedPosixEvidenceStore
from agent_evals.evidence.models import TrialEvidence
from agent_evals.evidence.resilience import detect_platform_capabilities
from agent_evals.evidence.store import (
    EvidenceIntegrityError,
    LocalEvidenceStore,
    evidence_record_key,
)

SUBJECT = "a" * 64
SCENARIO = "b" * 64
_CAPABILITIES = detect_platform_capabilities()

pytestmark = pytest.mark.skipif(
    not _CAPABILITIES.hardened_posix_available,
    reason="runtime does not provide the hardened POSIX dir_fd contract",
)


def _evidence(trial_id: str = "hardened-store") -> TrialEvidence:
    return TrialEvidence(
        trial_id=trial_id,
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        final_state={"status": "ok", "trial": trial_id},
    )


def test_hardened_store_preserves_portable_manifest_and_payload_identity(tmp_path: Path) -> None:
    item = _evidence()
    portable = LocalEvidenceStore(tmp_path / "portable")
    hardened = HardenedPosixEvidenceStore(tmp_path / "hardened")

    portable_manifest = portable.write(item)
    hardened_manifest = hardened.write(item)

    assert hardened_manifest == portable_manifest
    assert hardened.read(hardened_manifest.record_key).evidence == item
    assert portable.read(portable_manifest.record_key).evidence == item

    key = hardened_manifest.record_key
    portable_bucket = portable.root / "records" / key[:2]
    hardened_bucket = hardened.root / "records" / key[:2]
    assert (hardened_bucket / f"{key}.evidence.json").read_bytes() == (
        portable_bucket / f"{key}.evidence.json"
    ).read_bytes()
    assert (hardened_bucket / f"{key}.manifest.json").read_bytes() == (
        portable_bucket / f"{key}.manifest.json"
    ).read_bytes()


def test_hardened_store_rejects_symlink_record_bucket(tmp_path: Path) -> None:
    hardened = HardenedPosixEvidenceStore(tmp_path / "hardened")
    item = _evidence()
    record_key = evidence_record_key(item)

    external = tmp_path / "external"
    external.mkdir()
    bucket = hardened.root / "records" / record_key[:2]
    bucket.symlink_to(external, target_is_directory=True)

    with pytest.raises(EvidenceIntegrityError, match="record bucket"):
        hardened.write(item)
    assert tuple(external.iterdir()) == ()


def test_hardened_store_rejects_symlink_payload_without_following_target(tmp_path: Path) -> None:
    hardened = HardenedPosixEvidenceStore(tmp_path / "hardened")
    manifest = hardened.write(_evidence())
    bucket = hardened.root / "records" / manifest.record_key[:2]
    payload = bucket / f"{manifest.record_key}.evidence.json"
    target = tmp_path / "outside.json"
    target.write_text('{"outside":true}', encoding="utf-8")
    payload.unlink()
    payload.symlink_to(target)

    with pytest.raises(EvidenceIntegrityError, match="safely open hardened"):
        hardened.read(manifest.record_key)
    assert target.read_text(encoding="utf-8") == '{"outside":true}'


def test_hardened_store_artifact_operations_are_anchored_to_directory_fds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hardened = HardenedPosixEvidenceStore(tmp_path / "hardened")
    real_open = os.open
    observed: list[tuple[object, int | None]] = []

    def checked_open(
        path: object,
        flags: int,
        mode: int = 0o600,
        *,
        dir_fd: int | None = None,
    ) -> int:
        observed.append((path, dir_fd))
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(
        "agent_evals.evidence.hardened_store.os.open",
        checked_open,
    )

    manifest = hardened.write(_evidence())
    hardened.read(manifest.record_key)

    anchored_names = {
        str(path)
        for path, dir_fd in observed
        if dir_fd is not None and isinstance(path, str)
    }
    assert manifest.record_key[:2] in anchored_names
    assert f"{manifest.record_key}.lock" in anchored_names
    assert f"{manifest.record_key}.evidence.json" in anchored_names
    assert f"{manifest.record_key}.manifest.json" in anchored_names


def test_hardened_store_concurrent_record_keys_remain_independent(tmp_path: Path) -> None:
    hardened = HardenedPosixEvidenceStore(tmp_path / "hardened")
    items = tuple(_evidence(f"hardened-{index}") for index in range(24))

    with ThreadPoolExecutor(max_workers=8) as pool:
        manifests = tuple(pool.map(hardened.write, items))

    assert len({manifest.record_key for manifest in manifests}) == len(items)
    for item, manifest in zip(items, manifests, strict=True):
        assert hardened.read(manifest.record_key).evidence == item
