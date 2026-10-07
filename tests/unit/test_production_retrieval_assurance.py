from __future__ import annotations

from agent_evals.retrieval.production import (
    RetrievalDocumentLifecycle,
    RetrievalMode,
    RetrievalPipelinePolicy,
    RetrievalPipelineReceipt,
    RetrievalPipelineViolation,
    RetrievedDocumentObservation,
)


def _document(
    *,
    document_id: str,
    rank: int,
    rerank_score: int,
    tenant: str = "tenant-a",
    lifecycle: RetrievalDocumentLifecycle = RetrievalDocumentLifecycle.ACTIVE,
    citation: str | None = None,
) -> RetrievedDocumentObservation:
    return RetrievedDocumentObservation(
        document_id=document_id,
        tenant_id=tenant,
        collection="knowledge",
        labels=frozenset({"public", "support"}),
        lifecycle=lifecycle,
        rank=rank,
        lexical_score=100 - rank,
        vector_score_micros=900_000 - rank,
        rerank_score=rerank_score,
        content_sha256=f"{rank:064x}",
        citation_uri=citation or f"https://docs.example.test/{document_id}",
    )


def test_hybrid_retrieval_pipeline_enforces_lifecycle_filters_rerank_rewrite_citations_and_tenant() -> (
    None
):
    policy = RetrievalPipelinePolicy(
        tenant_id="tenant-a",
        mode=RetrievalMode.HYBRID,
        top_k=3,
        allowed_collections=frozenset({"knowledge"}),
        required_labels=frozenset({"support"}),
        require_query_rewrite=True,
        require_reranker=True,
        require_citations=True,
    )
    documents = (
        _document(document_id="doc-a", rank=1, rerank_score=300),
        _document(document_id="doc-b", rank=2, rerank_score=200),
        _document(document_id="doc-c", rank=3, rerank_score=100),
    )

    receipt = RetrievalPipelineReceipt.create(
        policy=policy,
        documents=documents,
        query_sha256="a" * 64,
        rewritten_query_sha256="b" * 64,
        reranker_identity="reranker-v2",
    )

    assert receipt.accepted is True
    assert receipt.violations == ()

    contaminated = list(documents)
    contaminated[1] = _document(
        document_id="doc-b",
        rank=2,
        rerank_score=400,
        tenant="tenant-b",
        lifecycle=RetrievalDocumentLifecycle.TOMBSTONED,
        citation=None,
    ).model_copy(update={"citation_uri": None})
    rejected = RetrievalPipelineReceipt.create(
        policy=policy,
        documents=tuple(contaminated),
        query_sha256="a" * 64,
        rewritten_query_sha256=None,
        reranker_identity="reranker-v2",
    )

    assert rejected.accepted is False
    assert RetrievalPipelineViolation.WRONG_TENANT in rejected.violations
    assert RetrievalPipelineViolation.INACTIVE_DOCUMENT in rejected.violations
    assert RetrievalPipelineViolation.MISSING_CITATION in rejected.violations
    assert RetrievalPipelineViolation.MISSING_REWRITE in rejected.violations
    assert RetrievalPipelineViolation.RERANK_ORDER in rejected.violations


def test_vector_and_lexical_modes_require_only_their_owned_score_domains() -> None:
    vector_policy = RetrievalPipelinePolicy(
        tenant_id="tenant-a",
        mode=RetrievalMode.VECTOR,
        allowed_collections=frozenset({"knowledge"}),
        require_citations=False,
    )
    vector_doc = _document(document_id="vector", rank=1, rerank_score=1).model_copy(
        update={"lexical_score": None}
    )
    assert (
        RetrievalPipelineReceipt.create(
            policy=vector_policy,
            documents=(vector_doc,),
            query_sha256="c" * 64,
        ).accepted
        is True
    )

    lexical_policy = vector_policy.model_copy(update={"mode": RetrievalMode.LEXICAL})
    lexical_doc = vector_doc.model_copy(update={"lexical_score": 5, "vector_score_micros": None})
    assert (
        RetrievalPipelineReceipt.create(
            policy=lexical_policy,
            documents=(lexical_doc,),
            query_sha256="d" * 64,
        ).accepted
        is True
    )

def test_unordered_retrieval_material_is_root_stable_and_round_trips() -> None:
    collections = ["knowledge", "archive"]
    labels = ["support", "public"]
    policy_a = RetrievalPipelinePolicy(
        tenant_id="tenant-a",
        mode=RetrievalMode.HYBRID,
        top_k=1,
        allowed_collections=frozenset(collections),
        required_labels=frozenset(labels),
        require_citations=True,
    )
    policy_b = RetrievalPipelinePolicy(
        tenant_id="tenant-a",
        mode=RetrievalMode.HYBRID,
        top_k=1,
        allowed_collections=frozenset(reversed(collections)),
        required_labels=frozenset(reversed(labels)),
        require_citations=True,
    )
    document_a = _document(document_id="canonical", rank=1, rerank_score=1)
    document_b = document_a.model_copy(
        update={"labels": frozenset(reversed(labels))},
    )

    receipt_a = RetrievalPipelineReceipt.create(
        policy=policy_a,
        documents=(document_a,),
        query_sha256="e" * 64,
    )
    receipt_b = RetrievalPipelineReceipt.create(
        policy=policy_b,
        documents=(document_b,),
        query_sha256="e" * 64,
    )

    assert policy_a.model_dump_json() == policy_b.model_dump_json()
    assert document_a.model_dump_json() == document_b.model_dump_json()
    assert receipt_a.receipt_root == receipt_b.receipt_root
    round_tripped = RetrievalPipelineReceipt.model_validate_json(receipt_a.model_dump_json())
    assert round_tripped.receipt_root == receipt_a.receipt_root
