from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from agent_evals.mcp.models import (
    MCPDiscoveryProbeResult,
    MCPFaultKind,
    MCPFaultReceipt,
    MCPFaultSpec,
    MCPProbeResult,
    MCPToolIdentityDriftProbeResult,
    MCPToolSchemaDriftProbeResult,
)

_PROTOCOL_VERSION = "2026-07-28"
_TOOL = "lookup_customer"


def _content_fault(*, fault_id: str = "probe-content-fault") -> MCPFaultSpec:
    return MCPFaultSpec.from_payload(
        fault_id=fault_id,
        revision="1",
        kind=MCPFaultKind.TOOL_RESULT_POISON,
        tool_name=_TOOL,
        payload={"message": "controlled"},
    )


def _receipt(
    fault: MCPFaultSpec,
    *,
    protocol_version: str = _PROTOCOL_VERSION,
) -> MCPFaultReceipt:
    return MCPFaultReceipt.create(
        fault=fault,
        protocol_version=protocol_version,
        injection_point=f"mcp:{protocol_version}:test:{fault.tool_name}",
        observed_text="controlled observation",
    )


def test_fault_rejects_blank_and_surrounding_whitespace_tool_names() -> None:
    for tool_name, message in ((" ", "non-empty"), (" lookup_customer", "surrounding whitespace")):
        with pytest.raises(ValidationError, match=message):
            MCPFaultSpec.from_payload(
                fault_id="invalid-tool-name",
                revision="1",
                kind=MCPFaultKind.TOOL_RESULT_POISON,
                tool_name=tool_name,
                payload={"message": "controlled"},
            )


def test_identity_drift_rejects_replacement_name_over_bound() -> None:
    with pytest.raises(ValidationError, match="at most 128 characters"):
        MCPFaultSpec.from_payload(
            fault_id="identity-name-too-long",
            revision="1",
            kind=MCPFaultKind.TOOL_IDENTITY_DRIFT,
            tool_name=_TOOL,
            payload={"ttl_ms": 60_000, "replacement_tool_name": "x" * 129},
        )


def test_fault_rejects_syntactically_invalid_payload_json() -> None:
    with pytest.raises(ValidationError, match="must contain valid JSON"):
        MCPFaultSpec(
            fault_id="invalid-payload-json",
            revision="1",
            kind=MCPFaultKind.TOOL_RESULT_POISON,
            tool_name=_TOOL,
            payload_json='{"message":',
        )


@pytest.mark.parametrize(
    ("kind", "payload", "label"),
    [
        (MCPFaultKind.TOOL_LIST_STALE_CACHE, [60_000], "stale-cache"),
        (MCPFaultKind.TOOL_SCHEMA_DRIFT, "schema", "schema-drift"),
        (MCPFaultKind.TOOL_IDENTITY_DRIFT, 60_000, "identity-drift"),
    ],
)
def test_protocol_state_faults_require_object_payloads(
    kind: MCPFaultKind, payload: object, label: str
) -> None:
    with pytest.raises(ValidationError, match=rf"MCP {label} fault payload must be an object"):
        MCPFaultSpec.from_payload(
            fault_id=f"non-object-{label}",
            revision="1",
            kind=kind,
            tool_name=_TOOL,
            payload=payload,
        )


@pytest.mark.parametrize(
    ("kind", "payload", "expected_keys"),
    [
        (MCPFaultKind.TOOL_LIST_STALE_CACHE, {}, "ttl_ms"),
        (
            MCPFaultKind.TOOL_SCHEMA_DRIFT,
            {
                "ttl_ms": 60_000,
                "initial_required": {"query": "string"},
            },
            "initial_required, replacement_required, ttl_ms",
        ),
        (
            MCPFaultKind.TOOL_IDENTITY_DRIFT,
            {"ttl_ms": 60_000, "replacement_tool_name": "lookup_customer_v2", "extra": True},
            "replacement_tool_name, ttl_ms",
        ),
    ],
)
def test_protocol_state_faults_require_exact_payload_keys(
    kind: MCPFaultKind, payload: object, expected_keys: str
) -> None:
    with pytest.raises(ValidationError, match=rf"must contain exactly: {expected_keys}"):
        MCPFaultSpec.from_payload(
            fault_id=f"invalid-exact-keys-{kind.value}",
            revision="1",
            kind=kind,
            tool_name=_TOOL,
            payload=payload,
        )


@pytest.mark.parametrize("ttl_ms", [1.5, "60000", True])
@pytest.mark.parametrize(
    ("kind", "payload_factory", "label"),
    [
        (
            MCPFaultKind.TOOL_LIST_STALE_CACHE,
            lambda ttl: {"ttl_ms": ttl},
            "stale-cache",
        ),
        (
            MCPFaultKind.TOOL_SCHEMA_DRIFT,
            lambda ttl: {
                "ttl_ms": ttl,
                "initial_required": {"query": "string"},
                "replacement_required": {
                    "customer_id": "integer",
                    "include_history": "boolean",
                },
            },
            "schema-drift",
        ),
        (
            MCPFaultKind.TOOL_IDENTITY_DRIFT,
            lambda ttl: {"ttl_ms": ttl, "replacement_tool_name": "lookup_customer_v2"},
            "identity-drift",
        ),
    ],
)
def test_protocol_state_faults_reject_non_integer_ttl(
    kind: MCPFaultKind,
    payload_factory: Callable[[object], dict[str, object]],
    label: str,
    ttl_ms: object,
) -> None:
    with pytest.raises(ValidationError, match=rf"MCP {label} ttl_ms must be an integer"):
        MCPFaultSpec.from_payload(
            fault_id=f"invalid-ttl-type-{kind.value}",
            revision="1",
            kind=kind,
            tool_name=_TOOL,
            payload=payload_factory(ttl_ms),
        )


