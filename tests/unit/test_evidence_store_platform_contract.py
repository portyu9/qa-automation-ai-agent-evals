from __future__ import annotations

from pathlib import Path

import pytest

from agent_evals.evidence.hardened_store import HardenedPosixEvidenceStore
from agent_evals.evidence.models import TrialEvidence
from agent_evals.evidence.resilience import (
    EvidenceStorePlatformMode,
    detect_platform_capabilities,
    require_platform_mode,
)
from agent_evals.evidence.store import EvidenceStoreError, LocalEvidenceStore


def _evidence(trial_id: str) -> TrialEvidence:
    return TrialEvidence(
        trial_id=trial_id,
        subject_identity="a" * 64,
        scenario_identity="b" * 64,
        final_state={"status": "ok"},
    )


def test_portable_store_round_trip_on_platform_runner(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "portable")
    original = _evidence("platform-portable")

    manifest = store.write(original)

    assert store.read(manifest.record_key).evidence == original


def test_hardened_posix_is_exercised_or_explicitly_rejected(tmp_path: Path) -> None:
    capabilities = detect_platform_capabilities()
    if not capabilities.hardened_posix_available:
        with pytest.raises(EvidenceStoreError, match="hardened_posix"):
            require_platform_mode(EvidenceStorePlatformMode.HARDENED_POSIX)
        return

    store = HardenedPosixEvidenceStore(tmp_path / "hardened")
    original = _evidence("platform-hardened")

    manifest = store.write(original)

    assert store.read(manifest.record_key).evidence == original
