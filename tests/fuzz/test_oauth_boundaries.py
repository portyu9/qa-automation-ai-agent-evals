from __future__ import annotations

import time
from urllib.parse import urlencode

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from pydantic import AnyHttpUrl
from starlette.datastructures import Headers
from starlette.requests import Request

from agent_evals.mcp.oauth_flow import (
    MCPOAuthFlowLab,
    MCPOAuthFlowPolicy,
    _access_token_from_introspection,
    _parse_authorization_redirect,
    _single_query_value,
    _strict_response_object,
)
from agent_evals.mcp.remote_auth import _DeterministicTokenVerifier, _TokenRecord

pytestmark = pytest.mark.fuzz

_PROTOCOL_VERSION = "2026-07-28"
_ISSUER = "http://127.0.0.1:41001/"
_RESOURCE = "http://127.0.0.1:42001/mcp"
_METADATA = "http://127.0.0.1:42001/.well-known/oauth-protected-resource/mcp"
_BEARER_ISSUER = "https://issuer.agent-evals.invalid/"
_BEARER_RESOURCE = "https://resource.agent-evals.invalid/mcp"
_BEARER_TOKEN = "deep-fuzz-valid-token"
_FIXED_NOW = 2_000_000_000
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
_NONEMPTY_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=30,
)
_AUTHORIZATION_CASING = st.tuples(*[
    st.sampled_from((character.lower(), character.upper()))
    for character in "Authorization"
]).map("".join)
_BEARER_CASING = st.tuples(*[
    st.sampled_from((character.lower(), character.upper()))
    for character in "Bearer"
]).map("".join)

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


@given(
    header_name=_AUTHORIZATION_CASING,
    scheme=_BEARER_CASING,
    separator=st.sampled_from((" ", "  ", "\t", "", " \t")),
    token=st.one_of(
        st.just(_BEARER_TOKEN),
        st.text(
            alphabet=st.characters(min_codepoint=33, max_codepoint=126),
            max_size=40,
        ).filter(lambda value: value != _BEARER_TOKEN),
    ),
)
@settings(max_examples=700, deadline=None)
async def test_bearer_header_parsing_matches_pinned_sdk_contract(
    header_name: str,
    scheme: str,
    separator: str,
    token: str,
) -> None:
    verifier = _DeterministicTokenVerifier(
        expected_issuer=_BEARER_ISSUER,
        expected_resource=_BEARER_RESOURCE,
        records={
            _BEARER_TOKEN: _TokenRecord(
                issuer=_BEARER_ISSUER,
                resource=_BEARER_RESOURCE,
                scopes=("read",),
            )
        },
    )
    backend = BearerAuthBackend(
        verifier,
        resource_server_url=AnyHttpUrl(_BEARER_RESOURCE),
    )
    header_value = f"{scheme}{separator}{token}"
    headers = Headers({header_name: header_value})
    request = Request({"type": "http", "headers": headers.raw})

    result = await backend.authenticate(request)

    expected = header_value.lower().startswith("bearer ") and header_value[7:] == _BEARER_TOKEN
    assert (result is not None) is expected


@given(
    issuer=st.one_of(
        st.just(_BEARER_ISSUER),
        _NONEMPTY_TEXT.filter(lambda value: value != _BEARER_ISSUER),
    ),
    resource=st.one_of(
        st.just(_BEARER_RESOURCE),
        _NONEMPTY_TEXT.filter(lambda value: value != _BEARER_RESOURCE),
    ),
)
@settings(max_examples=500, deadline=None)
async def test_token_verifier_requires_exact_issuer_and_resource(
    issuer: str,
    resource: str,
) -> None:
    verifier = _DeterministicTokenVerifier(
        expected_issuer=_BEARER_ISSUER,
        expected_resource=_BEARER_RESOURCE,
        records={
            _BEARER_TOKEN: _TokenRecord(
                issuer=issuer,
                resource=resource,
                scopes=("read",),
            )
        },
    )

    result = await verifier.verify_token(_BEARER_TOKEN)

    assert (result is not None) is (
        issuer == _BEARER_ISSUER and resource == _BEARER_RESOURCE
    )


@given(
    code_values=st.lists(_NONEMPTY_TEXT, max_size=2),
    state_values=st.lists(_NONEMPTY_TEXT, max_size=2),
    issuer_values=st.lists(_NONEMPTY_TEXT, max_size=2),
    fragment=_SAFE_TEXT,
)
@settings(max_examples=800, deadline=None)
def test_authorization_redirect_requires_unique_code_state_and_issuer(
    code_values: list[str],
    state_values: list[str],
    issuer_values: list[str],
    fragment: str,
) -> None:
    query = urlencode(
        [
            *(("code", value) for value in code_values),
            *(("state", value) for value in state_values),
            *(("iss", value) for value in issuer_values),
        ]
    )
    location = f"https://client.example/callback?{query}#{fragment}"

    code, state, issuer = _parse_authorization_redirect(location)

    assert code == (code_values[0] if len(code_values) == 1 else "")
    assert state == (state_values[0] if len(state_values) == 1 else None)
    assert issuer == (issuer_values[0] if len(issuer_values) == 1 else None)


@given(payload=st.binary(max_size=4096))
@settings(max_examples=900, deadline=None)
def test_oauth_introspection_raw_bytes_fail_closed(payload: bytes) -> None:
    try:
        decoded = _strict_response_object(
            payload,
            label="OAuth introspection response",
        )
    except RuntimeError:
        return

    assert type(decoded) is dict


@given(
    active=st.one_of(st.booleans(), _JSON_SCALARS),
    issuer=st.one_of(st.just(_ISSUER), _JSON_SCALARS),
    resource=st.one_of(st.just(_RESOURCE), _JSON_SCALARS),
    scope=st.one_of(st.just("read write"), _JSON_SCALARS),
    client_id=st.one_of(st.just("client-1"), _JSON_SCALARS),
    expires_at=st.one_of(
        st.none(),
        st.just(_FIXED_NOW + 3600),
        st.integers(min_value=0, max_value=_FIXED_NOW),
        st.booleans(),
        _SAFE_TEXT,
    ),
    subject=st.one_of(st.none(), _SAFE_TEXT, st.integers()),
)
@settings(max_examples=1200, deadline=None)
def test_introspection_claim_types_and_bindings_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    active: object,
    issuer: object,
    resource: object,
    scope: object,
    client_id: object,
    expires_at: object,
    subject: object,
) -> None:
    monkeypatch.setattr("agent_evals.mcp.oauth_flow.time.time", lambda: float(_FIXED_NOW))
    data = {
        "active": active,
        "iss": issuer,
        "aud": resource,
        "scope": scope,
        "client_id": client_id,
        "exp": expires_at,
        "sub": subject,
    }

    result = _access_token_from_introspection(
        data,
        token=_BEARER_TOKEN,
        expected_issuer=_ISSUER,
        expected_resource=_RESOURCE,
    )

    expected = (
        active is True
        and type(issuer) is str
        and issuer == _ISSUER
        and type(resource) is str
        and resource == _RESOURCE
        and type(scope) is str
        and type(client_id) is str
        and bool(client_id)
        and (
            expires_at is None
            or (type(expires_at) is int and expires_at > _FIXED_NOW)
        )
        and (subject is None or type(subject) is str)
    )
    assert (result is not None) is expected
