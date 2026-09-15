from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_evals.evidence.legacy_v2 import verify_historical_v2_record
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.evidence.store import ArtifactManifest, EvidenceIntegrityError, LocalEvidenceStore

_SUBJECT = "a" * 64
_SCENARIO = "b" * 64
_EVIDENCE_ROOT_DOMAIN = b"agent-evals/trial-evidence/v2\0"


def test_current_store_persists_offset_input_as_canonical_utc(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    observed = datetime(2026, 9, 10, 18, 30, tzinfo=timezone(timedelta(hours=-4)))
    evidence = TrialEvidence(
        trial_id="current-utc",
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.STATE,
                source="fixture",
                observed_at=observed,
            ),
        ),
    )

    manifest = store.write(evidence)
    payload = next(store.root.rglob("*.evidence.json")).read_bytes()
    loaded = store.read(manifest.record_key)

    assert b'"observed_at":"2026-09-10T22:30:00Z"' in payload
    assert loaded.evidence.events[0].observed_at == observed.astimezone(UTC)
    assert loaded.evidence.events[0].observed_at.tzinfo is UTC
    assert loaded.evidence.evidence_root == manifest.evidence_root


def test_historical_v2_verifier_preserves_non_utc_root_without_current_replay(
    tmp_path: Path,
) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    key, expected_root = _materialize_historical_v2_record(
        store,
        observed_at="2026-09-10T18:30:00-04:00",
        trial_id="historical-offset",
    )

    # Current parsing canonicalizes the instant to UTC, so it must not silently reinterpret the
    # old root under unchanged TrialEvidence/v2 semantics.
    with pytest.raises(EvidenceIntegrityError, match="root does not match"):
        store.read(key)

    manifest = verify_historical_v2_record(store, key)
    assert manifest.record_key == key
    assert manifest.evidence_root == expected_root


def test_historical_v2_verifier_can_verify_old_naive_timestamp_without_upgrading_it(
    tmp_path: Path,
) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    key, expected_root = _materialize_historical_v2_record(
        store,
        observed_at="2026-09-10T22:30:00",
        trial_id="historical-naive",
    )

    # A naive historical timestamp has no knowable UTC instant. Current evidence therefore rejects
    # it, while the compatibility verifier can still prove that the stored v2 bytes match their
    # historical manifest/root without manufacturing a timezone assumption.
    with pytest.raises(EvidenceIntegrityError, match="schema validation"):
        store.read(key)

    manifest = verify_historical_v2_record(store, key)
    assert manifest.evidence_root == expected_root


def test_historical_v2_verifier_still_rejects_root_mismatch(tmp_path: Path) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    key, _ = _materialize_historical_v2_record(
        store,
        observed_at="2026-09-10T18:30:00-04:00",
        trial_id="historical-tampered-root",
        manifest_root="f" * 64,
    )

    with pytest.raises(EvidenceIntegrityError, match="historical v2 evidence root"):
        verify_historical_v2_record(store, key)


def _materialize_historical_v2_record(
    store: LocalEvidenceStore,
    *,
    observed_at: str,
    trial_id: str,
    manifest_root: str | None = None,
) -> tuple[str, str]:
    raw = {
        "trial_id": trial_id,
        "subject_identity": _SUBJECT,
        "scenario_identity": _SCENARIO,
        "events": [
            {
                "sequence": 0,
                "kind": "state",
                "source": "fixture",
                "payload": {"observed": True},
                "observed_at": observed_at,
                "critical": False,
            }
        ],
        "final_state": {"status": "ok"},
        "final_output": "done",
        "elapsed_ms": 0.0,
        "input_tokens": 7,
        "output_tokens": 3,
        "estimated_cost_usd": 0.0,
    }
    payload = _canonical_json_bytes(raw)
    evidence_root = _historical_v2_root(raw)
    record_key = hashlib.sha256(
        _canonical_json_bytes(
            {
                "trial_id": trial_id,
                "subject_identity": _SUBJECT,
                "scenario_identity": _SCENARIO,
            }
        )
    ).hexdigest()
    manifest = ArtifactManifest(
        record_key=record_key,
        trial_id=trial_id,
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        evidence_root=manifest_root or evidence_root,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        payload_bytes=len(payload),
    )

    bucket = store.root / "records" / record_key[:2]
    bucket.mkdir(mode=0o700)
    (bucket / f"{record_key}.evidence.json").write_bytes(payload)
    (bucket / f"{record_key}.manifest.json").write_bytes(
        _canonical_json_bytes(manifest.model_dump(mode="json"))
    )
    return record_key, evidence_root


def _historical_v2_root(raw: dict[str, object]) -> str:
    envelope_identity = _canonical_json_bytes(
        {
            "trial_id": raw["trial_id"],
            "subject_identity": raw["subject_identity"],
            "scenario_identity": raw["scenario_identity"],
        }
    )
    chain = hashlib.sha256(_EVIDENCE_ROOT_DOMAIN + envelope_identity).digest()
    events = raw["events"]
    assert isinstance(events, list)
    for event in events:
        event_digest = hashlib.sha256(_canonical_json_bytes(event)).digest()
        chain = hashlib.sha256(chain + event_digest).digest()
    terminal = _canonical_json_bytes(
        {
            "final_state": raw["final_state"],
            "final_output": raw["final_output"],
            "elapsed_ms": raw["elapsed_ms"],
            "input_tokens": raw["input_tokens"],
            "output_tokens": raw["output_tokens"],
            "estimated_cost_usd": raw["estimated_cost_usd"],
        }
    )
    return hashlib.sha256(_EVIDENCE_ROOT_DOMAIN + chain + terminal).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
