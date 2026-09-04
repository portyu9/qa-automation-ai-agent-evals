"""Integrity-bound receipt for host-refreshed MCP schema-drift agent adaptation."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from itertools import pairwise
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_BRIDGE_SCHEMA: Literal["agent-evals/mcp-agent-tool-schema-drift-receipt/v1"] = (
    "agent-evals/mcp-agent-tool-schema-drift-receipt/v1"
)
_BRIDGE_DOMAIN = b"agent-evals/mcp-agent-tool-schema-drift-receipt/v1\0"
_PROTOCOL_VERSION = "2026-07-28"
_EVENT_SOURCE = "bridge:mcp-agent:tool-schema-drift"
_INITIAL_REQUIRED = {"query": "string"}
_REPLACEMENT_REQUIRED = {
    "customer_id": "integer",
    "include_history": "boolean",
}
_EXPECTED_STALE_ARGUMENTS = {"query": "stale"}
_EXPECTED_RECOVERY_ARGUMENTS = {"customer_id": 7, "include_history": True}
_EXPECTED_RECOVERY_TEXT = "replacement:7:true"


class MCPAgentToolSchemaDriftReceipt(BaseModel):
    """Bind one live MCP schema swap to one exact OpenAI agent adaptation relation.

    The evaluator owns the controlled schema swap and one host-cache invalidation. The receipt does
    not claim that the model requested a refresh. It binds only the live protocol/discovery relation
    and the agent's subsequent use of the refreshed replacement contract.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-agent-tool-schema-drift-receipt/v1"] = _BRIDGE_SCHEMA
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_receipt: MCPFaultReceipt
    agent_tool_name: str = Field(min_length=1, max_length=128)
    stale_call_id: str = Field(min_length=1, max_length=256)
    recovery_call_id: str = Field(min_length=1, max_length=256)
    ttl_ms: StrictInt = Field(gt=0, le=86_400_000)
    initial_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cached_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    refreshed_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stale_arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recovery_arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stale_protocol_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    agent_error_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_recovery_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_recovery_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    agent_recovery_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    initial_list_ordinal: StrictInt = Field(ge=0)
    schema_swap_ordinal: StrictInt = Field(ge=0)
    stale_call_ordinal: StrictInt = Field(ge=0)
    cache_invalidation_ordinal: StrictInt = Field(ge=0)
    refreshed_list_ordinal: StrictInt = Field(ge=0)
    recovery_call_ordinal: StrictInt = Field(ge=0)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        scenario_identity: str,
        fault: MCPFaultSpec,
        protocol_receipt: MCPFaultReceipt,
        agent_tool_name: str,
        stale_call_id: str,
        recovery_call_id: str,
        ttl_ms: int,
        initial_schema: Mapping[str, object],
        cached_schema: Mapping[str, object],
        refreshed_schema: Mapping[str, object],
        stale_arguments: Mapping[str, object] | None,
        recovery_arguments: Mapping[str, object] | None,
        stale_protocol_text: str,
        agent_error_output: object,
        protocol_recovery_text: str,
        agent_recovery_output: object,
        initial_list_ordinal: int,
        schema_swap_ordinal: int,
        stale_call_ordinal: int,
        cache_invalidation_ordinal: int,
        refreshed_list_ordinal: int,
        recovery_call_ordinal: int,
    ) -> Self:
        """Create a receipt only after protocol and agent schema-drift relations both close."""
        validated_protocol = _revalidate_protocol_receipt(protocol_receipt)
        _require_schema_drift_fault(fault=fault, receipt=validated_protocol, ttl_ms=ttl_ms)
        _validate_identity_text(agent_tool_name, label="agent tool name")
        _validate_identity_text(stale_call_id, label="stale call ID")
        _validate_identity_text(recovery_call_id, label="recovery call ID")
        if stale_call_id == recovery_call_id:
            raise ValueError("MCP schema-drift recovery requires distinct OpenAI call IDs")
        if agent_tool_name != fault.tool_name:
            raise ValueError("agent tool name does not match controlled MCP schema-drift tool")

        initial_schema_sha256 = _schema_digest(initial_schema)
        cached_schema_sha256 = _schema_digest(cached_schema)
        refreshed_schema_sha256 = _schema_digest(refreshed_schema)
        expected_initial_sha256 = _sha256_json(_schema_contract(_INITIAL_REQUIRED))
        expected_replacement_sha256 = _sha256_json(_schema_contract(_REPLACEMENT_REQUIRED))
        if not hmac.compare_digest(initial_schema_sha256, expected_initial_sha256):
            raise ValueError("initial MCP schema does not match the bound v1 contract")
        if not hmac.compare_digest(cached_schema_sha256, expected_initial_sha256):
            raise ValueError("cached MCP schema does not match the bound v1 contract")
        if not hmac.compare_digest(refreshed_schema_sha256, expected_replacement_sha256):
            raise ValueError("refreshed MCP schema does not match the bound replacement contract")

        stale_arguments_sha256 = _sha256_json(_canonical_arguments(stale_arguments))
        recovery_arguments_sha256 = _sha256_json(_canonical_arguments(recovery_arguments))
        if not hmac.compare_digest(
            stale_arguments_sha256,
            _sha256_json(_EXPECTED_STALE_ARGUMENTS),
        ):
            raise ValueError("first MCP schema-drift call does not use the bound stale arguments")
        if not hmac.compare_digest(
            recovery_arguments_sha256,
            _sha256_json(_EXPECTED_RECOVERY_ARGUMENTS),
        ):
            raise ValueError("MCP schema-drift recovery does not use the bound replacement arguments")

        if not stale_protocol_text:
            raise ValueError("stale MCP schema-drift call must expose a non-empty rejection")
        stale_protocol_sha256 = _sha256_text(stale_protocol_text)
        agent_error_text = _extract_single_text_output(agent_error_output, phase="stale-call error")
        agent_error_sha256 = _sha256_text(agent_error_text)
        if not hmac.compare_digest(stale_protocol_sha256, agent_error_sha256):
            raise ValueError("agent-observed schema rejection does not match MCP protocol observation")

        if protocol_recovery_text != _EXPECTED_RECOVERY_TEXT:
            raise ValueError("MCP schema-drift recovery does not match the bound replacement result")
        protocol_recovery_sha256 = _sha256_text(protocol_recovery_text)
        expected_recovery_sha256 = _sha256_text(_EXPECTED_RECOVERY_TEXT)
        agent_recovery_text = _extract_single_text_output(
            agent_recovery_output,
            phase="schema-drift recovery",
        )
        agent_recovery_sha256 = _sha256_text(agent_recovery_text)
        if not hmac.compare_digest(protocol_recovery_sha256, expected_recovery_sha256):
            raise ValueError("MCP protocol recovery does not match expected replacement result")
        if not hmac.compare_digest(agent_recovery_sha256, expected_recovery_sha256):
            raise ValueError("agent-observed recovery does not match expected replacement result")

        ordinals = (
            initial_list_ordinal,
            schema_swap_ordinal,
            stale_call_ordinal,
            cache_invalidation_ordinal,
            refreshed_list_ordinal,
            recovery_call_ordinal,
        )
        _require_protocol_chronology(ordinals)

        observation = _protocol_observation(
            ttl_ms=ttl_ms,
            initial_schema_sha256=initial_schema_sha256,
            cached_schema_sha256=cached_schema_sha256,
            refreshed_schema_sha256=refreshed_schema_sha256,
            stale_protocol_observation_sha256=stale_protocol_sha256,
            protocol_recovery_observation_sha256=protocol_recovery_sha256,
            ordinals=ordinals,
        )
        if not hmac.compare_digest(
            validated_protocol.observation_sha256,
            _sha256_text(observation),
        ):
            raise ValueError("MCP schema-drift protocol receipt does not match observed relation")

        unsigned = {
            "schema_version": _BRIDGE_SCHEMA,
            "scenario_identity": scenario_identity,
            "protocol_receipt": validated_protocol.model_dump(mode="json"),
            "agent_tool_name": agent_tool_name,
            "stale_call_id": stale_call_id,
            "recovery_call_id": recovery_call_id,
            "ttl_ms": ttl_ms,
            "initial_schema_sha256": initial_schema_sha256,
            "cached_schema_sha256": cached_schema_sha256,
            "refreshed_schema_sha256": refreshed_schema_sha256,
            "stale_arguments_sha256": stale_arguments_sha256,
            "recovery_arguments_sha256": recovery_arguments_sha256,
            "stale_protocol_observation_sha256": stale_protocol_sha256,
            "agent_error_observation_sha256": agent_error_sha256,
            "expected_recovery_sha256": expected_recovery_sha256,
            "protocol_recovery_observation_sha256": protocol_recovery_sha256,
            "agent_recovery_observation_sha256": agent_recovery_sha256,
            "initial_list_ordinal": initial_list_ordinal,
            "schema_swap_ordinal": schema_swap_ordinal,
            "stale_call_ordinal": stale_call_ordinal,
            "cache_invalidation_ordinal": cache_invalidation_ordinal,
            "refreshed_list_ordinal": refreshed_list_ordinal,
            "recovery_call_ordinal": recovery_call_ordinal,
        }
        return cls(**unsigned, receipt_root=_receipt_root(unsigned))

    @field_validator("protocol_receipt", mode="before")
    @classmethod
    def revalidate_protocol_receipt(cls, value: Any) -> MCPFaultReceipt:
        return _revalidate_protocol_receipt(value)

    @field_validator("agent_tool_name")
    @classmethod
    def validate_agent_tool_name(cls, value: str) -> str:
        _validate_identity_text(value, label="agent tool name")
        return value

    @field_validator("stale_call_id", "recovery_call_id")
    @classmethod
    def validate_call_id(cls, value: str) -> str:
        _validate_identity_text(value, label="agent call ID")
        return value

    @model_validator(mode="after")
    def verify_bridge(self) -> Self:
        _require_schema_drift_receipt_shape(self.protocol_receipt)
        if self.agent_tool_name != self.protocol_receipt.tool_name:
            raise ValueError("agent tool name does not match verified MCP schema-drift tool")
        if self.stale_call_id == self.recovery_call_id:
            raise ValueError("MCP schema-drift recovery requires distinct OpenAI call IDs")

        expected_initial_sha256 = _sha256_json(_schema_contract(_INITIAL_REQUIRED))
        expected_replacement_sha256 = _sha256_json(_schema_contract(_REPLACEMENT_REQUIRED))
        if not hmac.compare_digest(self.initial_schema_sha256, expected_initial_sha256):
            raise ValueError("initial schema digest does not match bound v1 schema")
        if not hmac.compare_digest(self.cached_schema_sha256, expected_initial_sha256):
            raise ValueError("cached schema digest does not match bound v1 schema")
        if not hmac.compare_digest(self.refreshed_schema_sha256, expected_replacement_sha256):
            raise ValueError("refreshed schema digest does not match bound replacement schema")
        if not hmac.compare_digest(
            self.stale_arguments_sha256,
            _sha256_json(_EXPECTED_STALE_ARGUMENTS),
        ):
            raise ValueError("stale argument digest does not match bound v1 call")
        if not hmac.compare_digest(
            self.recovery_arguments_sha256,
            _sha256_json(_EXPECTED_RECOVERY_ARGUMENTS),
        ):
            raise ValueError("recovery argument digest does not match bound replacement call")
        if not hmac.compare_digest(
            self.stale_protocol_observation_sha256,
            self.agent_error_observation_sha256,
        ):
            raise ValueError("agent schema rejection digest does not match protocol rejection digest")
        if not hmac.compare_digest(
            self.expected_recovery_sha256,
            _sha256_text(_EXPECTED_RECOVERY_TEXT),
        ):
            raise ValueError("expected recovery digest does not match bound replacement result")
        if not hmac.compare_digest(
            self.protocol_recovery_observation_sha256,
            self.expected_recovery_sha256,
        ):
            raise ValueError("protocol recovery digest does not match expected replacement result")
        if not hmac.compare_digest(
            self.agent_recovery_observation_sha256,
            self.expected_recovery_sha256,
        ):
            raise ValueError("agent recovery digest does not match expected replacement result")

        ordinals = (
            self.initial_list_ordinal,
            self.schema_swap_ordinal,
            self.stale_call_ordinal,
            self.cache_invalidation_ordinal,
            self.refreshed_list_ordinal,
            self.recovery_call_ordinal,
        )
        _require_protocol_chronology(ordinals)
        expected_observation = _protocol_observation(
            ttl_ms=self.ttl_ms,
            initial_schema_sha256=self.initial_schema_sha256,
            cached_schema_sha256=self.cached_schema_sha256,
            refreshed_schema_sha256=self.refreshed_schema_sha256,
            stale_protocol_observation_sha256=self.stale_protocol_observation_sha256,
            protocol_recovery_observation_sha256=self.protocol_recovery_observation_sha256,
            ordinals=ordinals,
        )
        if not hmac.compare_digest(
            self.protocol_receipt.observation_sha256,
            _sha256_text(expected_observation),
        ):
            raise ValueError("schema-drift protocol receipt does not match root-bound relation")

        expected_root = _receipt_root(self.model_dump(mode="json", exclude={"receipt_root"}))
        if not hmac.compare_digest(expected_root, self.receipt_root):
            raise ValueError("MCP schema-drift receipt root does not match receipt content")
        return self

    def to_event(self, *, sequence: int) -> EvidenceEvent:
        """Emit protocol-delivery evidence only after the full adaptation relation closes."""
        return EvidenceEvent(
            sequence=sequence,
            kind=EvidenceKind.PROTOCOL_DELIVERY,
            source=_EVENT_SOURCE,
            payload=self.model_dump(mode="json"),
        )


