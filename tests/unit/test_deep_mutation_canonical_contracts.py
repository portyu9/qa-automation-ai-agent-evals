from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import BaseModel

import agent_evals.evidence.store as evidence_store
import agent_evals.retrieval.receipt as retrieval_receipt
import agent_evals.semantic.receipt as semantic_receipt
import agent_evals.side_effect.receipt as side_effect_receipt
from agent_evals.retrieval.models import RetrievalPoisonRelation


class _ProbeModel(BaseModel):
    value: int


def test_receipt_roots_use_exact_domain_separation() -> None:
    material = {"z": 1, "a": "x"}
    canonical = b'{"a":"x","z":1}'

    retrieval_root = retrieval_receipt._receipt_root(material)
    semantic_root = semantic_receipt._receipt_root(material)
    side_effect_root = side_effect_receipt._receipt_root(material)

    assert (
        retrieval_root
        == hashlib.sha256(b"agent-evals/retrieval-delivery-receipt/v1\0" + canonical).hexdigest()
    )
    assert (
        semantic_root
        == hashlib.sha256(b"agent-evals/semantic-judgment-receipt/v1\0" + canonical).hexdigest()
    )
    assert (
        side_effect_root
        == hashlib.sha256(
            b"agent-evals/side-effect-idempotency-receipt/v1\0" + canonical
        ).hexdigest()
    )
    assert len({retrieval_root, semantic_root, side_effect_root}) == 3


def test_receipt_canonicalization_preserves_declared_unicode_policy() -> None:
    material = {"z": 1, "a": "Ω"}
    escaped = b'{"a":"\\u03a9","z":1}'
    unicode_bytes = '{"a":"Ω","z":1}'.encode()

    assert (
        retrieval_receipt._receipt_root(material)
        == hashlib.sha256(b"agent-evals/retrieval-delivery-receipt/v1\0" + escaped).hexdigest()
    )
    assert (
        side_effect_receipt._receipt_root(material)
        == hashlib.sha256(b"agent-evals/side-effect-idempotency-receipt/v1\0" + escaped).hexdigest()
    )
    assert semantic_receipt._canonical_json_bytes(material) == unicode_bytes
    assert (
        semantic_receipt._receipt_root(material)
        == hashlib.sha256(b"agent-evals/semantic-judgment-receipt/v1\0" + unicode_bytes).hexdigest()
    )


@pytest.mark.parametrize(
    ("root_fn", "label"),
    [
        (retrieval_receipt._receipt_root, "retrieval receipt material"),
        (semantic_receipt._receipt_root, "semantic judgment receipt material"),
        (side_effect_receipt._receipt_root, "side-effect receipt material"),
    ],
)
def test_receipt_roots_preserve_resource_limit_labels(
    root_fn: object,
    label: str,
) -> None:
    assert callable(root_fn)
    with pytest.raises(ValueError, match=label):
        root_fn({"unsupported": object()})


def test_retrieval_json_default_is_explicit_and_fail_closed() -> None:
    assert retrieval_receipt._json_default(_ProbeModel(value=7)) == {"value": 7}
    assert retrieval_receipt._json_default(RetrievalPoisonRelation.ENTER_TOP_K) == "enter_top_k"
    with pytest.raises(
        TypeError,
        match=r"^unsupported receipt value type: object$",
    ):
        retrieval_receipt._json_default(object())


def test_side_effect_json_default_is_explicit_and_fail_closed() -> None:
    assert side_effect_receipt._json_default(_ProbeModel(value=7)) == {"value": 7}
    with pytest.raises(
        TypeError,
        match=r"^unsupported side-effect receipt value type: object$",
    ):
        side_effect_receipt._json_default(object())


def test_semantic_canonicalization_rejects_nonfinite_or_unsupported_material() -> None:
    for value in ({"value": float("nan")}, {"value": object()}):
        with pytest.raises(
            ValueError,
            match=r"^semantic judgment material must be finite JSON-compatible data$",
        ):
            semantic_receipt._canonical_json_bytes(value)


def test_evidence_store_canonical_json_is_sorted_compact_and_finite() -> None:
    material = {"z": 1, "a": "Ω"}
    expected = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    assert evidence_store._canonical_json_bytes(material) == expected
    assert expected == b'{"a":"\\u03a9","z":1}'
    with pytest.raises(ValueError):
        evidence_store._canonical_json_bytes({"value": float("nan")})
