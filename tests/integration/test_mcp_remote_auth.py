from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_evals.mcp import (
    MCPRemoteAuthLab,
    MCPRemoteAuthPolicy,
    MCPRemoteAuthReceipt,
)

pytestmark = pytest.mark.mcp_remote


def make_policy(**overrides: object) -> MCPRemoteAuthPolicy:
    values: dict[str, object] = {
        "lab_id": "loopback-auth",
        "revision": "1",
        "issuer_url": "https://issuer.agent-evals.invalid",
        "resource_path": "/mcp",
        "required_scopes": ("agent-evals.write", "agent-evals.read"),
        "tool_name": "protected_echo",
    }
    values.update(overrides)
    return MCPRemoteAuthPolicy.model_validate(values)


def test_remote_auth_policy_identity_is_canonical_and_fail_closed() -> None:
    left = make_policy(required_scopes=("agent-evals.write", "agent-evals.read"))
    right = make_policy(required_scopes=("agent-evals.read", "agent-evals.write"))

    assert left.required_scopes == ("agent-evals.read", "agent-evals.write")
    assert left.identity == right.identity

    invalid_overrides = (
        {"issuer_url": "http://issuer.agent-evals.invalid"},
        {"issuer_url": "https://user@issuer.agent-evals.invalid"},
        {"resource_path": "mcp"},
        {"resource_path": "//mcp"},
        {"resource_path": "/mcp?tenant=7"},
        {"required_scopes": ()},
        {"required_scopes": ("agent-evals.read", "agent-evals.read")},
        {"required_scopes": (" agent-evals.read",)},
        {"tool_name": " protected_echo"},
    )
    for overrides in invalid_overrides:
        with pytest.raises(ValidationError):
            make_policy(**overrides)


def test_remote_auth_receipt_detects_tampering() -> None:
    policy = make_policy()
    receipt = MCPRemoteAuthReceipt.create(
        policy=policy,
        observation_json='{"status":"verified"}',
    )
    tampered = receipt.model_dump(mode="json")
    tampered["observation_sha256"] = "0" * 64

    with pytest.raises(ValidationError, match="receipt root does not match"):
        MCPRemoteAuthReceipt.model_validate(tampered)


@pytest.mark.asyncio
async def test_remote_auth_lab_enforces_bearer_scope_metadata_and_valid_mcp_call() -> None:
    policy = make_policy()
    result = await MCPRemoteAuthLab(policy).probe()

    assert result.protocol_version == "2026-07-28"
    assert result.transport == "streamable-http-loopback"
    assert result.resource_url.startswith("http://127.0.0.1:")
    assert result.resource_url.endswith("/mcp")
    assert result.protected_resource_metadata_url.startswith("http://127.0.0.1:")
    assert result.protected_resource_metadata_url.endswith(
        "/.well-known/oauth-protected-resource/mcp"
    )

    assert result.missing_token_status == 401
    assert result.invalid_token_status == 401
    assert result.expired_token_status == 401
    assert result.wrong_issuer_status == 401
    assert result.wrong_resource_status == 401
    assert result.insufficient_scope_status == 403

    assert 'error="invalid_token"' in result.unauthorized_www_authenticate
    assert (
        f'resource_metadata="{result.protected_resource_metadata_url}"'
        in result.unauthorized_www_authenticate
    )
    assert 'error="insufficient_scope"' in result.forbidden_www_authenticate
    assert (
        f'resource_metadata="{result.protected_resource_metadata_url}"'
        in result.forbidden_www_authenticate
    )

    assert result.metadata_resource == result.resource_url
    assert result.metadata_authorization_servers == (policy.issuer_url,)
    assert result.metadata_scopes_supported == policy.required_scopes
    assert result.valid_tool_names == (policy.tool_name,)
    assert result.valid_call_text == ("authorized:hello",)

    assert result.receipt is not None
    assert result.receipt.policy_identity == policy.identity
    assert result.receipt.protocol_version == result.protocol_version
    serialized = result.model_dump_json()
    assert "Bearer " not in serialized
    assert "agent-evals-mcp-auth:" not in serialized