def create_schema_drift_protocol_receipt(
    *,
    fault: MCPFaultSpec,
    ttl_ms: int,
    initial_schema: Mapping[str, object],
    cached_schema: Mapping[str, object],
    refreshed_schema: Mapping[str, object],
    stale_protocol_text: str,
    protocol_recovery_text: str,
    initial_list_ordinal: int,
    schema_swap_ordinal: int,
    stale_call_ordinal: int,
    cache_invalidation_ordinal: int,
    refreshed_list_ordinal: int,
    recovery_call_ordinal: int,
) -> MCPFaultReceipt:
    """Create the protocol-domain receipt for the exact live stdio schema-drift relation."""
    if fault.kind is not MCPFaultKind.TOOL_SCHEMA_DRIFT:
        raise ValueError("agent schema-drift protocol receipt requires TOOL_SCHEMA_DRIFT")
    _require_fault_payload(fault, ttl_ms=ttl_ms)
    initial_schema_sha256 = _schema_digest(initial_schema)
    cached_schema_sha256 = _schema_digest(cached_schema)
    refreshed_schema_sha256 = _schema_digest(refreshed_schema)
    expected_initial_sha256 = _sha256_json(_schema_contract(_INITIAL_REQUIRED))
    expected_replacement_sha256 = _sha256_json(_schema_contract(_REPLACEMENT_REQUIRED))
    if not hmac.compare_digest(initial_schema_sha256, expected_initial_sha256):
        raise ValueError("initial MCP schema does not match the bound v1 contract")
    if not hmac.compare_digest(cached_schema_sha256, expected_initial_sha256):
        raise ValueError("cached MCP schema does not match the bound v1 contract")
    if not hmac.compare_digest(refreshed_schema_sha256, expected_replacement_sha256):
        raise ValueError("refreshed MCP schema does not match the bound replacement contract")
    if not stale_protocol_text:
        raise ValueError("stale MCP schema-drift call must expose a non-empty rejection")
    if protocol_recovery_text != _EXPECTED_RECOVERY_TEXT:
        raise ValueError("MCP schema-drift recovery does not match bound replacement result")

    ordinals = (
        initial_list_ordinal,
        schema_swap_ordinal,
        stale_call_ordinal,
        cache_invalidation_ordinal,
        refreshed_list_ordinal,
        recovery_call_ordinal,
    )
    _require_protocol_chronology(ordinals)
    observation = _protocol_observation(
        ttl_ms=ttl_ms,
        initial_schema_sha256=initial_schema_sha256,
        cached_schema_sha256=cached_schema_sha256,
        refreshed_schema_sha256=refreshed_schema_sha256,
        stale_protocol_observation_sha256=_sha256_text(stale_protocol_text),
        protocol_recovery_observation_sha256=_sha256_text(protocol_recovery_text),
        ordinals=ordinals,
    )
    return MCPFaultReceipt.create(
        fault=fault,
        protocol_version=_PROTOCOL_VERSION,
        injection_point=_protocol_point(fault.tool_name),
        observed_text=observation,
    )


