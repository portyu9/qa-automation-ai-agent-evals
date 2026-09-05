"""Platform-stable lexical ranking and canonical model-visible retrieval results."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_evals.retrieval.models import (
    RetrievalChunkSpec,
    RetrievalCorpusSpec,
    RetrievalQuerySpec,
)


class RetrievalHit(BaseModel):
    """One ranked chunk exactly as exposed by the deterministic retriever."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rank: int = Field(ge=1, le=64, strict=True)
    chunk_id: str
    document_id: str
    source: str
    score: int = Field(ge=0, strict=True)
    content: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_content_digest(self) -> RetrievalHit:
        expected = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("retrieval hit content digest does not match content")
        return self


class RetrievalResult(BaseModel):
    """Bounded canonical retrieval payload supplied to a model-facing tool result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str
    hits: tuple[RetrievalHit, ...] = Field(max_length=64)

    @model_validator(mode="after")
    def validate_ranks(self) -> RetrievalResult:
        expected = list(range(1, len(self.hits) + 1))
        actual = [hit.rank for hit in self.hits]
        if actual != expected:
            raise ValueError("retrieval result ranks must be contiguous from one")
        if len({hit.chunk_id for hit in self.hits}) != len(self.hits):
            raise ValueError("retrieval result cannot contain duplicate chunk identities")
        return self

    @property
    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json.encode("utf-8")).hexdigest()


def rank_corpus(corpus: RetrievalCorpusSpec, query: RetrievalQuerySpec) -> RetrievalResult:
    """Rank a corpus with an explicit deterministic integer scoring contract."""
    query_tokens = _tokens(query.query)
    query_counter = Counter(query_tokens)
    unique_query = frozenset(query_counter)
    normalized_phrase = " ".join(query_tokens)
    profile = query.ranker

    scored: list[tuple[int, str, str, RetrievalChunkSpec]] = []
    for chunk in corpus.chunks:
        chunk_tokens = _tokens(chunk.content)
        chunk_counter = Counter(chunk_tokens)
        overlap = sum(
            min(count, chunk_counter.get(token, 0)) for token, count in query_counter.items()
        )
        coverage = sum(1 for token in unique_query if chunk_counter.get(token, 0) > 0)
        normalized_chunk = " ".join(chunk_tokens)
        phrase = bool(normalized_phrase) and normalized_phrase in normalized_chunk
        score = (
            overlap * profile.overlap_weight
            + coverage * profile.coverage_weight
            + (profile.phrase_bonus if phrase else 0)
        )
        scored.append((score, chunk.chunk_id, chunk.document_id, chunk))

    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    hits = tuple(
        RetrievalHit(
            rank=index,
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            source=chunk.source,
            score=score,
            content=chunk.content,
            content_sha256=chunk.content_sha256,
        )
        for index, (score, _, _, chunk) in enumerate(scored[: query.top_k], start=1)
    )
    return RetrievalResult(query=query.query, hits=hits)


def _tokens(value: str) -> tuple[str, ...]:
    """NFKC + casefold + Unicode-alphanumeric tokenization with no locale dependence."""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens: list[str] = []
    current: list[str] = []
    for character in normalized:
        if character.isalnum():
            current.append(character)
            continue
        if current:
            tokens.append("".join(current))
            current.clear()
    if current:
        tokens.append("".join(current))
    return tuple(tokens)
