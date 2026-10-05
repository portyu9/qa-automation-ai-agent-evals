from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_evals.mcp.oauth_flow import (
    MCPOAuthFlowLab,
    MCPOAuthFlowPolicy,
    _single_query_value,
    _strict_response_object,
)

pytestmark = pytest.mark.fuzz

_PROTOCOL_VERSION = "2026-07-28"
_ISSUER = "http://127.0.0.1:41001/"
_RESOURCE = "http://127.0.0.1:42001/mcp"
_METADATA = "http://127.0.0.1:42001/.well-known/oauth-protected-resource/mcp"
_SAFE_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    max_size=80,
)
_JSON_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-(10**40), max_value=10**40),
    st.floats(allow_nan=False, allow_infinity=False, width=64),
    _SAFE_TEXT,
)
_JSON_VALUES = st.recursive(
    _JSON_SCALARS,
    lambda children: st.one_of(
        st.lists(children, max_size=5),
        st.dictionaries(_SAFE_TEXT, children, max_size=5),
    ),
    max_leaves=24,
)


def _lab() -> MCPOAuthFlowLab:
    return MCPOAuthFlowLab(
        MCPOAuthFlowPolicy(
            lab_id="deep-fuzz-oauth",
            revision="1",
            required_scopes=("read", "write"),
            tool_name="protected_lookup",
        )
    )


def _valid_receipt_arguments() -> dict[str, object]:
    return {
        "protocol_version": _PROTOCOL_VERSION,
        "issuer_url": _ISSUER,
        "resource_url": _RESOURCE,
        "metadata_url": _METADATA,
        "as_metadata": {
            "issuer": _ISSUER,
            "authorization_endpoint": f"{_ISSUER}authorize",
            "token_endpoint": f"{_ISSUER}token",
            "registration_endpoint": f"{_ISSUER}register",
            "code_challenge_methods_supported": ["S256"],
        },
        "prm": {
            "resource": _RESOURCE,
            "authorization_servers": [_ISSUER],
            "scopes_supported": ["write", "read"],
        },
        "request": {
            "state": "opaque-state",
            "code_challenge": "opaque-challenge",
            "code_challenge_method": "S256",
            "resource": _RESOURCE,
            "scope": "write read",
        },
        "response": {"iss": _ISSUER},
        "introspection": {
            "active": True,
            "iss": _ISSUER,
            "aud": _RESOURCE,
            "scope": "read write",
        },
        "valid_tool_names": ("protected_lookup",),
        "valid_call_text": ("oauth:agent-evals-user:hello",),
        "reconnect_call_text": ("oauth:agent-evals-user:again",),
        "counts_after_first": (1, 1, 1),
        "counts_after_second": (1, 1, 1),
        "introspection_count": 3,
    }


@given(payload=st.binary(max_size=4096))
@settings(max_examples=1000, deadline=None)
def test_oauth_discovery_raw_bytes_fail_closed(payload: bytes) -> None:
    try:
        decoded = _strict_response_object(payload, label="OAuth fuzz metadata")
    except RuntimeError:
        return

    assert type(decoded) is dict


@pytest.mark.parametrize(
    "payload",
    [
        b'{"issuer":"one","issuer":"two"}',
        b'{"issuer":NaN}',
        b'{"issuer":1e9999}',
        b'{"issuer":"\xff"}',
    ],
)
def test_oauth_discovery_rejects_ambiguous_or_invalid_json(payload: bytes) -> None:
    with pytest.raises(RuntimeError, match="strict bounded JSON"):
        _strict_response_object(payload, label="OAuth fuzz metadata")


def test_oauth_receipt_is_reachable_only_for_complete_exact_flow() -> None:
    receipt = _lab()._receipt_for_observation(**_valid_receipt_arguments())

    assert receipt is not None
    assert receipt.protocol_version == _PROTOCOL_VERSION


@given(
    as_metadata=st.dictionaries(_SAFE_TEXT, _JSON_VALUES, max_size=10),
    prm=st.dictionaries(_SAFE_TEXT, _JSON_VALUES, max_size=10),
    request=st.dictionaries(_SAFE_TEXT, _JSON_VALUES, max_size=10),
    response=st.dictionaries(_SAFE_TEXT, _JSON_VALUES, max_size=10),
    introspection=st.dictionaries(_SAFE_TEXT, _JSON_VALUES, max_size=10),
)
@settings(max_examples=1200, deadline=None)
def test_malformed_plausible_oauth_facts_never_accidentally_issue_receipt(
    as_metadata: dict[str, object],
    prm: dict[str, object],
    request: dict[str, object],
    response: dict[str, object],
    introspection: dict[str, object],
) -> None:
    args = _valid_receipt_arguments()
    args.update(
        {
            "as_metadata": as_metadata,
            "prm": prm,
            "request": request,
            "response": response,
            "introspection": introspection,
        }
    )

    receipt = _lab()._receipt_for_observation(**args)

    if receipt is not None:
        assert as_metadata == _valid_receipt_arguments()["as_metadata"]
        assert prm == _valid_receipt_arguments()["prm"]
        assert request == _valid_receipt_arguments()["request"]
        assert response == _valid_receipt_arguments()["response"]
        assert introspection == _valid_receipt_arguments()["introspection"]


@given(
    values=st.lists(_SAFE_TEXT, max_size=4),
    key=_SAFE_TEXT,
)
@settings(max_examples=500, deadline=None)
def test_authorization_query_requires_one_exact_value(values: list[str], key: str) -> None:
    query = {key: values}

    result = _single_query_value(query, key)

    if len(values) == 1:
        assert result == values[0]
    else:
        assert result == ""
