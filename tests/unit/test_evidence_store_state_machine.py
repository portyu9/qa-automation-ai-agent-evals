from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Literal

import pytest
from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

import agent_evals.evidence.store as store_module
from agent_evals.evidence.models import TrialEvidence
from agent_evals.evidence.store import (
    ArtifactManifest,
    EvidenceConflictError,
    EvidenceIntegrityError,
    EvidenceStoreBusyError,
    IncompleteEvidenceRecordError,
    LocalEvidenceStore,
    evidence_record_key,
)

_SUBJECT = "a" * 64
_SCENARIO = "b" * 64

ArtifactState = Literal[
    "absent",
    "committed",
    "payload_only",
    "manifest_only",
    "corrupt_payload",
    "corrupt_manifest",
]


def _evidence(status: str) -> TrialEvidence:
    return TrialEvidence(
        trial_id="state-machine-trial",
        subject_identity=_SUBJECT,
        scenario_identity=_SCENARIO,
        final_state={"status": status},
        final_output="done",
    )


class EvidenceStoreStateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self._temporary = tempfile.TemporaryDirectory()
        self.store = LocalEvidenceStore(Path(self._temporary.name) / "evidence")
        self.original = _evidence("original")
        self.conflicting = _evidence("conflicting")
        self.record_key = evidence_record_key(self.original)
        assert evidence_record_key(self.conflicting) == self.record_key

        self.paths = self.store._paths(self.record_key, create_bucket=True)
        self.expected_payload = store_module._canonical_json_bytes(
            self.original.snapshot().model_dump(mode="json")
        )
        self.expected_manifest = ArtifactManifest(
            record_key=self.record_key,
            trial_id=self.original.trial_id,
            subject_identity=self.original.subject_identity,
            scenario_identity=self.original.scenario_identity,
            evidence_root=self.original.evidence_root,
            payload_sha256=hashlib.sha256(self.expected_payload).hexdigest(),
            payload_bytes=len(self.expected_payload),
        )
        self.expected_manifest_bytes = store_module._canonical_json_bytes(
            self.expected_manifest.model_dump(mode="json")
        )
        self.artifact_state: ArtifactState = "absent"
        self.lock_present = False

    def teardown(self) -> None:
        self._temporary.cleanup()

    def _artifact_snapshot(self) -> tuple[bytes | None, bytes | None]:
        payload = self.paths.payload.read_bytes() if self.paths.payload.exists() else None
        manifest = self.paths.manifest.read_bytes() if self.paths.manifest.exists() else None
        return payload, manifest

    def _assert_read_behavior(self) -> None:
        if self.artifact_state == "committed":
            stored = self.store.read(self.record_key)
            assert stored.evidence == self.original
            assert stored.manifest == self.expected_manifest
        elif self.artifact_state in {"absent", "payload_only", "manifest_only"}:
            with pytest.raises(IncompleteEvidenceRecordError):
                self.store.read(self.record_key)
        else:
            with pytest.raises(EvidenceIntegrityError):
                self.store.read(self.record_key)

    @rule()
    def exercise_original_write(self) -> None:
        before = self._artifact_snapshot()
        if self.lock_present:
            with pytest.raises(EvidenceStoreBusyError):
                self.store.write(self.original)
            assert self._artifact_snapshot() == before
            return

        if self.artifact_state == "absent":
            manifest = self.store.write(self.original)
            assert manifest == self.expected_manifest
            self.artifact_state = "committed"
        elif self.artifact_state == "committed":
            manifest = self.store.write(self.original)
            assert manifest == self.expected_manifest
            assert self._artifact_snapshot() == before
        elif self.artifact_state in {"payload_only", "manifest_only"}:
            with pytest.raises(IncompleteEvidenceRecordError):
                self.store.write(self.original)
            assert self._artifact_snapshot() == before
        else:
            with pytest.raises(EvidenceIntegrityError):
                self.store.write(self.original)
            assert self._artifact_snapshot() == before

    @precondition(lambda self: self.artifact_state == "committed")
    @rule()
    def reject_conflicting_write(self) -> None:
        before = self._artifact_snapshot()
        if self.lock_present:
            with pytest.raises(EvidenceStoreBusyError):
                self.store.write(self.conflicting)
        else:
            with pytest.raises(EvidenceConflictError):
                self.store.write(self.conflicting)
        assert self._artifact_snapshot() == before

    @precondition(lambda self: self.artifact_state == "absent" and not self.lock_present)
    @rule()
    def materialize_payload_only_crash_state(self) -> None:
        self.paths.payload.write_bytes(self.expected_payload)
        self.artifact_state = "payload_only"

    @precondition(lambda self: self.artifact_state == "absent" and not self.lock_present)
    @rule()
    def materialize_manifest_only_crash_state(self) -> None:
        self.paths.manifest.write_bytes(self.expected_manifest_bytes)
        self.artifact_state = "manifest_only"

    @precondition(lambda self: self.artifact_state == "committed" and not self.lock_present)
    @rule()
    def corrupt_payload(self) -> None:
        self.paths.payload.write_bytes(b"{}")
        self.artifact_state = "corrupt_payload"

    @precondition(lambda self: self.artifact_state == "committed" and not self.lock_present)
    @rule()
    def corrupt_manifest(self) -> None:
        self.paths.manifest.write_bytes(b"{}")
        self.artifact_state = "corrupt_manifest"

    @precondition(
        lambda self: self.artifact_state
        in {"payload_only", "manifest_only", "corrupt_payload", "corrupt_manifest"}
        and not self.lock_present
    )
    @rule()
    def explicit_operator_discards_invalid_artifacts(self) -> None:
        self.paths.payload.unlink(missing_ok=True)
        self.paths.manifest.unlink(missing_ok=True)
        self.artifact_state = "absent"

    @precondition(lambda self: not self.lock_present)
    @rule()
    def add_stale_lock(self) -> None:
        self.paths.lock.write_text("operator-review-required", encoding="utf-8")
        self.lock_present = True

    @precondition(lambda self: self.lock_present)
    @rule()
    def explicit_operator_clears_stale_lock(self) -> None:
        self.paths.lock.unlink()
        self.lock_present = False

    @precondition(lambda self: not self.lock_present)
    @rule()
    def replacement_lock_is_not_unlinked(self) -> None:
        before = self._artifact_snapshot()
        fd = self.store._acquire_lock(self.paths.lock)
        self.paths.lock.unlink()
        self.paths.lock.write_text("replacement-owner", encoding="utf-8")

        with pytest.raises(EvidenceIntegrityError, match="lock ownership changed"):
            store_module._release_lock(self.paths.lock, fd)

        assert self.paths.lock.read_text(encoding="utf-8") == "replacement-owner"
        assert self._artifact_snapshot() == before
        self.lock_present = True

    @rule()
    def exercise_read(self) -> None:
        before = self._artifact_snapshot()
        self._assert_read_behavior()
        assert self._artifact_snapshot() == before

    @invariant()
    def filesystem_shape_matches_model(self) -> None:
        assert self.paths.lock.exists() is self.lock_present
        assert not tuple(self.store.root.rglob("*.tmp"))

        payload, manifest = self._artifact_snapshot()
        if self.artifact_state == "absent":
            assert payload is None
            assert manifest is None
        elif self.artifact_state == "committed":
            assert payload == self.expected_payload
            assert manifest == self.expected_manifest_bytes
        elif self.artifact_state == "payload_only":
            assert payload == self.expected_payload
            assert manifest is None
        elif self.artifact_state == "manifest_only":
            assert payload is None
            assert manifest == self.expected_manifest_bytes
        elif self.artifact_state == "corrupt_payload":
            assert payload == b"{}"
            assert manifest == self.expected_manifest_bytes
        else:
            assert self.artifact_state == "corrupt_manifest"
            assert payload == self.expected_payload
            assert manifest == b"{}"

    @invariant()
    def reads_never_promote_invalid_state(self) -> None:
        before = self._artifact_snapshot()
        self._assert_read_behavior()
        assert self._artifact_snapshot() == before


TestEvidenceStoreStateMachine = EvidenceStoreStateMachine.TestCase
TestEvidenceStoreStateMachine.settings = settings(
    max_examples=75,
    stateful_step_count=25,
    deadline=None,
)
