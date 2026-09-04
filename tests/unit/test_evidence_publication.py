from __future__ import annotations

from pathlib import Path

import pytest

from agent_evals.evidence.models import TrialEvidence
from agent_evals.evidence.store import EvidenceConflictError, LocalEvidenceStore


def test_atomic_publication_does_not_overwrite_racing_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    evidence = TrialEvidence(
        trial_id="publication-race",
        subject_identity="a" * 64,
        scenario_identity="b" * 64,
        final_state={"status": "ok"},
    )
    real_hardlink_to = Path.hardlink_to
    injected = False

    def racing_hardlink(destination: Path, source: Path) -> None:
        nonlocal injected
        if not injected and destination.name.endswith(".evidence.json"):
            injected = True
            destination.write_bytes(b"competing-writer")
        real_hardlink_to(destination, source)

    monkeypatch.setattr(Path, "hardlink_to", racing_hardlink)

    with pytest.raises(EvidenceConflictError, match="appeared during publication"):
        store.write(evidence)

    payloads = tuple(store.root.rglob("*.evidence.json"))
    assert len(payloads) == 1
    assert payloads[0].read_bytes() == b"competing-writer"
    assert not tuple(store.root.rglob("*.manifest.json"))
