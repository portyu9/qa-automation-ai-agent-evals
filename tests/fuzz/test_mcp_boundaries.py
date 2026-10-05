from __future__ import annotations

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent_evals._strict_json import strict_json_loads
from agent_evals.mcp.lab import (
    MCPFaultLab,
    _schema_contract_json,
    _schema_projection_json,
)
from agent_evals.mcp.models import MCPFaultKind, MCPFaultSpec

pytestmark = pytest.mark.fuzz

_PROTOCOL_VERSION = "2026-07-28"
_SAFE_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    max_size=60,
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
_CONTENT_KINDS = (
    MCPFaultKind.TOOL_METADATA_POISON,
    MCPFaultKind.TOOL_RESULT_POISON,
    MCPFaultKind.TOOL_ERROR,
)


@given(kind=st.sampled_from(_CONTENT_KINDS), payload=_JSON_VALUES)
@settings(max_examples=60, deadline=None)
async def test_generated_content_faults_cross_official_sdk_framing(
    kind: MCPFaultKind,
    payload: object,
) -> None:
    fault = MCPFaultSpec.from_payload(
        fault_id="deep-fuzz-content",
        revision="1",
        kind=kind,
        tool_name="controlled_lookup",
        payload=payload,
    )

    result = await MCPFaultLab(fault).probe()

    assert result.protocol_version == _PROTOCOL_VERSION
    assert result.receipt is not None
    assert result.receipt.fault_identity == fault.identity
    assert result.second_call_is_error is False


@given(
    protocol_version=_SAFE_TEXT,
    advertised_description=_SAFE_TEXT,
    first_call_text=st.lists(_SAFE_TEXT, max_size=3).map(tuple),
    first_call_is_error=st.booleans(),
)
@settings(max_examples=600, deadline=None)
def test_content_receipt_requires_exact_protocol_envelope(
    protocol_version: str,
    advertised_description: str,
    first_call_text: tuple[str, ...],
    first_call_is_error: bool,
) -> None:
    fault = MCPFaultSpec.from_payload(
        fault_id="deep-fuzz-result",
        revision="1",
        kind=MCPFaultKind.TOOL_RESULT_POISON,
        tool_name="controlled_lookup",
        payload={"tainted": "value"},
    )
    lab = MCPFaultLab(fault)

    receipt = lab._receipt_for_observation(
        protocol_version=protocol_version,
        advertised_description=advertised_description,
        first_call_text=first_call_text,
        first_call_is_error=first_call_is_error,
    )

    if receipt is not None:
        assert protocol_version == _PROTOCOL_VERSION
        assert first_call_is_error is False
        assert first_call_text == (fault.payload_json,)


@given(
    protocol_version=_SAFE_TEXT,
    initial_names=st.lists(_SAFE_TEXT, max_size=3).map(tuple),
    cached_names=st.lists(_SAFE_TEXT, max_size=3).map(tuple),
    refreshed_names=st.lists(_SAFE_TEXT, max_size=3).map(tuple),
    ttl_ms=st.integers(min_value=-10, max_value=86_400_010),
)
@settings(max_examples=700, deadline=None)
def test_discovery_receipt_requires_exact_list_refresh_order(
    protocol_version: str,
    initial_names: tuple[str, ...],
    cached_names: tuple[str, ...],
    refreshed_names: tuple[str, ...],
    ttl_ms: int,
) -> None:
    fault = MCPFaultSpec.from_payload(
        fault_id="deep-fuzz-cache",
        revision="1",
        kind=MCPFaultKind.TOOL_LIST_STALE_CACHE,
        tool_name="controlled_lookup",
        payload={"ttl_ms": 1000},
    )
    lab = MCPFaultLab(fault)

    receipt = lab._discovery_cache_receipt(
        protocol_version=protocol_version,
        initial_tool_names=initial_names,
        cached_tool_names=cached_names,
        refreshed_tool_names=refreshed_names,
        initial_ttl_ms=ttl_ms,
    )

    if receipt is not None:
        assert protocol_version == _PROTOCOL_VERSION
        assert ttl_ms == 1000
        assert initial_names == ("controlled_lookup",)
        assert cached_names == initial_names
        assert refreshed_names == ()


