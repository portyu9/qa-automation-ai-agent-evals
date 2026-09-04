from __future__ import annotations

from typing import cast

import pytest

from agent_evals.minimization.delta import ddmin


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_budget",
    [
        0,
        -1,
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
        1.5,
        "10",
        None,
    ],
)
async def test_ddmin_rejects_invalid_budget_before_evaluating_predicate(
    invalid_budget: object,
) -> None:
    calls = 0

    async def reproduces_failure(_items: tuple[str, ...]) -> bool:
        nonlocal calls
        calls += 1
        return True

    with pytest.raises(ValueError, match="max_evaluations must be a positive integer"):
        await ddmin(
            ("trigger", "noise"),
            reproduces_failure,
            max_evaluations=cast(int, invalid_budget),
        )

    assert calls == 0