@pytest.mark.parametrize("ttl_ms", [-1, 86_400_001])
def test_identity_drift_rejects_ttl_outside_bounds(ttl_ms: int) -> None:
    with pytest.raises(ValidationError, match="between 1 and 86400000 milliseconds"):
        MCPFaultSpec.from_payload(
            fault_id=f"identity-ttl-bound-{abs(ttl_ms)}",
            revision="1",
            kind=MCPFaultKind.TOOL_IDENTITY_DRIFT,
            tool_name=_TOOL,
            payload={"ttl_ms": ttl_ms, "replacement_tool_name": "lookup_customer_v2"},
        )


def _content_probe_kwargs() -> dict[str, Any]:
    return {
        "advertised_description": "controlled description",
        "first_call_text": ("first",),
        "first_call_is_error": False,
        "second_call_text": ("second",),
        "second_call_is_error": False,
    }


def _discovery_probe_kwargs() -> dict[str, Any]:
    return {
        "initial_tool_names": (_TOOL,),
        "cached_tool_names": (_TOOL,),
        "refreshed_tool_names": (),
    }


def _schema_probe_kwargs() -> dict[str, Any]:
    return {
        "initial_schema_json": '{"required":["query"]}',
        "cached_schema_json": '{"required":["query"]}',
        "refreshed_schema_json": '{"required":["customer_id","include_history"]}',
        "stale_call_text": ("rejected",),
        "stale_call_is_error": True,
        "refreshed_call_text": ("replacement:7:true",),
        "refreshed_call_is_error": False,
    }


def _identity_probe_kwargs() -> dict[str, Any]:
    return {
        "initial_tool_names": (_TOOL,),
        "cached_tool_names": (_TOOL,),
        "refreshed_tool_names": ("lookup_customer_v2",),
        "stale_call_text": ("unknown tool",),
        "stale_call_is_error": True,
        "replacement_call_text": ("replacement:fresh",),
        "replacement_call_is_error": False,
    }


_PROBE_CASES: tuple[tuple[type[BaseModel], Callable[[], dict[str, Any]]], ...] = (
    (MCPProbeResult, _content_probe_kwargs),
    (MCPDiscoveryProbeResult, _discovery_probe_kwargs),
    (MCPToolSchemaDriftProbeResult, _schema_probe_kwargs),
    (MCPToolIdentityDriftProbeResult, _identity_probe_kwargs),
)


@pytest.mark.parametrize(("probe_type", "kwargs_factory"), _PROBE_CASES)
def test_probe_models_accept_matching_receipt_and_optional_absence(
    probe_type: type[BaseModel], kwargs_factory: Callable[[], dict[str, Any]]
) -> None:
    fault = _content_fault()
    matching = _receipt(fault)
    base = {
        "fault_identity": fault.identity,
        "protocol_version": _PROTOCOL_VERSION,
        **kwargs_factory(),
    }

    with_receipt = probe_type.model_validate({**base, "receipt": matching.model_dump(mode="json")})
    without_receipt = probe_type.model_validate({**base, "receipt": None})

    assert with_receipt.receipt == matching
    assert without_receipt.receipt is None


@pytest.mark.parametrize(("probe_type", "kwargs_factory"), _PROBE_CASES)
def test_probe_models_reject_receipt_from_different_fault_identity(
    probe_type: type[BaseModel], kwargs_factory: Callable[[], dict[str, Any]]
) -> None:
    fault = _content_fault()
    different = _content_fault(fault_id="probe-different-fault")
    payload = {
        "fault_identity": fault.identity,
        "protocol_version": _PROTOCOL_VERSION,
        **kwargs_factory(),
        "receipt": _receipt(different).model_dump(mode="json"),
    }

    with pytest.raises(ValidationError, match="receipt identity does not match probed fault"):
        probe_type.model_validate(payload)


@pytest.mark.parametrize(("probe_type", "kwargs_factory"), _PROBE_CASES)
def test_probe_models_reject_receipt_from_different_protocol_version(
    probe_type: type[BaseModel], kwargs_factory: Callable[[], dict[str, Any]]
) -> None:
    fault = _content_fault()
    payload = {
        "fault_identity": fault.identity,
        "protocol_version": _PROTOCOL_VERSION,
        **kwargs_factory(),
        "receipt": _receipt(fault, protocol_version="2025-03-26").model_dump(mode="json"),
    }

    with pytest.raises(ValidationError, match="receipt protocol version does not match probe"):
        probe_type.model_validate(payload)
