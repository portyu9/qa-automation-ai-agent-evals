"""Integrity-bound receipt for host-refreshed MCP stale-tool removal delivery."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_BRIDGE_SCHEMA: Literal["agent-evals/mcp-agent-tool-stale-cache-receipt/v1"] = (
    "agent-evals/mcp-agent-tool-stale-cache-receipt/v1"
)
_BRIDGE_DOMAIN = b"agent-evals/mcp-agent-tool-stale-cache-receipt/v1\0"
_PROTOCOL_VERSION = "2026-07-28"
_EVENT_SOURCE = "bridge:mcp-agent:tool-stale-cache"
_EXPECTED_STALE_ARGUMENTS = {"query": "stale"}
_MAX_CACHE_TTL_MS = 86_400_000


class MCPAgentToolStaleCacheReceipt(BaseModel):
    """Bind one stale cached tool to exact removal delivery at the OpenAI model boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-agent-tool-stale-cache-receipt/v1"] = _BRIDGE_SCHEMA
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_receipt: MCPFaultReceipt
    tool_name: str = Field(min_length=1, max_length=128)
    stale_call_id: str = Field(min_length=1, max_length=256)
    ttl_ms: StrictInt = Field(gt=0, le=_MAX_CACHE_TTL_MS)
    stale_arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stale_protocol_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    agent_error_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    initial_model_tool_names_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    refreshed_model_tool_names_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    initial_list_ordinal: StrictInt = Field(ge=0)
    removal_ordinal: StrictInt = Field(ge=0)
    cached_list_ordinal: StrictInt = Field(ge=0)
    stale_call_ordinal: StrictInt = Field(ge=0)
    cache_invalidation_ordinal: StrictInt = Field(ge=0)
    refreshed_list_ordinal: StrictInt = Field(ge=0)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        scenario_identity: str,
        fault: MCPFaultSpec,
        protocol_receipt: MCPFaultReceipt,
        tool_name: str,
        stale_call_id: str,
        ttl_ms: int,
        stale_arguments: Mapping[str, object] | None,
        stale_protocol_text: str,
        agent_error_output: object,
        initial_model_tool_names: Sequence[str],
        refreshed_model_tool_names: Sequence[str],
        initial_list_ordinal: int,
        removal_ordinal: int,
        cached_list_ordinal: int,
        stale_call_ordinal: int,
        cache_invalidation_ordinal: int,
        refreshed_list_ordinal: int,
    ) -> Self:
        """Create only after protocol, model-visible, and normalized agent relations close."""
        validated_protocol = _revalidate_protocol_receipt(protocol_receipt)
        _require_stale_cache_fault(
            fault=fault,
            receipt=validated_protocol,
            ttl_ms=ttl_ms,
        )
        _validate_identity_text(tool_name, label="tool name")
        _validate_identity_text(stale_call_id, label="stale call ID")
        if tool_name != fault.tool_name:
            raise ValueError("stale-cache tool name does not match controlled MCP fault")

        stale_arguments_sha256 = _sha256_json(_canonical_arguments(stale_arguments))
        if not hmac.compare_digest(
            stale_arguments_sha256,
            _sha256_json(_EXPECTED_STALE_ARGUMENTS),
        ):
            raise ValueError("MCP stale-cache call does not use bound stale arguments")

        if not stale_protocol_text or "unknown tool" not in stale_protocol_text.lower():
            raise ValueError("removed MCP stale-cache tool must expose an unknown-tool rejection")
        stale_protocol_sha256 = _sha256_text(stale_protocol_text)
        agent_error_text = _extract_single_text_output(agent_error_output)
        agent_error_sha256 = _sha256_text(agent_error_text)
        if not hmac.compare_digest(stale_protocol_sha256, agent_error_sha256):
            raise ValueError("agent-observed stale-tool rejection does not match MCP observation")

        initial_names = _canonical_tool_names(initial_model_tool_names)
        refreshed_names = _canonical_tool_names(refreshed_model_tool_names)
        if initial_names != (tool_name,):
            raise ValueError("initial model-visible controlled tool set must contain only target")
        if refreshed_names:
            raise ValueError("refreshed model-visible controlled tool set must prove target absence")
        initial_model_tool_names_sha256 = _sha256_json(initial_names)
        refreshed_model_tool_names_sha256 = _sha256_json(refreshed_names)

        ordinals = (
            initial_list_ordinal,
            removal_ordinal,
            cached_list_ordinal,
            stale_call_ordinal,
            cache_invalidation_ordinal,
            refreshed_list_ordinal,
        )
        _require_protocol_chronology(ordinals)
        _require_protocol_observation(
            validated_protocol,
            tool_name=tool_name,
            ttl_ms=ttl_ms,
        )

        unsigned = {
            "schema_version": _BRIDGE_SCHEMA,
            "scenario_identity": scenario_identity,
            "protocol_receipt": validated_protocol.model_dump(mode="json"),
            "tool_name": tool_name,
            "stale_call_id": stale_call_id,
            "ttl_ms": ttl_ms,
            "stale_arguments_sha256": stale_arguments_sha256,
            "stale_protocol_observation_sha256": stale_protocol_sha256,
            "agent_error_observation_sha256": agent_error_sha256,
            "initial_model_tool_names_sha256": initial_model_tool_names_sha256,
            "refreshed_model_tool_names_sha256": refreshed_model_tool_names_sha256,
            "initial_list_ordinal": initial_list_ordinal,
            "removal_ordinal": removal_ordinal,
            "cached_list_ordinal": cached_list_ordinal,
            "stale_call_ordinal": stale_call_ordinal,
            "cache_invalidation_ordinal": cache_invalidation_ordinal,
            "refreshed_list_ordinal": refreshed_list_ordinal,
        }
        return cls.model_validate({**unsigned, "receipt_root": _receipt_root(unsigned)})

    @field_validator("protocol_receipt", mode="before")
    @classmethod
    def revalidate_protocol_receipt(cls, value: Any) -> MCPFaultReceipt:
        return _revalidate_protocol_receipt(value)

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        _validate_identity_text(value, label="tool name")
        return value

    @field_validator("stale_call_id")
    @classmethod
    def validate_call_id(cls, value: str) -> str:
        _validate_identity_text(value, label="stale call ID")
        return value

    @model_validator(mode="after")
    def verify_bridge(self) -> Self:
        _require_stale_cache_receipt_shape(self.protocol_receipt)
        if self.tool_name != self.protocol_receipt.tool_name:
            raise ValueError("stale-cache tool name does not match verified MCP protocol receipt")

        expected_payload_sha256 = _sha256_json({"ttl_ms": self.ttl_ms})
        if not hmac.compare_digest(
            self.protocol_receipt.payload_sha256,
            expected_payload_sha256,
        ):
            raise ValueError("stale-cache protocol payload digest does not match bound TTL")
        if not hmac.compare_digest(
            self.stale_arguments_sha256,
            _sha256_json(_EXPECTED_STALE_ARGUMENTS),
        ):
            raise ValueError("stale argument digest does not match bound target call")
        if not hmac.compare_digest(
            self.stale_protocol_observation_sha256,
            self.agent_error_observation_sha256,
        ):
            raise ValueError("agent stale-tool rejection digest does not match protocol rejection")
        if not hmac.compare_digest(
            self.initial_model_tool_names_sha256,
            _sha256_json((self.tool_name,)),
        ):
            raise ValueError("initial model-visible tool digest does not match controlled target")
        if not hmac.compare_digest(
            self.refreshed_model_tool_names_sha256,
            _sha256_json(()),
        ):
            raise ValueError("refreshed model-visible tool digest does not prove target absence")

        ordinals = (
            self.initial_list_ordinal,
            self.removal_ordinal,
            self.cached_list_ordinal,
            self.stale_call_ordinal,
            self.cache_invalidation_ordinal,
            self.refreshed_list_ordinal,
        )
        _require_protocol_chronology(ordinals)
        _require_protocol_observation(
            self.protocol_receipt,
            tool_name=self.tool_name,
            ttl_ms=self.ttl_ms,
        )

        expected_root = _receipt_root(self.model_dump(mode="json", exclude={"receipt_root"}))
        if not hmac.compare_digest(expected_root, self.receipt_root):
            raise ValueError("MCP stale-cache bridge root does not match receipt content")
        return self

    def to_event(self, *, sequence: int) -> EvidenceEvent:
        return EvidenceEvent(
            sequence=sequence,
            kind=EvidenceKind.PROTOCOL_DELIVERY,
            source=_EVENT_SOURCE,
            payload=self.model_dump(mode="json"),
        )