@given(
    required=st.lists(
        st.one_of(_SAFE_TEXT, st.integers(), st.booleans(), st.none()),
        max_size=8,
    ),
    properties=st.dictionaries(
        _SAFE_TEXT,
        st.one_of(
            st.dictionaries(_SAFE_TEXT, _JSON_SCALARS, max_size=4),
            _JSON_SCALARS,
        ),
        max_size=8,
    ),
)
@settings(max_examples=800, deadline=None)
def test_schema_projection_never_interprets_malformed_shapes(
    required: list[object],
    properties: dict[str, object],
) -> None:
    schema = {"required": required, "properties": properties}
    try:
        projected = _schema_projection_json(schema)
    except RuntimeError:
        return

    decoded = strict_json_loads(projected, label="schema projection", require_object=True)
    assert set(decoded) == {"property_types", "required"}
    assert isinstance(decoded["property_types"], dict)
    assert isinstance(decoded["required"], list)


@given(
    protocol_version=_SAFE_TEXT,
    initial_schema=_SAFE_TEXT,
    cached_schema=_SAFE_TEXT,
    refreshed_schema=_SAFE_TEXT,
    stale_text=st.lists(_SAFE_TEXT, max_size=3).map(tuple),
    stale_is_error=st.booleans(),
    refreshed_text=st.lists(_SAFE_TEXT, max_size=3).map(tuple),
    refreshed_is_error=st.booleans(),
    ttl_ms=st.integers(min_value=-10, max_value=86_400_010),
)
@settings(max_examples=900, deadline=None)
def test_schema_drift_receipt_requires_full_cached_call_refresh_sequence(
    protocol_version: str,
    initial_schema: str,
    cached_schema: str,
    refreshed_schema: str,
    stale_text: tuple[str, ...],
    stale_is_error: bool,
    refreshed_text: tuple[str, ...],
    refreshed_is_error: bool,
    ttl_ms: int,
) -> None:
    fault = MCPFaultSpec.from_payload(
        fault_id="deep-fuzz-schema",
        revision="1",
        kind=MCPFaultKind.TOOL_SCHEMA_DRIFT,
        tool_name="controlled_lookup",
        payload={
            "ttl_ms": 1000,
            "initial_required": {"query": "string"},
            "replacement_required": {
                "customer_id": "integer",
                "include_history": "boolean",
            },
        },
    )
    lab = MCPFaultLab(fault)

    receipt = lab._schema_drift_receipt(
        protocol_version=protocol_version,
        initial_schema_json=initial_schema,
        cached_schema_json=cached_schema,
        refreshed_schema_json=refreshed_schema,
        stale_call_text=stale_text,
        stale_call_is_error=stale_is_error,
        refreshed_call_text=refreshed_text,
        refreshed_call_is_error=refreshed_is_error,
        initial_ttl_ms=ttl_ms,
    )

    if receipt is not None:
        assert protocol_version == _PROTOCOL_VERSION
        assert ttl_ms == 1000
        assert initial_schema == _schema_contract_json({"query": "string"})
        assert cached_schema == initial_schema
        assert refreshed_schema == _schema_contract_json(
            {"customer_id": "integer", "include_history": "boolean"}
        )
        assert stale_is_error is True
        assert stale_text
        assert refreshed_is_error is False
        assert refreshed_text == ("replacement:7:true",)


def test_schema_projection_canonical_output_is_valid_json() -> None:
    projected = _schema_projection_json(
        {
            "required": ["z", "a"],
            "properties": {
                "z": {"type": "boolean"},
                "a": {"type": "integer"},
            },
        }
    )
    assert json.loads(projected) == {
        "property_types": {"a": "integer", "z": "boolean"},
        "required": ["a", "z"],
    }
