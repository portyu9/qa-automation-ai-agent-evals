from __future__ import annotations

import inspect
from collections.abc import Callable

import pytest
from pydantic import BaseModel

from agent_evals.mcp.agent_identity_bridge import (
    MCPAgentToolIdentityDriftReceipt,
    create_identity_drift_protocol_receipt,
)
from agent_evals.mcp.agent_schema_bridge import (
    MCPAgentToolSchemaDriftReceipt,
    create_schema_drift_protocol_receipt,
)
from agent_evals.mcp.agent_stale_cache_bridge import (
    MCPAgentToolStaleCacheReceipt,
    create_stale_cache_protocol_receipt,
)


@pytest.mark.parametrize(
    "receipt_type",
    [
        MCPAgentToolStaleCacheReceipt,
        MCPAgentToolSchemaDriftReceipt,
        MCPAgentToolIdentityDriftReceipt,
    ],
)
def test_agent_receipt_schema_names_mcp_cache_hint_ownership(
    receipt_type: type[BaseModel],
) -> None:
    assert "mcp_cache_hint_ttl_ms" in receipt_type.model_fields
    assert "ttl_ms" not in receipt_type.model_fields

    parameters = inspect.signature(receipt_type.create).parameters
    assert "mcp_cache_hint_ttl_ms" in parameters
    assert "ttl_ms" not in parameters


@pytest.mark.parametrize(
    "protocol_helper",
    [
        create_stale_cache_protocol_receipt,
        create_schema_drift_protocol_receipt,
        create_identity_drift_protocol_receipt,
    ],
)
def test_protocol_helpers_retain_protocol_cache_hint_name(
    protocol_helper: Callable[..., object],
) -> None:
    parameters = inspect.signature(protocol_helper).parameters
    assert "ttl_ms" in parameters
    assert "mcp_cache_hint_ttl_ms" not in parameters
