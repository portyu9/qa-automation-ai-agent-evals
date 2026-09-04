from __future__ import annotations

import pytest

from agent_evals.minimization.delta import ddmin


@pytest.mark.asyncio
async def test_ddmin_preserves_only_failure_inducing_elements() -> None:
    async def fails(items: tuple[str, ...]) -> bool:
        return "poison" in items and "execute" in items

    result = await ddmin(["hello", "poison", "irrelevant", "execute", "bye"], fails)
    assert set(result.minimized) == {"poison", "execute"}
    assert len(result.minimized) == 2
    assert not result.exhausted


@pytest.mark.asyncio
async def test_ddmin_tests_subsets_for_non_monotonic_failure_predicates() -> None:
    original = ("trigger", "guard", "noise")

    async def fails(items: tuple[str, ...]) -> bool:
        return items == original or items == ("trigger",)

    result = await ddmin(original, fails)

    assert result.original_size == 3
    assert result.minimized == ("trigger",)
    assert not result.exhausted


@pytest.mark.asyncio
async def test_ddmin_respects_evaluation_budget_without_claiming_completion() -> None:
    async def always(_items: tuple[str, ...]) -> bool:
        return True

    result = await ddmin(["a", "b", "c"], always, max_evaluations=1)
    assert result.minimized == ("a", "b", "c")
    assert result.evaluations == 1
    assert result.exhausted is True


@pytest.mark.asyncio
async def test_ddmin_rejects_non_reproducing_original() -> None:
    async def never(_items: tuple[str, ...]) -> bool:
        return False

    with pytest.raises(ValueError, match="does not reproduce"):
        await ddmin(["safe"], never)