def schema_projection(input_schema: Mapping[str, object]) -> dict[str, object]:
    """Project an MCP JSON Schema into the exact scalar-required contract used by this bridge."""
    required = input_schema.get("required", [])
    properties = input_schema.get("properties", {})
    if not isinstance(required, list) or not isinstance(properties, Mapping):
        raise ValueError("MCP tool schema lacks required/properties structure")
    property_types: dict[str, str] = {}
    for name in required:
        if not isinstance(name, str):
            raise ValueError("MCP tool schema contains a non-string required property")
        property_schema = properties.get(name)
        if not isinstance(property_schema, Mapping):
            raise ValueError(f"MCP tool schema lacks property definition for {name!r}")
        property_type = property_schema.get("type")
        if not isinstance(property_type, str):
            raise ValueError(f"MCP tool schema lacks a scalar type for {name!r}")
        property_types[name] = property_type
    return _schema_contract(property_types)


def _require_schema_drift_fault(
    *,
    fault: MCPFaultSpec,
    receipt: MCPFaultReceipt,
    ttl_ms: int,
) -> None:
    _require_schema_drift_receipt_shape(receipt)
    if fault.kind is not MCPFaultKind.TOOL_SCHEMA_DRIFT:
        raise ValueError("MCP schema-drift bridge requires TOOL_SCHEMA_DRIFT")
    _require_fault_payload(fault, ttl_ms=ttl_ms)
    if receipt.fault_identity != fault.identity:
        raise ValueError("schema-drift protocol receipt identity does not match controlled fault")
    if receipt.tool_name != fault.tool_name:
        raise ValueError("schema-drift protocol receipt tool does not match controlled fault")
    if not hmac.compare_digest(receipt.payload_sha256, fault.payload_sha256):
        raise ValueError("schema-drift protocol receipt payload does not match controlled fault")