def create_stale_cache_protocol_receipt(
    *,
    fault: MCPFaultSpec,
    ttl_ms: int,
    initial_tool_names: Sequence[str],
    cached_tool_names: Sequence[str],
    refreshed_tool_names: Sequence[str],
) -> MCPFaultReceipt:
    """Create the existing stale-cache protocol receipt from exact live discovery observations."""
    if fault.kind is not MCPFaultKind.TOOL_LIST_STALE_CACHE:
        raise ValueError("agent stale-cache protocol receipt requires TOOL_LIST_STALE_CACHE")
    _require_fault_payload(fault, ttl_ms=ttl_ms)

    initial_names = _canonical_tool_names(initial_tool_names)
    cached_names = _canonical_tool_names(cached_tool_names)
    refreshed_names = _canonical_tool_names(refreshed_tool_names)
    if initial_names != (fault.tool_name,):
        raise ValueError("stale-cache initial discovery must contain only controlled target")
    if cached_names != initial_names:
        raise ValueError("stale-cache post-removal cached discovery must retain controlled target")
    if refreshed_names:
        raise ValueError("stale-cache refreshed discovery must prove controlled target absence")

    return MCPFaultReceipt.create(
        fault=fault,
        protocol_version=_PROTOCOL_VERSION,
        injection_point=_protocol_point(fault.tool_name),
        observed_text=_protocol_observation(tool_name=fault.tool_name, ttl_ms=ttl_ms),
    )


