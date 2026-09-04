from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_evals.evidence.models import TrialEvidence
from agent_evals.evidence.store import ArtifactManifest, EvidenceIntegrityError, LocalEvidenceStore

SUBJECT = "a" * 64
SCENARIO = "b" * 64


def _evidence() -> TrialEvidence:
    return TrialEvidence(
        trial_id="manifest-strictness",
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
    )


def _manifest_data(payload_bytes: object) -> dict[str, object]:
    return {
        "schema_version": "agent-evals-evidence-manifest/v1",
        "evidence_schema": "agent-evals/trial-evidence/v2",
        "record_key": "c" * 64,
        "trial_id": "manifest-strictness",
        "subject_identity": SUBJECT,
        "scenario_identity": SCENARIO,
        "evidence_root": "d" * 64,
        "payload_sha256": "e" * 64,
        "payload_bytes": payload_bytes,
    }


@pytest.mark.parametrize("payload_bytes", [True, "123", 123.0, 123.5])
def test_manifest_payload_bytes_rejects_coercive_runtime_types(payload_bytes: object) -> None:
    with pytest.raises(ValidationError):
        ArtifactManifest.model_validate(_manifest_data(payload_bytes))


def test_store_rejects_same_value_string_payload_bytes_in_persisted_manifest(
    tmp_path: Path,
) -> None:
    store = LocalEvidenceStore(tmp_path / "evidence")
    manifest = store.write(_evidence())
    path = next(store.root.rglob("*.manifest.json"))
    content = json.loads(path.read_text(encoding="utf-8"))
    content["payload_bytes"] = str(content["payload_bytes"])
    path.write_text(
        json.dumps(content, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(EvidenceIntegrityError, match="manifest failed schema validation"):
        store.read(manifest.record_key)
