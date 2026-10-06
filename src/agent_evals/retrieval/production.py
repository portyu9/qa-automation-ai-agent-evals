"""Production retrieval assurance for vector/hybrid ranking, lifecycle and tenant isolation."""

from __future__ import annotations

import hashlib
import hmac
import json
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_POLICY_SCHEMA: Literal["agent-evals/retrieval-pipeline-policy/v1"] = (
    "agent-evals/retrieval-pipeline-policy/v1"
)
_DOCUMENT_SCHEMA: Literal["agent-evals/retrieved-document-observation/v1"] = (
    "agent-evals/retrieved-document-observation/v1"
)
_RECEIPT_SCHEMA: Literal["agent-evals/retrieval-pipeline-receipt/v1"] = (
    "agent-evals/retrieval-pipeline-receipt/v1"
)
_RECEIPT_DOMAIN = b"agent-evals/retrieval-pipeline-receipt/v1\0"


class RetrievalMode(StrEnum):
    LEXICAL = "lexical"
    VECTOR = "vector"
    HYBRID = "hybrid"


class RetrievalDocumentLifecycle(StrEnum):
    ACTIVE = "active"
    TOMBSTONED = "tombstoned"
    EXPIRED = "expired"


class RetrievalPipelineViolation(StrEnum):
    WRONG_TENANT = "wrong-tenant"
    WRONG_COLLECTION = "wrong-collection"
    FILTER_MISMATCH = "filter-mismatch"
    INACTIVE_DOCUMENT = "inactive-document"
    MISSING_VECTOR_SCORE = "missing-vector-score"
    MISSING_LEXICAL_SCORE = "missing-lexical-score"
    RERANK_ORDER = "rerank-order"
    MISSING_CITATION = "missing-citation"
    MISSING_REWRITE = "missing-rewrite"
    MISSING_RERANKER = "missing-reranker"


class RetrievalPipelinePolicy(BaseModel):
    """Scenario-owned production retrieval constraints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/retrieval-pipeline-policy/v1"] = _POLICY_SCHEMA
    tenant_id: str = Field(min_length=1, max_length=256)
    mode: RetrievalMode
    top_k: int = Field(default=5, ge=1, le=1_000, strict=True)
    allowed_collections: frozenset[str] = Field(min_length=1)
    required_labels: frozenset[str] = frozenset()
    require_query_rewrite: bool = Field(default=False, strict=True)
    require_reranker: bool = Field(default=False, strict=True)
    require_citations: bool = Field(default=True, strict=True)

    @field_validator("allowed_collections", "required_labels")
    @classmethod
    def validate_labels(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not item.strip() or item != item.strip() for item in value):
            raise ValueError("retrieval policy labels must be trimmed non-empty strings")
        return value


class RetrievedDocumentObservation(BaseModel):
    """One bounded document observation after filtering/ranking."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/retrieved-document-observation/v1"] = _DOCUMENT_SCHEMA
    document_id: str = Field(min_length=1, max_length=512)
    tenant_id: str = Field(min_length=1, max_length=256)
    collection: str = Field(min_length=1, max_length=256)
    labels: frozenset[str] = frozenset()
    lifecycle: RetrievalDocumentLifecycle
    rank: int = Field(ge=1, le=100_000, strict=True)
    lexical_score: int | None = Field(default=None, ge=0, le=2**63 - 1, strict=True)
    vector_score_micros: int | None = Field(
        default=None,
        ge=-1_000_000,
        le=1_000_000,
        strict=True,
    )
    rerank_score: int | None = Field(default=None, ge=-(2**63), le=2**63 - 1, strict=True)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    citation_uri: str | None = Field(default=None, min_length=1, max_length=4096)

    @field_validator("labels")
    @classmethod
    def validate_labels(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not item.strip() or item != item.strip() for item in value):
            raise ValueError("retrieval document labels must be trimmed non-empty strings")
        return value