def _require_stale_cache_fault(
    *,
    fault: MCPFaultSpec,
    receipt: MCPFaultReceipt,
    ttl_ms: int,
) -> None:
    _require_stale_cache_receipt_shape(receipt)
    if fault.kind is not MCPFaultKind.TOOL_LIST_STALE_CACHE:
        raise ValueError("MCP stale-cache bridge requires TOOL_LIST_STALE_CACHE")
    _require_fault_payload(fault, ttl_ms=ttl_ms)
    if receipt.fault_identity != fault.identity:
        raise ValueError("stale-cache protocol receipt identity does not match controlled fault")
    if receipt.tool_name != fault.tool_name:
        raise ValueError("stale-cache protocol receipt tool does not match controlled fault")
    if not hmac.compare_digest(receipt.payload_sha256, fault.payload_sha256):
        raise ValueError("stale-cache protocol receipt payload does not match controlled fault")


def _require_stale_cache_receipt_shape(receipt: MCPFaultReceipt) -> None:
    if receipt.kind is not MCPFaultKind.TOOL_LIST_STALE_CACHE:
        raise ValueError("MCP stale-cache bridge requires TOOL_LIST_STALE_CACHE protocol receipt")
    if receipt.protocol_version != _PROTOCOL_VERSION:
        raise ValueError(f"MCP stale-cache bridge requires protocol version {_PROTOCOL_VERSION}")
    if receipt.injection_point != _protocol_point(receipt.tool_name):
        raise ValueError("MCP stale-cache receipt uses an unexpected protocol boundary")


def _require_fault_payload(fault: MCPFaultSpec, *, ttl_ms: int) -> None:
    payload = fault.payload
    if not isinstance(payload, dict):
        raise ValueError("MCP stale-cache fault payload must be an object")
    if payload.get("ttl_ms") != ttl_ms:
        raise ValueError("MCP stale-cache TTL does not match controlled fault")


def _protocol_point(tool_name: str) -> str:
    return (
        f"mcp:{_PROTOCOL_VERSION}:tools/list:cache-use-stale-after-remove:"
        f"{tool_name}:refresh-proves-absent"
    )


def _protocol_observation(*, tool_name: str, ttl_ms: int) -> str:
    return _canonical_json(
        {
            "cached_tool_names": (tool_name,),
            "initial_tool_names": (tool_name,),
            "refreshed_tool_names": (),
            "ttl_ms": ttl_ms,
        }
    )


def _require_protocol_observation(
    receipt: MCPFaultReceipt,
    *,
    tool_name: str,
    ttl_ms: int,
) -> None:
    expected = _protocol_observation(tool_name=tool_name, ttl_ms=ttl_ms)
    if not hmac.compare_digest(receipt.observation_sha256, _sha256_text(expected)):
        raise ValueError("stale-cache protocol receipt does not match bound discovery relation")


def _require_protocol_chronology(ordinals: tuple[int, int, int, int, int, int]) -> None:
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in ordinals
    ):
        raise ValueError("MCP stale-cache protocol ordinals must be non-negative integers")
    if not all(left < right for left, right in pairwise(ordinals)):
        raise ValueError(
            "MCP stale-cache protocol chronology must be initial-list < removal < cached-list < "
            "stale-call < cache-invalidation < refreshed-list"
        )


def _canonical_tool_names(value: Sequence[str]) -> tuple[str, ...]:
    names = tuple(value)
    if any(not isinstance(name, str) for name in names):
        raise ValueError("model-visible controlled tool set must contain only strings")
    for name in names:
        _validate_identity_text(name, label="model-visible tool name")
    if len(set(names)) != len(names):
        raise ValueError("model-visible controlled tool set must not contain duplicates")
    return tuple(sorted(names))


def _canonical_arguments(value: Mapping[str, object] | None) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("MCP stale-cache arguments must be a mapping or None")
    result = dict(value)
    if any(not isinstance(key, str) for key in result):
        raise ValueError("MCP stale-cache argument keys must be strings")
    _canonical_json_bytes(result)
    return result


def _extract_single_text_output(value: object) -> str:
    if not isinstance(value, Mapping):
        raise ValueError("agent MCP stale-tool rejection must be one model-visible text output object")
    if set(value) != {"type", "text"}:
        raise ValueError("agent MCP stale-tool rejection must contain exactly 'type' and 'text'")
    text = value.get("text")
    if value.get("type") != "text" or not isinstance(text, str):
        raise ValueError("agent MCP stale-tool rejection must be one text output object")
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
