from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from agent_evals.evidence.blob_store import (
    ContentAddressedEvidenceStore,
    EvidenceBlobBackend,
    FilesystemBlobBackend,
    canonical_evidence_bytes,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.evidence.retention import (
    GarbageCollectionPlan,
    RetentionReferenceSet,
    execute_garbage_collection,
)

SUBJECT = "a" * 64
SCENARIO = "b" * 64


def _evidence(trial_id: str, *, payload: str = "value") -> TrialEvidence:
    return TrialEvidence(
        trial_id=trial_id,
        subject_identity=SUBJECT,
        scenario_identity=SCENARIO,
        events=(
            EvidenceEvent(
                sequence=0,
                kind=EvidenceKind.STATE,
                source="fixture",
                payload={"payload": payload},
            ),
        ),
        final_state={"done": True},
    )


@dataclass
class _RemoteMemoryBackend(EvidenceBlobBackend):
    objects: dict[str, bytes] = field(default_factory=dict)
    put_calls: int = 0

    def put_if_absent(self, key: str, content: bytes) -> bool:
        self.put_calls += 1
        if key in self.objects:
            return False
        self.objects[key] = bytes(content)
        return True

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def list_keys(self) -> tuple[str, ...]:
        return tuple(sorted(self.objects))

    def delete(self, key: str) -> bool:
        return self.objects.pop(key, None) is not None


@pytest.mark.parametrize("compression", ["none", "gzip"])
def test_content_addressed_store_hashes_canonical_uncompressed_content(
    compression: str,
) -> None:
    backend = _RemoteMemoryBackend()
    store = ContentAddressedEvidenceStore(backend, compression=compression)  # type: ignore[arg-type]
    evidence = _evidence("same")

    manifest = store.write(evidence)

    assert manifest.logical_sha256 == __import__("hashlib").sha256(
        canonical_evidence_bytes(evidence.snapshot())
    ).hexdigest()
    assert store.read(manifest.logical_sha256) == evidence.snapshot()
    assert manifest.evidence_root == evidence.evidence_root
    if compression == "gzip":
        assert manifest.compression == "gzip"


def test_repeated_identical_blob_is_deduplicated_without_overwrite() -> None:
    backend = _RemoteMemoryBackend()
    first = ContentAddressedEvidenceStore(backend, compression="none")
    second = ContentAddressedEvidenceStore(backend, compression="gzip")
    evidence = _evidence("dedup")

    manifest_a = first.write(evidence)
    object_before = backend.objects[manifest_a.logical_sha256]
    manifest_b = second.write(evidence)

    assert manifest_b.logical_sha256 == manifest_a.logical_sha256
    assert backend.put_calls == 2
    assert len(backend.objects) == 1
    assert backend.objects[manifest_a.logical_sha256] == object_before
    assert second.read(manifest_a.logical_sha256) == evidence.snapshot()


def test_remote_backend_corruption_fails_closed() -> None:
    backend = _RemoteMemoryBackend()
    store = ContentAddressedEvidenceStore(backend, compression="gzip")
    manifest = store.write(_evidence("corrupt"))
    backend.objects[manifest.logical_sha256] += b"tamper"

    with pytest.raises(Exception, match="blob|evidence|compressed|length|hash"):
        store.read(manifest.logical_sha256)


def test_filesystem_backend_preserves_no_clobber_semantics(tmp_path: Path) -> None:
    backend = FilesystemBlobBackend(tmp_path / "blobs")
    store = ContentAddressedEvidenceStore(backend)
    evidence = _evidence("filesystem")

    first = store.write(evidence)
    second = store.write(evidence)

    assert first == second
    assert backend.list_keys() == (first.logical_sha256,)


def test_reference_safe_gc_deletes_only_unreferenced_objects() -> None:
    backend = _RemoteMemoryBackend()
    store = ContentAddressedEvidenceStore(backend)
    keep = store.write(_evidence("keep"))
    drop = store.write(_evidence("drop"))
    references = RetentionReferenceSet.create((keep.logical_sha256,))
    plan = GarbageCollectionPlan.create(store, references)

    assert plan.delete_candidates == (drop.logical_sha256,)
    deleted = execute_garbage_collection(
        backend,
        plan,
        references,
        confirm_plan_root=plan.plan_root,
    )

    assert deleted == (drop.logical_sha256,)
    assert store.read(keep.logical_sha256).trial_id == "keep"
    assert backend.list_keys() == (keep.logical_sha256,)


def test_gc_refuses_stale_reference_snapshot_and_wrong_confirmation() -> None:
    backend = _RemoteMemoryBackend()
    store = ContentAddressedEvidenceStore(backend)
    first = store.write(_evidence("first"))
    second = store.write(_evidence("second"))
    original_refs = RetentionReferenceSet.create((first.logical_sha256,))
    plan = GarbageCollectionPlan.create(store, original_refs)
    current_refs = RetentionReferenceSet.create((first.logical_sha256, second.logical_sha256))

    with pytest.raises(ValueError, match="plan-root confirmation"):
        execute_garbage_collection(
            backend,
            plan,
            original_refs,
            confirm_plan_root="0" * 64,
        )
    with pytest.raises(ValueError, match="reference set changed"):
        execute_garbage_collection(
            backend,
            plan,
            current_refs,
            confirm_plan_root=plan.plan_root,
        )

    assert set(backend.list_keys()) == {first.logical_sha256, second.logical_sha256}