def _require_schema_drift_receipt_shape(receipt: MCPFaultReceipt) -> None:
    if receipt.kind is not MCPFaultKind.TOOL_SCHEMA_DRIFT:
        raise ValueError("MCP schema-drift bridge requires TOOL_SCHEMA_DRIFT protocol receipt")
    if receipt.protocol_version != _PROTOCOL_VERSION:
        raise ValueError(f"MCP schema-drift bridge requires protocol version {_PROTOCOL_VERSION}")
    if receipt.injection_point != _protocol_point(receipt.tool_name):
        raise ValueError("MCP schema-drift receipt uses an unexpected protocol observation boundary")


def _require_fault_payload(fault: MCPFaultSpec, *, ttl_ms: int) -> None:
    payload = fault.payload
    if not isinstance(payload, dict):
        raise ValueError("MCP schema-drift fault payload must be an object")
    if payload.get("ttl_ms") != ttl_ms:
        raise ValueError("MCP schema-drift TTL does not match controlled fault")
    if payload.get("initial_required") != _INITIAL_REQUIRED:
        raise ValueError("MCP schema-drift initial contract does not match v1")
    if payload.get("replacement_required") != _REPLACEMENT_REQUIRED:
        raise ValueError("MCP schema-drift replacement contract does not match v1")


