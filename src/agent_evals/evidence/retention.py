"""Reference-safe retention planning for content-addressed evidence blobs."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Iterable
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.evidence.blob_store import (
    ContentAddressedEvidenceStore,
    EvidenceBlobBackend,
    validate_blob_key,
)
from agent_evals.evidence.store import EvidenceIntegrityError

_REFERENCE_SCHEMA: Literal["agent-evals/evidence-reference-set/v1"] = (
    "agent-evals/evidence-reference-set/v1"
)
_GC_SCHEMA: Literal["agent-evals/evidence-gc-plan/v1"] = "agent-evals/evidence-gc-plan/v1"
_REFERENCE_DOMAIN = b"agent-evals/evidence-reference-set/v1\0"
_GC_DOMAIN = b"agent-evals/evidence-gc-plan/v1\0"
_MAX_KEYS = 100_000


class RetentionReferenceSet(BaseModel):
    """Canonical immutable snapshot of evidence identities that must be retained."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/evidence-reference-set/v1"] = _REFERENCE_SCHEMA
    referenced_sha256: tuple[str, ...] = Field(max_length=_MAX_KEYS)
    reference_set_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, references: Iterable[str]) -> Self:
        canonical = tuple(sorted(set(references)))
        if len(canonical) > _MAX_KEYS:
            raise ValueError("evidence reference set exceeds configured key ceiling")
        for key in canonical:
            validate_blob_key(key)
        root = _reference_root(canonical)
        return cls(referenced_sha256=canonical, reference_set_root=root)

    @model_validator(mode="after")
    def verify_reference_set(self) -> Self:
        if self.referenced_sha256 != tuple(sorted(set(self.referenced_sha256))):
            raise ValueError("evidence reference keys must be canonical sorted unique values")
        for key in self.referenced_sha256:
            validate_blob_key(key)
        if not hmac.compare_digest(
            _reference_root(self.referenced_sha256), self.reference_set_root
        ):
            raise ValueError("evidence reference-set root mismatch")
        return self


class GarbageCollectionPlan(BaseModel):
    """Integrity-bound deletion plan tied to one exact reference snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/evidence-gc-plan/v1"] = _GC_SCHEMA
    reference_set_root: str = Field(pattern=r"^[0-9a-f]{64}$")
    delete_candidates: tuple[str, ...] = Field(max_length=_MAX_KEYS)
    plan_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        store: ContentAddressedEvidenceStore,
        references: RetentionReferenceSet,
    ) -> Self:
        referenced = set(references.referenced_sha256)
        stored_keys = store.keys()
        candidates = tuple(key for key in stored_keys if key not in referenced)
        return cls(
            reference_set_root=references.reference_set_root,
            delete_candidates=candidates,
            plan_root=_plan_root(references.reference_set_root, candidates),
        )

    @model_validator(mode="after")
    def verify_plan(self) -> Self:
        if self.delete_candidates != tuple(sorted(set(self.delete_candidates))):
            raise ValueError("GC candidates must be canonical sorted unique keys")
        for key in self.delete_candidates:
            validate_blob_key(key)
        expected = _plan_root(self.reference_set_root, self.delete_candidates)
        if not hmac.compare_digest(expected, self.plan_root):
            raise ValueError("evidence GC plan root mismatch")
        return self


def execute_garbage_collection(
    backend: EvidenceBlobBackend,
    plan: GarbageCollectionPlan,
    references: RetentionReferenceSet,
    *,
    confirm_plan_root: str,
) -> tuple[str, ...]:
    """Delete only candidates from the exact still-current reference snapshot."""
    if not hmac.compare_digest(confirm_plan_root, plan.plan_root):
        raise ValueError("garbage collection requires exact plan-root confirmation")
    if not hmac.compare_digest(plan.reference_set_root, references.reference_set_root):
        raise ValueError("reference set changed after garbage-collection planning")
    referenced = set(references.referenced_sha256)
    if referenced.intersection(plan.delete_candidates):
        raise EvidenceIntegrityError(
            "garbage-collection plan attempts to delete referenced evidence"
        )

    deleted: list[str] = []
    for key in plan.delete_candidates:
        if key in referenced:
            raise EvidenceIntegrityError("refusing to delete currently referenced evidence")
        if backend.delete(key):
            deleted.append(key)
    return tuple(deleted)


def _reference_root(keys: tuple[str, ...]) -> str:
    material = {"schema_version": _REFERENCE_SCHEMA, "referenced_sha256": list(keys)}
    return hashlib.sha256(_REFERENCE_DOMAIN + _canonical_json_bytes(material)).hexdigest()


def _plan_root(reference_set_root: str, candidates: tuple[str, ...]) -> str:
    material = {
        "schema_version": _GC_SCHEMA,
        "reference_set_root": reference_set_root,
        "delete_candidates": list(candidates),
    }
    return hashlib.sha256(_GC_DOMAIN + _canonical_json_bytes(material)).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
