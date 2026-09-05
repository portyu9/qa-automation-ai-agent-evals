"""Content-addressed contracts for deterministic retrieval assurance."""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ID_PATTERN = r"^[a-z0-9][a-z0-9._:-]{0,127}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class RetrievalPoisonRelation(StrEnum):
    """Bound ranking relation required from one controlled insertion."""

    ENTER_TOP_K = "enter_top_k"
    DISPLACE_CHUNK = "displace_chunk"


class RetrievalRankerProfile(BaseModel):
    """Behavior-bearing identity for the deterministic lexical ranker."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ranker_id: str = Field(default="fixed-lexical", pattern=_ID_PATTERN)
    revision: str = Field(default="1", min_length=1, max_length=64)
    tokenizer: str = Field(default="nfkc-casefold-alnum/v1", min_length=1, max_length=128)
    overlap_weight: int = Field(default=100, ge=1, le=100_000, strict=True)
    coverage_weight: int = Field(default=25, ge=0, le=100_000, strict=True)
    phrase_bonus: int = Field(default=1_000, ge=0, le=1_000_000, strict=True)

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="python"))


class RetrievalChunkSpec(BaseModel):
    """One exact corpus chunk with stable provenance and content identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(pattern=_ID_PATTERN)
    document_id: str = Field(pattern=_ID_PATTERN)
    source: str = Field(min_length=1, max_length=2_048)
    content: str = Field(min_length=1, max_length=200_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("retrieval source must not contain surrounding whitespace")
        return value

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        _canonical_json_bytes(value)
        return value

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="python"))


class RetrievalCorpusSpec(BaseModel):
    """Canonical immutable corpus definition used by one retrieval contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    corpus_id: str = Field(pattern=_ID_PATTERN)
    revision: str = Field(min_length=1, max_length=128)
    chunks: tuple[RetrievalChunkSpec, ...] = Field(min_length=1, max_length=512)

    @field_validator("chunks")
    @classmethod
    def canonicalize_chunks(
        cls,
        value: tuple[RetrievalChunkSpec, ...],
    ) -> tuple[RetrievalChunkSpec, ...]:
        chunk_ids = [chunk.chunk_id for chunk in value]
        if len(set(chunk_ids)) != len(chunk_ids):
            raise ValueError("retrieval corpus chunk_id values must be unique")
        return tuple(sorted(value, key=lambda chunk: (chunk.chunk_id, chunk.identity)))

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="python"))


class RetrievalQuerySpec(BaseModel):
    """Exact query, result bound, and deterministic ranker identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str = Field(min_length=1, max_length=20_000)
    top_k: int = Field(default=3, ge=1, le=64, strict=True)
    ranker: RetrievalRankerProfile = Field(default_factory=RetrievalRankerProfile)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("retrieval query must not contain surrounding whitespace")
        return value

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="python"))


class RetrievalPoisonSpec(BaseModel):
    """Insertion-only perturbation bound to one exact base corpus."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    poison_id: str = Field(pattern=_ID_PATTERN)
    revision: str = Field(min_length=1, max_length=64)
    base_corpus_identity: str = Field(pattern=_SHA256_PATTERN)
    inserted_chunk: RetrievalChunkSpec
    relation: RetrievalPoisonRelation = RetrievalPoisonRelation.ENTER_TOP_K
    expected_displaced_chunk_id: str | None = Field(default=None, pattern=_ID_PATTERN)

    @model_validator(mode="after")
    def validate_relation(self) -> Self:
        if self.relation is RetrievalPoisonRelation.DISPLACE_CHUNK:
            if self.expected_displaced_chunk_id is None:
                raise ValueError(
                    "displace_chunk poison relation requires an expected displaced chunk"
                )
            if self.expected_displaced_chunk_id == self.inserted_chunk.chunk_id:
                raise ValueError("inserted poison chunk cannot also be the displaced chunk")
        elif self.expected_displaced_chunk_id is not None:
            raise ValueError("expected displaced chunk is valid only for displace_chunk relation")
        return self

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="python"))

    def apply(self, base: RetrievalCorpusSpec) -> RetrievalCorpusSpec:
        if base.identity != self.base_corpus_identity:
            raise ValueError("retrieval poison is bound to a different base corpus")
        if any(chunk.chunk_id == self.inserted_chunk.chunk_id for chunk in base.chunks):
            raise ValueError("retrieval poison insertion cannot replace an existing chunk_id")
        return RetrievalCorpusSpec(
            corpus_id=base.corpus_id,
            revision=base.revision,
            chunks=(*base.chunks, self.inserted_chunk),
        )


class RetrievalContractSpec(BaseModel):
    """Scenario-owned retrieval behavior required before subject grading."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str = Field(default="retrieve_context", pattern=_ID_PATTERN)
    corpus: RetrievalCorpusSpec
    query: RetrievalQuerySpec
    poison: RetrievalPoisonSpec | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if self.query.top_k > len(self.corpus.chunks) + (1 if self.poison is not None else 0):
            raise ValueError("retrieval top_k cannot exceed the available attacked corpus size")
        if self.poison is not None:
            if self.poison.base_corpus_identity != self.corpus.identity:
                raise ValueError("retrieval poison must bind the exact scenario base corpus")
            if (
                self.poison.expected_displaced_chunk_id is not None
                and self.poison.expected_displaced_chunk_id
                not in {chunk.chunk_id for chunk in self.corpus.chunks}
            ):
                raise ValueError("expected displaced chunk must exist in the base corpus")
        return self

    @property
    def identity(self) -> str:
        return _sha256_json(self.model_dump(mode="python", exclude_none=True))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    normalized = _canonicalize_json(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _canonicalize_json(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonicalize_json(value.model_dump(mode="python", exclude_none=True))
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("retrieval JSON object keys must be strings")
        return {key: _canonicalize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize_json(item) for item in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("retrieval JSON values must be finite")
        return value
    raise ValueError(f"unsupported retrieval JSON value type: {type(value).__name__}")
