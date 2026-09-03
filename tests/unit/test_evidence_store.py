from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.evidence.store import (
    EvidenceConflictError,
    EvidenceIntegrityError,
    EvidenceStoreResourceError,
    IncompleteEvidenceRecordError,
    LocalEvidenceStore,
    evidence_record_key,
)

SUBJECT = "a" * 64
SCENARIO = "b" * 64


def evidence(
    *,
    trial_id: str = "trial-1",
    state: dict[str, object] | None = None,
) -> TrialEvidence:
    return TrialEvidence(
        trial_id=trial_id,
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.STATE,
                source="environment",
                payload={"observed": True},
            ),
        ),
        final_state=state or {"status": "ok"},
        final_output="done",
        input_tokens=7,
        output_tokens=3,
    )


def test_store_round_trip_manifest_and_idempotent_write(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    original = evidence()

    manifest = store.write(original)
    loaded = store.read(manifest.record_key)
    repeated = store.write(original)

    assert manifest == repeated
    assert loaded.evidence == original
    assert loaded.manifest.evidence_root == original.evidence_root
    assert loaded.manifest.payload_bytes > 0
    assert len(loaded.manifest.payload_sha256) == 64


def test_record_key_is_path_safe_even_when_trial_id_is_hostile(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    hostile = evidence(trial_id="../../escape/../trial")
    manifest = store.write(hostile)

    assert len(manifest.record_key) == 64
    assert set(manifest.record_key) <= set("0123456789abcdef")
    assert store.read(manifest.record_key).evidence.trial_id == hostile.trial_id
    for artifact in store.root.rglob("*"):
        artifact.relative_to(store.root)


def test_same_record_identity_cannot_be_rewritten_with_different_evidence(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    store.write(evidence(state={"status": "one"}))

    with pytest.raises(EvidenceConflictError, match="different immutable evidence"):
        store.write(evidence(state={"status": "two"}))


def test_tampered_payload_fails_integrity_verification(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    manifest = store.write(evidence())
    payload = next(store.root.rglob("*.evidence.json"))
    payload.write_bytes(b"{}")

    with pytest.raises(EvidenceIntegrityError, match=r"length|hash"):
        store.read(manifest.record_key)


def test_tampered_manifest_identity_fails_verification(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    manifest = store.write(evidence())
    path = next(store.root.rglob("*.manifest.json"))
    content = json.loads(path.read_text(encoding="utf-8"))
    content["trial_id"] = "different-trial"
    path.write_text(json.dumps(content), encoding="utf-8")

    with pytest.raises(EvidenceIntegrityError, match="identity"):
        store.read(manifest.record_key)


def test_partial_record_is_explicitly_incomplete_and_not_repaired(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    original = evidence()
    manifest = store.write(original)
    next(store.root.rglob("*.manifest.json")).unlink()

    with pytest.raises(IncompleteEvidenceRecordError):
        store.read(manifest.record_key)
    with pytest.raises(IncompleteEvidenceRecordError, match="refusing automatic overwrite"):
        store.write(original)


def test_payload_resource_ceiling_applies_before_persistence(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence", max_payload_bytes=64)
    with pytest.raises(EvidenceStoreResourceError, match="maximum"):
        store.write(evidence(state={"large": "x" * 512}))


def test_invalid_record_key_is_rejected_before_filesystem_lookup(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    with pytest.raises(EvidenceIntegrityError, match="64 lowercase hexadecimal"):
        store.read("../../not-a-key")


def test_root_symlink_is_rejected_when_platform_supports_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "evidence-link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    with pytest.raises(EvidenceIntegrityError, match="cannot be a symlink"):
        LocalEvidenceStore(link)


def test_record_key_changes_with_bound_evaluation_identity() -> None:
    first = evidence()
    second = first.model_copy(update={"subject_identity": "c" * 64})
    third = first.model_copy(update={"scenario_identity": "d" * 64})

    assert (
        len({evidence_record_key(first), evidence_record_key(second), evidence_record_key(third)})
        == 3
    )