class RetrievalPipelineReceipt(BaseModel):
    """Integrity-bound production retrieval pipeline observation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/retrieval-pipeline-receipt/v1"] = _RECEIPT_SCHEMA
    policy: RetrievalPipelinePolicy
    documents: tuple[RetrievedDocumentObservation, ...] = Field(max_length=1_000)
    query_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rewritten_query_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    reranker_identity: str | None = Field(default=None, min_length=1, max_length=512)
    violations: tuple[RetrievalPipelineViolation, ...]
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        policy: RetrievalPipelinePolicy,
        documents: tuple[RetrievedDocumentObservation, ...],
        query_sha256: str,
        rewritten_query_sha256: str | None = None,
        reranker_identity: str | None = None,
    ) -> Self:
        _require_exact(policy, RetrievalPipelinePolicy, "retrieval pipeline policy")
        checked_policy = RetrievalPipelinePolicy.model_validate_json(policy.model_dump_json())
        checked: list[RetrievedDocumentObservation] = []
        for item in documents:
            _require_exact(item, RetrievedDocumentObservation, "retrieved document observation")
            checked.append(RetrievedDocumentObservation.model_validate_json(item.model_dump_json()))
        if len(checked) > checked_policy.top_k:
            raise ValueError("retrieval receipt contains more documents than top_k")
        ids = [item.document_id for item in checked]
        if len(set(ids)) != len(ids):
            raise ValueError("retrieval receipt document IDs must be unique")
        ranks = [item.rank for item in checked]
        if ranks != list(range(1, len(checked) + 1)):
            raise ValueError("retrieval receipt ranks must be contiguous from 1")

        violations: set[RetrievalPipelineViolation] = set()
        if checked_policy.require_query_rewrite and rewritten_query_sha256 is None:
            violations.add(RetrievalPipelineViolation.MISSING_REWRITE)
        if checked_policy.require_reranker and reranker_identity is None:
            violations.add(RetrievalPipelineViolation.MISSING_RERANKER)

        for item in checked:
            if item.tenant_id != checked_policy.tenant_id:
                violations.add(RetrievalPipelineViolation.WRONG_TENANT)
            if item.collection not in checked_policy.allowed_collections:
                violations.add(RetrievalPipelineViolation.WRONG_COLLECTION)
            if not checked_policy.required_labels <= item.labels:
                violations.add(RetrievalPipelineViolation.FILTER_MISMATCH)
            if item.lifecycle is not RetrievalDocumentLifecycle.ACTIVE:
                violations.add(RetrievalPipelineViolation.INACTIVE_DOCUMENT)
            if (
                checked_policy.mode in {RetrievalMode.VECTOR, RetrievalMode.HYBRID}
                and item.vector_score_micros is None
            ):
                violations.add(RetrievalPipelineViolation.MISSING_VECTOR_SCORE)
            if (
                checked_policy.mode in {RetrievalMode.LEXICAL, RetrievalMode.HYBRID}
                and item.lexical_score is None
            ):
                violations.add(RetrievalPipelineViolation.MISSING_LEXICAL_SCORE)
            if checked_policy.require_citations and item.citation_uri is None:
                violations.add(RetrievalPipelineViolation.MISSING_CITATION)

        if checked_policy.require_reranker and checked:
            scores = [item.rerank_score for item in checked]
            if any(score is None for score in scores):
                violations.add(RetrievalPipelineViolation.RERANK_ORDER)
            else:
                concrete = [score for score in scores if score is not None]
                if concrete != sorted(concrete, reverse=True):
                    violations.add(RetrievalPipelineViolation.RERANK_ORDER)

        canonical_violations = tuple(sorted(violations, key=lambda item: item.value))
        accepted = not canonical_violations
        material = {
            "schema_version": _RECEIPT_SCHEMA,
            "policy": checked_policy.model_dump(mode="json"),
            "documents": [item.model_dump(mode="json") for item in checked],
            "query_sha256": query_sha256,
            "rewritten_query_sha256": rewritten_query_sha256,
            "reranker_identity": reranker_identity,
            "violations": [item.value for item in canonical_violations],
            "accepted": accepted,
        }
        return cls.model_construct(
            policy=checked_policy,
            documents=tuple(checked),
            query_sha256=query_sha256,
            rewritten_query_sha256=rewritten_query_sha256,
            reranker_identity=reranker_identity,
            violations=canonical_violations,
            accepted=accepted,
            receipt_root=_domain_root(_RECEIPT_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_receipt(self) -> Self:
        rebuilt = type(self).create(
            policy=self.policy,
            documents=self.documents,
            query_sha256=self.query_sha256,
            rewritten_query_sha256=self.rewritten_query_sha256,
            reranker_identity=self.reranker_identity,
        )
        if (
            self.violations != rebuilt.violations
            or self.accepted != rebuilt.accepted
            or not hmac.compare_digest(self.receipt_root, rebuilt.receipt_root)
        ):
            raise ValueError("retrieval pipeline receipt does not recompute")
        return self


def _require_exact(value: object, expected: type[object], label: str) -> None:
    if type(value) is not expected:
        raise ValueError(f"{label} requires exact {expected.__name__}")


def _domain_root(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + _canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("retrieval pipeline material must be finite JSON-compatible data") from exc


__all__ = [
    "RetrievalDocumentLifecycle",
    "RetrievalMode",
    "RetrievalPipelinePolicy",
    "RetrievalPipelineReceipt",
    "RetrievalPipelineViolation",
    "RetrievedDocumentObservation",
]