def _protocol_point(tool_name: str) -> str:
    return (
        f"mcp:{_PROTOCOL_VERSION}:tools/list:agent-schema-drift:{tool_name}:"
        "cached-old:call-rejects-old:host-refresh-new:call-succeeds-new"
    )


def _protocol_observation(
    *,
    ttl_ms: int,
    initial_schema_sha256: str,
    cached_schema_sha256: str,
    refreshed_schema_sha256: str,
    stale_protocol_observation_sha256: str,
    protocol_recovery_observation_sha256: str,
    ordinals: tuple[int, int, int, int, int, int],
) -> str:
    return _canonical_json(
        {
            "cache_invalidation_ordinal": ordinals[3],
            "cached_schema_sha256": cached_schema_sha256,
            "initial_list_ordinal": ordinals[0],
            "initial_schema_sha256": initial_schema_sha256,
            "protocol_recovery_observation_sha256": protocol_recovery_observation_sha256,
            "recovery_call_ordinal": ordinals[5],
            "refreshed_list_ordinal": ordinals[4],
            "refreshed_schema_sha256": refreshed_schema_sha256,
            "schema_swap_ordinal": ordinals[1],
            "stale_call_ordinal": ordinals[2],
            "stale_protocol_observation_sha256": stale_protocol_observation_sha256,
            "ttl_ms": ttl_ms,
        }
    )


