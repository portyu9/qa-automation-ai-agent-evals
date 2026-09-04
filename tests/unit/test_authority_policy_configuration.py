from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.contracts.models import AuthorityPolicy


@pytest.mark.parametrize("field", ["max_turns", "max_tool_calls", "max_handoffs"])
@pytest.mark.parametrize("invalid_value", [True, False, "1", 1.0, 1.5])
def test_authority_budgets_reject_non_integer_runtime_types(
    field: str,
    invalid_value: object,
) -> None:
    with pytest.raises(ValidationError):
        AuthorityPolicy.model_validate({field: invalid_value})


def test_authority_budgets_preserve_valid_integer_boundaries() -> None:
    policy = AuthorityPolicy(max_turns=1, max_tool_calls=0, max_handoffs=0)

    assert policy.max_turns == 1
    assert policy.max_tool_calls == 0
    assert policy.max_handoffs == 0
