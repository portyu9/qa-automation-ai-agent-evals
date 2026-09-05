from __future__ import annotations

import pytest

from agent_evals.adapters.base import AdapterPreconditionError
from agent_evals.adapters.openai_mcp_tool_identity_drift import _normalized_request_arguments
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind


def _event(arguments: object) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.TOOL_REQUEST,
        source="test",
        payload={"tool": "lookup_customer", "call_id": "call-1", "arguments": arguments},
    )


def test_identity_argument_parser_accepts_exact_finite_object() -> None:
    parsed = _normalized_request_arguments(_event('{"query":"stale","nested":{"count":1}}'))

    assert parsed == {"query": "stale", "nested": {"count": 1}}


@pytest.mark.parametrize(
    "arguments",
    [
        '{"query":"stale","query":"changed"}',
        '{"query":"stale","score":NaN}',
        '{"query":"stale","score":Infinity}',
        '{"query":"stale","score":-Infinity}',
    ],
)
def test_identity_argument_parser_rejects_duplicate_keys_and_non_finite_constants(
    arguments: str,
) -> None:
    with pytest.raises(AdapterPreconditionError) as exc_info:
        _normalized_request_arguments(_event(arguments))

    assert exc_info.value.code == "mcp_identity_agent_arguments_invalid"
    assert "strict finite JSON" in exc_info.value.reason


def test_identity_argument_parser_rejects_float_overflow() -> None:
    with pytest.raises(AdapterPreconditionError) as exc_info:
        _normalized_request_arguments(_event('{"query":"stale","score":1e309}'))

    assert exc_info.value.code == "mcp_identity_agent_arguments_invalid"
    assert "non-finite numbers" in exc_info.value.reason


@pytest.mark.parametrize("arguments", ["[]", '"stale"', "1", "null"])
def test_identity_argument_parser_requires_top_level_object(arguments: str) -> None:
    with pytest.raises(AdapterPreconditionError) as exc_info:
        _normalized_request_arguments(_event(arguments))

    assert exc_info.value.code == "mcp_identity_agent_arguments_invalid"
    assert "string-keyed object" in exc_info.value.reason


@pytest.mark.parametrize("arguments", [None, ""])
def test_identity_argument_parser_requires_serialized_arguments(arguments: object) -> None:
    with pytest.raises(AdapterPreconditionError) as exc_info:
        _normalized_request_arguments(_event(arguments))

    assert exc_info.value.code == "mcp_identity_agent_arguments_missing"
