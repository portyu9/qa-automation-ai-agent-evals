from __future__ import annotations

import pytest

from agent_evals.adversarial import delivery as attack_delivery
from agent_evals.evidence.limits import RECEIPT_MATERIAL_BUDGET, ResourceLimitError
from agent_evals.retrieval import receipt as retrieval_receipt
from agent_evals.semantic import receipt as semantic_receipt
from agent_evals.side_effect import receipt as side_effect_receipt


def _oversized_material() -> dict[str, str]:
    return {"oversized": "x" * (RECEIPT_MATERIAL_BUDGET.max_utf8_bytes + 1)}


def test_attack_receipt_rejects_before_canonicalization(monkeypatch: pytest.MonkeyPatch) -> None:
    def should_not_run(_value: object) -> bytes:
        raise AssertionError("attack receipt canonicalizer must not run for over-budget material")

    monkeypatch.setattr(attack_delivery, "_canonical_json_bytes", should_not_run)

    with pytest.raises(ResourceLimitError, match="UTF-8 material bytes"):
        attack_delivery._receipt_root(_oversized_material())


def test_semantic_receipt_rejects_before_canonicalization(monkeypatch: pytest.MonkeyPatch) -> None:
    def should_not_run(_value: object) -> bytes:
        raise AssertionError("semantic receipt canonicalizer must not run for over-budget material")

    monkeypatch.setattr(semantic_receipt, "_canonical_json_bytes", should_not_run)

    with pytest.raises(ResourceLimitError, match="UTF-8 material bytes"):
        semantic_receipt._receipt_root(_oversized_material())


def test_side_effect_receipt_rejects_before_json_dumps(monkeypatch: pytest.MonkeyPatch) -> None:
    def should_not_run(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("side-effect json.dumps must not run for over-budget material")

    monkeypatch.setattr(side_effect_receipt.json, "dumps", should_not_run)

    with pytest.raises(ResourceLimitError, match="UTF-8 material bytes"):
        side_effect_receipt._receipt_root(_oversized_material())


def test_retrieval_receipt_rejects_before_json_dumps(monkeypatch: pytest.MonkeyPatch) -> None:
    def should_not_run(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("retrieval json.dumps must not run for over-budget material")

    monkeypatch.setattr(retrieval_receipt.json, "dumps", should_not_run)

    with pytest.raises(ResourceLimitError, match="UTF-8 material bytes"):
        retrieval_receipt._receipt_root(_oversized_material())
