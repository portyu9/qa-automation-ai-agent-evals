from __future__ import annotations

import pytest

from agent_evals.adapters.base import AdapterPreconditionError
from agent_evals.adapters.openai_handoff_authority import _require_call_agent_consistency


def test_handoff_authority_requires_result_to_match_attributed_request() -> None:
    with pytest.raises(AdapterPreconditionError) as exc_info:
        _require_call_agent_consistency({}, {"call-1": "Specialist agent"})

    assert exc_info.value.code == "openai_agent_request_attribution_missing"


def test_handoff_authority_requires_request_and_result_agent_to_match() -> None:
    with pytest.raises(AdapterPreconditionError) as exc_info:
        _require_call_agent_consistency(
            {"call-1": "Specialist agent"},
            {"call-1": "Triage agent"},
        )

    assert exc_info.value.code == "openai_agent_call_owner_mismatch"


def test_handoff_authority_accepts_consistent_call_agent_attribution() -> None:
    _require_call_agent_consistency(
        {"call-1": "Specialist agent"},
        {"call-1": "Specialist agent"},
    )
