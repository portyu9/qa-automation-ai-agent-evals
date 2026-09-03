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
async def test_ddmin_rejects_non_reproducing_original() -> None:
    async def never(_items: tuple[str, ...]) -> bool:
        return False

    with pytest.raises(ValueError, match="does not reproduce"):
        await ddmin(["safe"], never)
