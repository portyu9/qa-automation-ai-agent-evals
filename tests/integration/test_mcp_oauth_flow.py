from __future__ import annotations

import hashlib
from urllib.parse import urlsplit

import pytest
from pydantic import ValidationError

from agent_evals.mcp import (
    MCPOAuthFlowLab,
    MCPOAuthFlowPolicy,
    MCPOAuthFlowReceipt,
)

pytestmark = pytest.mark.mcp_oauth


def make_policy(**overrides: object) -> MCPOAuthFlowPolicy:
    values: dict[str, object] = {
        "lab_id": "oauth-separated",
        "revision": "1",
        "resource_path": "/mcp",
        "required_scopes": ("agent-evals.write", "agent-evals.read"),
        "tool_name": "protected_echo",
        "client_name": "agent-evals-oauth-client",
        "redirect_path": "/oauth/callback",
    }
    values.update(overrides)
    return MCPOAuthFlowPolicy.model_validate(values)


def test_oauth_flow_policy_identity_is_canonical_and_fail_closed() -> None:
    left = make_policy(required_scopes=("agent-evals.write", "agent-evals.read"))
    right = make_policy(required_scopes=("agent-evals.read", "agent-evals.write"))

    assert left.required_scopes == ("agent-evals.read", "agent-evals.write")
    assert left.identity == right.identity

    invalid_overrides = (
        {"resource_path": "mcp"},
        {"resource_path": "//mcp"},
        {"resource_path": "/mcp?tenant=7"},
        {"redirect_path": "oauth/callback"},
        {"redirect_path": "//oauth/callback"},
        {"required_scopes": ()},
        {"required_scopes": ("agent-evals.read", "agent-evals.read")},
        {"required_scopes": ("agent evals.read",)},
        {"tool_name": " protected_echo"},
        {"client_name": " agent-evals-client"},
    )
    for overrides in invalid_overrides:
        with pytest.raises(ValidationError):
            make_policy(**overrides)


def test_oauth_flow_receipt_detects_tampering() -> None:
    policy = make_policy()
    receipt = MCPOAuthFlowReceipt.create(
        policy=policy,
        observation_json='{"flow":"verified"}',
    )
    tampered = receipt.model_dump(mode="json")
    tampered["observation_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="receipt root does not match"):
        MCPOAuthFlowReceipt.model_validate(tampered)


@pytest.mark.asyncio
async def test_oauth_flow_separates_as_rs_and_closes_pkce_resource_introspection() -> None:
    policy = make_policy()
    result = await MCPOAuthFlowLab(policy).probe()

    assert result.protocol_version == "2026-07-28"
    assert result.transport == "oauth-code-pkce-loopback"

    issuer = urlsplit(result.issuer_url)
    resource = urlsplit(result.resource_url)
    assert issuer.hostname == "127.0.0.1"
    assert resource.hostname == "127.0.0.1"
    assert issuer.port is not None
    assert resource.port is not None
    assert issuer.port != resource.port
    assert result.resource_url.endswith("/mcp")

    assert result.authorization_metadata_issuer == result.issuer_url
    assert result.authorization_endpoint == f"{result.issuer_url}/authorize"
    assert result.token_endpoint == f"{result.issuer_url}/token"
    assert result.registration_endpoint == f"{result.issuer_url}/register"
    assert result.code_challenge_methods_supported == ("S256",)

    assert result.protected_resource_authorization_servers == (result.issuer_url,)
    assert result.protected_resource_scopes_supported == policy.required_scopes
    assert result.protected_resource_metadata_url.startswith(
        f"http://127.0.0.1:{resource.port}/.well-known/oauth-protected-resource"
    )

    assert result.authorization_request_state_present is True
    assert result.authorization_request_code_challenge_present is True
    assert result.authorization_request_code_challenge_method == "S256"
    assert result.authorization_request_resource == result.resource_url
    assert result.authorization_request_scopes == policy.required_scopes
    assert result.authorization_response_issuer == result.issuer_url

    assert result.registration_count == 1
    assert result.authorization_count == 1
    assert result.token_exchange_count == 1
    assert result.introspection_count >= 3
    assert result.introspection_last_issuer == result.issuer_url
    assert result.introspection_last_resource == result.resource_url
    assert result.introspection_last_scopes == policy.required_scopes
    assert result.reused_stored_authorization is True

    assert result.valid_tool_names == (policy.tool_name,)
    assert result.valid_call_text == ("oauth:agent-evals-user:hello",)
    assert result.reconnect_call_text == ("oauth:agent-evals-user:again",)

    assert result.receipt is not None
    assert result.receipt.policy_identity == policy.identity
    assert result.receipt.protocol_version == result.protocol_version

    serialized = result.model_dump_json()
    for domain in ("authorization-code", "access-token", "introspection-secret"):
        fixture = hashlib.sha256(
            f"agent-evals:{domain}:{policy.identity}:1".encode()
        ).hexdigest()
        assert fixture not in serialized
