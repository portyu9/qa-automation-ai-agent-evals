"""Integrity-bound receipts for deterministic retrieval and poisoning relations."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.retrieval.models import RetrievalContractSpec, RetrievalPoisonRelation
from agent_evals.retrieval.ranker import RetrievalHit, rank_corpus

_SCHEMA: Literal["agent-evals/retrieval-delivery-receipt/v1"] = (
    "agent-evals/retrieval-delivery-receipt/v1"
)
_EVENT_SOURCE = "bridge:retrieval:openai"
_ROOT_DOMAIN = b"agent-evals/retrieval-delivery-receipt/v1\0"


class RetrievalReceiptError(ValueError):
    """The retrieval relation cannot be established unambiguously."""


class RetrievalHitDigest(BaseModel):
    """Content-free receipt projection of one ranked retrieval hit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int = Field(ge=1, le=64, strict=True)
    chunk_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    score: int = Field(ge=0, strict=True)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_hit(cls, hit: RetrievalHit) -> RetrievalHitDigest:
        return cls(
            rank=hit.rank,
            chunk_id=hit.chunk_id,
            document_id=hit.document_id,
            score=hit.score,
            content_sha256=hit.content_sha256,
        )


class RetrievalDeliveryReceipt(BaseModel):
    """Exact corpus/query/ranking/model-visible delivery relation for one tool call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/retrieval-delivery-receipt/v1"] = _SCHEMA
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    tool_name: str = Field(min_length=1, max_length=128)
    call_id: str = Field(min_length=1, max_length=512)
    base_corpus_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    attacked_corpus_identity: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    query_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    ranker_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    poison_identity: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    poison_relation: RetrievalPoisonRelation | None = None
    baseline_hits: tuple[RetrievalHitDigest, ...] = Field(min_length=1, max_length=64)
    active_hits: tuple[RetrievalHitDigest, ...] = Field(min_length=1, max_length=64)
    model_visible_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_shape_and_root(self) -> Self:
        if (self.poison_identity is None) != (self.attacked_corpus_identity is None):
            raise ValueError("poison and attacked-corpus identities must appear together")
        if (self.poison_identity is None) != (self.poison_relation is None):
            raise ValueError("poison identity and relation must appear together")
        _require_contiguous_ranks(self.baseline_hits, label="baseline")
        _require_contiguous_ranks(self.active_hits, label="active")
        expected = _receipt_root(self.model_dump(mode="python", exclude={"receipt_root"}))
        if self.receipt_root != expected:
            raise ValueError("retrieval delivery receipt root mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        scenario_identity: str,
        contract: RetrievalContractSpec,
        call_id: str,
        model_visible_result: str,
    ) -> RetrievalDeliveryReceipt:
        if not call_id:
            raise RetrievalReceiptError("retrieval tool call identity must be non-empty")

        baseline = rank_corpus(contract.corpus, contract.query)
        active = baseline
        attacked_identity: str | None = None
        poison_identity: str | None = None
        poison_relation: RetrievalPoisonRelation | None = None

        if contract.poison is not None:
            try:
                attacked = contract.poison.apply(contract.corpus)
            except ValueError as exc:
                raise RetrievalReceiptError("retrieval poison could not be applied") from exc
            active = rank_corpus(attacked, contract.query)
            attacked_identity = attacked.identity
            poison_identity = contract.poison.identity
            poison_relation = contract.poison.relation
            _require_poison_relation(contract, baseline.hits, active.hits)

        if model_visible_result != active.canonical_json:
            raise RetrievalReceiptError(
                "model-visible retrieval result does not equal the canonical active ranking"
            )

        unsigned: dict[str, Any] = {
            "schema_version": _SCHEMA,
            "scenario_identity": scenario_identity,
            "contract_identity": contract.identity,
            "tool_name": contract.tool_name,
            "call_id": call_id,
            "base_corpus_identity": contract.corpus.identity,
            "attacked_corpus_identity": attacked_identity,
            "query_identity": contract.query.identity,
            "ranker_identity": contract.query.ranker.identity,
            "poison_identity": poison_identity,
            "poison_relation": poison_relation,
            "baseline_hits": tuple(RetrievalHitDigest.from_hit(hit) for hit in baseline.hits),
            "active_hits": tuple(RetrievalHitDigest.from_hit(hit) for hit in active.hits),
            "model_visible_result_sha256": hashlib.sha256(
                model_visible_result.encode("utf-8")
            ).hexdigest(),
        }
        return cls.model_validate({**unsigned, "receipt_root": _receipt_root(unsigned)})

    def to_event(self, *, sequence: int) -> EvidenceEvent:
        return EvidenceEvent(
            sequence=sequence,
            kind=EvidenceKind.RETRIEVAL_DELIVERY,
            source=_EVENT_SOURCE,
            payload=self.model_dump(mode="json"),
        )


def expected_event_source() -> str:
    return _EVENT_SOURCE


def _require_poison_relation(
    contract: RetrievalContractSpec,
    baseline_hits: tuple[RetrievalHit, ...],
    active_hits: tuple[RetrievalHit, ...],
) -> None:
    poison = contract.poison
    if poison is None:
        return
    active_ids = {hit.chunk_id for hit in active_hits}
    if poison.inserted_chunk.chunk_id not in active_ids:
        raise RetrievalReceiptError("controlled poison did not enter the active top-k ranking")
    if poison.relation is RetrievalPoisonRelation.DISPLACE_CHUNK:
        displaced = poison.expected_displaced_chunk_id
        baseline_ids = {hit.chunk_id for hit in baseline_hits}
        if displaced is None or displaced not in baseline_ids or displaced in active_ids:
            raise RetrievalReceiptError(
                "controlled poison did not displace the exact expected baseline chunk"
            )


def _require_contiguous_ranks(
    hits: tuple[RetrievalHitDigest, ...],
    *,
    label: str,
) -> None:
    expected = list(range(1, len(hits) + 1))
    actual = [hit.rank for hit in hits]
    if actual != expected:
        raise ValueError(f"retrieval {label} receipt ranks must be contiguous from one")
    if len({hit.chunk_id for hit in hits}) != len(hits):
        raise ValueError(f"retrieval {label} receipt hits must have unique chunk identities")


def _receipt_root(value: dict[str, Any]) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(_ROOT_DOMAIN + canonical).hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, RetrievalPoisonRelation):
        return value.value
    raise TypeError(f"unsupported receipt value type: {type(value).__name__}")