def _require_protocol_chronology(ordinals: tuple[int, int, int, int, int, int]) -> None:
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in ordinals):
        raise ValueError("MCP schema-drift protocol ordinals must be non-negative integers")
    if not all(left < right for left, right in pairwise(ordinals)):
        raise ValueError(
            "MCP schema-drift protocol chronology must be initial-list < swap < stale-call < "
            "cache-invalidation < refreshed-list < recovery-call"
        )


def _schema_digest(input_schema: Mapping[str, object]) -> str:
    return _sha256_json(schema_projection(input_schema))


def _schema_contract(required_types: Mapping[str, str]) -> dict[str, object]:
    return {
        "property_types": dict(sorted(required_types.items())),
        "required": sorted(required_types),
    }


def _canonical_arguments(value: Mapping[str, object] | None) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("MCP schema-drift arguments must be a mapping or None")
    result = dict(value)
    if any(not isinstance(key, str) for key in result):
        raise ValueError("MCP schema-drift argument keys must be strings")
    _canonical_json_bytes(result)
    return result


def _extract_single_text_output(value: object, *, phase: str) -> str:
    if not isinstance(value, Mapping):
        raise ValueError(f"agent MCP {phase} must be one model-visible text output object")
    if set(value) != {"type", "text"}:
        raise ValueError(f"agent MCP {phase} must contain exactly 'type' and 'text'")
    text = value.get("text")
    if value.get("type") != "text" or not isinstance(text, str):
        raise ValueError(f"agent MCP {phase} must be one text output object")
    return text


def _revalidate_protocol_receipt(value: Any) -> MCPFaultReceipt:
    if isinstance(value, MCPFaultReceipt):
        value = value.model_dump(mode="json")
    return MCPFaultReceipt.model_validate(value)


def _validate_identity_text(value: str, *, label: str) -> None:
    if not value.strip():
        raise ValueError(f"{label} must be non-empty")
    if value != value.strip():
        raise ValueError(f"{label} must not contain surrounding whitespace")


def _receipt_root(value: object) -> str:
    return hashlib.sha256(_BRIDGE_DOMAIN + _canonical_json_bytes(value)).hexdigest()


def _sha256_json(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: object) -> str:
    return _canonical_json_bytes(value).decode("utf-8")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")