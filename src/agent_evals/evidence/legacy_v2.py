"""Verification-only compatibility for historical TrialEvidence/v2 timestamp encodings.

Current evidence requires timezone-aware UTC-normalized ``observed_at`` values. Historical v2
records could contain aware non-UTC offsets or naive datetimes, and their serialized timestamp text
was hashed into each event digest. This module can rederive those historical roots without making
noncanonical timestamps acceptable to current evidence ingestion, replay, grading, or persistence.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import ValidationError

from agent_evals.evidence.models import _validate_historical_v2_evidence_json
from agent_evals.evidence.store import (
    ArtifactManifest,
    EvidenceIntegrityError,
    IncompleteEvidenceRecordError,
    LocalEvidenceStore,
    _record_key,
    _safe_read_regular_file,
    _validate_record_key,
)

_EVIDENCE_ROOT_DOMAIN = b"agent-evals/trial-evidence/v2\0"


def verify_historical_v2_record(
    store: LocalEvidenceStore,
    record_key: str,
) -> ArtifactManifest:
    """Verify one persisted v2 record without returning gradeable current evidence.

    The function reuses the local store's bounded/symlink-aware artifact reads and current
    structural/resource validation. Its only compatibility allowance is historical timestamp
    representation during schema validation. Root derivation uses the persisted JSON values so an
    old offset or naive timestamp is verified exactly as it was originally hashed.

    Successful return proves consistency between the stored payload, manifest, identity, and
    historical v2 root. It does not upgrade unsigned hashes to authentication, infer a timezone for
    naive timestamps, migrate the record, or authorize the record for current replay/grading.
    """

    _validate_record_key(record_key)
    paths = store._paths(record_key, create_bucket=False)
    if store._presence(paths) != "complete":
        raise IncompleteEvidenceRecordError(
            f"record key {record_key} does not have both payload and manifest"
        )

    manifest_bytes = _safe_read_regular_file(paths.manifest, store._max_manifest_bytes)
    payload = _safe_read_regular_file(paths.payload, store._max_payload_bytes)

    try:
        manifest = ArtifactManifest.model_validate_json(manifest_bytes)
    except ValidationError as exc:
        raise EvidenceIntegrityError("evidence manifest failed schema validation") from exc

    if manifest.record_key != record_key:
        raise EvidenceIntegrityError("manifest record key does not match requested record")
    expected_key = _record_key(
        trial_id=manifest.trial_id,
        subject_identity=manifest.subject_identity,
        scenario_identity=manifest.scenario_identity,
    )
    if expected_key != record_key:
        raise EvidenceIntegrityError("manifest identity does not derive the requested record key")
    if manifest.payload_bytes != len(payload):
        raise EvidenceIntegrityError("manifest payload length does not match stored bytes")
    if manifest.payload_sha256 != hashlib.sha256(payload).hexdigest():
        raise EvidenceIntegrityError("stored evidence payload hash does not match manifest")

    try:
        evidence = _validate_historical_v2_evidence_json(payload)
    except ValidationError as exc:
        raise EvidenceIntegrityError(
            "historical v2 evidence payload failed schema validation"
        ) from exc

    if (
        evidence.trial_id != manifest.trial_id
        or evidence.subject_identity != manifest.subject_identity
        or evidence.scenario_identity != manifest.scenario_identity
    ):
        raise EvidenceIntegrityError("stored evidence identity does not match manifest")

    try:
        raw = json.loads(payload)
        historical_root = _historical_v2_root(raw)
    except (KeyError, TypeError, ValueError) as exc:
        raise EvidenceIntegrityError("historical v2 evidence root material is malformed") from exc
    if historical_root != manifest.evidence_root:
        raise EvidenceIntegrityError("stored historical v2 evidence root does not match manifest")

    return manifest


def _historical_v2_root(raw: Any) -> str:
    if not isinstance(raw, dict):
        raise TypeError("historical v2 evidence must be a JSON object")
    events = raw["events"]
    if not isinstance(events, list):
        raise TypeError("historical v2 events must be a JSON array")

    envelope_identity = _canonical_json_bytes(
        {
            "trial_id": raw["trial_id"],
            "subject_identity": raw["subject_identity"],
            "scenario_identity": raw["scenario_identity"],
        }
    )
    chain = hashlib.sha256(_EVIDENCE_ROOT_DOMAIN + envelope_identity).digest()
    for event in events:
        if not isinstance(event, dict):
            raise TypeError("historical v2 event must be a JSON object")
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
