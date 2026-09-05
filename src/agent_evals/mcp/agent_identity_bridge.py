"""Integrity-bound receipt for host-refreshed MCP tool-identity adaptation."""

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

_BRIDGE_SCHEMA: Literal["agent-evals/mcp-agent-tool-identity-drift-receipt/v2"] = (
    "agent-evals/mcp-agent-tool-identity-drift-receipt/v2"
)
_BRIDGE_DOMAIN = b"agent-evals/mcp-agent-tool-identity-drift-receipt/v2\0"
_PROTOCOL_VERSION = "2026-07-28"
_EVENT_SOURCE = "bridge:mcp-agent:tool-identity-drift"
_EXPECTED_STALE_ARGUMENTS = {"query": "stale"}
_EXPECTED_RECOVERY_ARGUMENTS = {"query": "fresh"}
_EXPECTED_RECOVERY_TEXT = "replacement:fresh"


class MCPAgentToolIdentityDriftReceipt(BaseModel):
    """Bind one live MCP rename to one exact OpenAI agent identity-adaptation relation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-agent-tool-identity-drift-receipt/v2"] = _BRIDGE_SCHEMA
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_receipt: MCPFaultReceipt
    original_tool_name: str = Field(min_length=1, max_length=128)
    replacement_tool_name: str = Field(min_length=1, max_length=128)
    stale_call_id: str = Field(min_length=1, max_length=256)
    recovery_call_id: str = Field(min_length=1, max_length=256)
    ttl_ms: StrictInt = Field(gt=0, le=86_400_000)
    stale_arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    recovery_arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stale_protocol_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    agent_error_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_recovery_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    protocol_recovery_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    agent_recovery_observation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    initial_model_tool_names_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    refreshed_model_tool_names_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    initial_list_ordinal: StrictInt = Field(ge=0)
    identity_swap_ordinal: StrictInt = Field(ge=0)
    cached_list_ordinal: StrictInt = Field(ge=0)
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
        original_tool_name: str,
        replacement_tool_name: str,
        stale_call_id: str,
        recovery_call_id: str,
        ttl_ms: int,
        stale_arguments: Mapping[str, object] | None,
        recovery_arguments: Mapping[str, object] | None,
        stale_protocol_text: str,
        agent_error_output: object,
        protocol_recovery_text: str,
        agent_recovery_output: object,
        initial_model_tool_names: Sequence[str],
        refreshed_model_tool_names: Sequence[str],
        initial_list_ordinal: int,
        identity_swap_ordinal: int,
        cached_list_ordinal: int,
        stale_call_ordinal: int,
        cache_invalidation_ordinal: int,
        refreshed_list_ordinal: int,
        recovery_call_ordinal: int,
    ) -> Self:
        """Create only after protocol, model-visible, and normalized agent relations close."""
        validated_protocol = _revalidate_protocol_receipt(protocol_receipt)
        _require_identity_drift_fault(
            fault=fault,
            receipt=validated_protocol,
            ttl_ms=ttl_ms,
            replacement_tool_name=replacement_tool_name,
        )
        _validate_identity_text(original_tool_name, label="original tool name")
        _validate_identity_text(replacement_tool_name, label="replacement tool name")
        _validate_identity_text(stale_call_id, label="stale call ID")
        _validate_identity_text(recovery_call_id, label="recovery call ID")
        if original_tool_name != fault.tool_name:
            raise ValueError("original tool name does not match controlled MCP identity-drift tool")
        if original_tool_name == replacement_tool_name:
            raise ValueError("MCP identity-drift replacement must differ from original tool name")
        if stale_call_id == recovery_call_id:
            raise ValueError("MCP identity-drift recovery requires distinct OpenAI call IDs")

        stale_arguments_sha256 = _sha256_json(_canonical_arguments(stale_arguments))
        recovery_arguments_sha256 = _sha256_json(_canonical_arguments(recovery_arguments))
        if not hmac.compare_digest(
            stale_arguments_sha256,
            _sha256_json(_EXPECTED_STALE_ARGUMENTS),
        ):
            raise ValueError("first MCP identity-drift call does not use bound stale arguments")
        if not hmac.compare_digest(
            recovery_arguments_sha256,
            _sha256_json(_EXPECTED_RECOVERY_ARGUMENTS),
        ):
            raise ValueError("MCP identity-drift recovery does not use bound replacement arguments")

        if not stale_protocol_text or "unknown tool" not in stale_protocol_text.lower():
            raise ValueError("stale MCP identity-drift call must expose an unknown-tool rejection")
        stale_protocol_sha256 = _sha256_text(stale_protocol_text)
        agent_error_text = _extract_single_text_output(agent_error_output, phase="stale-call error")
        agent_error_sha256 = _sha256_text(agent_error_text)
        if not hmac.compare_digest(stale_protocol_sha256, agent_error_sha256):
            raise ValueError("agent-observed identity rejection does not match MCP observation")

        if protocol_recovery_text != _EXPECTED_RECOVERY_TEXT:
            raise ValueError("MCP identity-drift recovery does not match bound replacement result")
        protocol_recovery_sha256 = _sha256_text(protocol_recovery_text)
        expected_recovery_sha256 = _sha256_text(_EXPECTED_RECOVERY_TEXT)
        agent_recovery_text = _extract_single_text_output(
            agent_recovery_output,
            phase="identity-drift recovery",
        )
        agent_recovery_sha256 = _sha256_text(agent_recovery_text)
        if not hmac.compare_digest(agent_recovery_sha256, expected_recovery_sha256):
            raise ValueError("agent-observed replacement result does not match controlled result")

        initial_names = _canonical_tool_names(initial_model_tool_names)
        refreshed_names = _canonical_tool_names(refreshed_model_tool_names)
        if initial_names != (original_tool_name,):
            raise ValueError(
                "initial model-visible controlled identity set must contain only old name"
            )
        if refreshed_names != (replacement_tool_name,):
            raise ValueError(
                "refreshed model-visible controlled identity set must contain only replacement name"
            )
        initial_model_tool_names_sha256 = _sha256_json(initial_names)
        refreshed_model_tool_names_sha256 = _sha256_json(refreshed_names)

        ordinals = (
            initial_list_ordinal,
            identity_swap_ordinal,
            cached_list_ordinal,
            stale_call_ordinal,
            cache_invalidation_ordinal,
            refreshed_list_ordinal,
            recovery_call_ordinal,
        )
        _require_protocol_chronology(ordinals)
        observation = _protocol_observation(
            ttl_ms=ttl_ms,
            original_tool_name=original_tool_name,
            replacement_tool_name=replacement_tool_name,
            stale_protocol_observation_sha256=stale_protocol_sha256,
            protocol_recovery_observation_sha256=protocol_recovery_sha256,
            ordinals=ordinals,
        )
        if not hmac.compare_digest(
            validated_protocol.observation_sha256,
            _sha256_text(observation),
        ):
            raise ValueError("MCP identity-drift protocol receipt does not match observed relation")

        unsigned = {
            "schema_version": _BRIDGE_SCHEMA,
            "scenario_identity": scenario_identity,
            "protocol_receipt": validated_protocol.model_dump(mode="json"),
            "original_tool_name": original_tool_name,
            "replacement_tool_name": replacement_tool_name,
            "stale_call_id": stale_call_id,
            "recovery_call_id": recovery_call_id,
            "ttl_ms": ttl_ms,
            "stale_arguments_sha256": stale_arguments_sha256,
            "recovery_arguments_sha256": recovery_arguments_sha256,
            "stale_protocol_observation_sha256": stale_protocol_sha256,
            "agent_error_observation_sha256": agent_error_sha256,
            "expected_recovery_sha256": expected_recovery_sha256,
            "protocol_recovery_observation_sha256": protocol_recovery_sha256,
            "agent_recovery_observation_sha256": agent_recovery_sha256,
            "initial_model_tool_names_sha256": initial_model_tool_names_sha256,
            "refreshed_model_tool_names_sha256": refreshed_model_tool_names_sha256,
            "initial_list_ordinal": initial_list_ordinal,
            "identity_swap_ordinal": identity_swap_ordinal,
            "cached_list_ordinal": cached_list_ordinal,
            "stale_call_ordinal": stale_call_ordinal,
            "cache_invalidation_ordinal": cache_invalidation_ordinal,
            "refreshed_list_ordinal": refreshed_list_ordinal,
            "recovery_call_ordinal": recovery_call_ordinal,
        }
        return cls.model_validate({**unsigned, "receipt_root": _receipt_root(unsigned)})

    @field_validator("protocol_receipt", mode="before")
    @classmethod
    def revalidate_protocol_receipt(cls, value: Any) -> MCPFaultReceipt:
        return _revalidate_protocol_receipt(value)

    @field_validator("original_tool_name", "replacement_tool_name")
    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        _validate_identity_text(value, label="tool name")
        return value

    @field_validator("stale_call_id", "recovery_call_id")
    @classmethod
    def validate_call_id(cls, value: str) -> str:
        _validate_identity_text(value, label="agent call ID")
        return value

    @model_validator(mode="after")
    def verify_bridge(self) -> Self:
        _require_identity_drift_receipt_shape(
            self.protocol_receipt,
            replacement_tool_name=self.replacement_tool_name,
        )
        if self.original_tool_name != self.protocol_receipt.tool_name:
            raise ValueError("original tool name does not match verified MCP protocol receipt")
        if self.original_tool_name == self.replacement_tool_name:
            raise ValueError("replacement tool identity must differ from original identity")
        if self.stale_call_id == self.recovery_call_id:
            raise ValueError("MCP identity-drift recovery requires distinct OpenAI call IDs")

        if not hmac.compare_digest(
            self.stale_arguments_sha256,
            _sha256_json(_EXPECTED_STALE_ARGUMENTS),
        ):
            raise ValueError("stale argument digest does not match bound old-name call")
        if not hmac.compare_digest(
            self.recovery_arguments_sha256,
            _sha256_json(_EXPECTED_RECOVERY_ARGUMENTS),
        ):
            raise ValueError("recovery argument digest does not match bound replacement call")
        if not hmac.compare_digest(
            self.stale_protocol_observation_sha256,
            self.agent_error_observation_sha256,
        ):
            raise ValueError("agent identity rejection digest does not match protocol rejection")
        if not hmac.compare_digest(
            self.expected_recovery_sha256,
            _sha256_text(_EXPECTED_RECOVERY_TEXT),
        ):
            raise ValueError(
                "expected recovery digest does not match controlled replacement result"
            )
        if not hmac.compare_digest(
            self.protocol_recovery_observation_sha256,
            self.expected_recovery_sha256,
        ):
            raise ValueError(
                "protocol recovery digest does not match controlled replacement result"
            )
        if not hmac.compare_digest(
            self.agent_recovery_observation_sha256,
            self.expected_recovery_sha256,
        ):
            raise ValueError("agent recovery digest does not match controlled replacement result")
        if not hmac.compare_digest(
            self.initial_model_tool_names_sha256,
            _sha256_json((self.original_tool_name,)),
        ):
            raise ValueError("initial model-visible identity digest does not match original tool")
        if not hmac.compare_digest(
            self.refreshed_model_tool_names_sha256,
            _sha256_json((self.replacement_tool_name,)),
        ):
            raise ValueError(
                "refreshed model-visible identity digest does not match replacement tool"
            )

        payload_material = {
            "replacement_tool_name": self.replacement_tool_name,
            "ttl_ms": self.ttl_ms,
        }
        if not hmac.compare_digest(
            self.protocol_receipt.payload_sha256,
            _sha256_json(payload_material),
        ):
            raise ValueError("identity-drift protocol payload digest does not match bound relation")

        ordinals = (
            self.initial_list_ordinal,
            self.identity_swap_ordinal,
            self.cached_list_ordinal,
            self.stale_call_ordinal,
            self.cache_invalidation_ordinal,
            self.refreshed_list_ordinal,
            self.recovery_call_ordinal,
        )
        _require_protocol_chronology(ordinals)
        expected_observation = _protocol_observation(
            ttl_ms=self.ttl_ms,
            original_tool_name=self.original_tool_name,
            replacement_tool_name=self.replacement_tool_name,
            stale_protocol_observation_sha256=self.stale_protocol_observation_sha256,
            protocol_recovery_observation_sha256=self.protocol_recovery_observation_sha256,
            ordinals=ordinals,
        )
        if not hmac.compare_digest(
            self.protocol_receipt.observation_sha256,
            _sha256_text(expected_observation),
        ):
            raise ValueError("identity-drift protocol receipt does not match root-bound relation")

        expected_root = _receipt_root(self.model_dump(mode="json", exclude={"receipt_root"}))
        if not hmac.compare_digest(expected_root, self.receipt_root):
            raise ValueError("MCP identity-drift receipt root does not match receipt content")
        return self

    def to_event(self, *, sequence: int) -> EvidenceEvent:
        return EvidenceEvent(
            sequence=sequence,
            kind=EvidenceKind.PROTOCOL_DELIVERY,
            source=_EVENT_SOURCE,
            payload=self.model_dump(mode="json"),
        )


def create_identity_drift_protocol_receipt(
    *,
    fault: MCPFaultSpec,
    ttl_ms: int,
    original_tool_name: str,
    replacement_tool_name: str,
    stale_protocol_text: str,
    protocol_recovery_text: str,
    initial_list_ordinal: int,
    identity_swap_ordinal: int,
    cached_list_ordinal: int,
    stale_call_ordinal: int,
    cache_invalidation_ordinal: int,
    refreshed_list_ordinal: int,
    recovery_call_ordinal: int,
) -> MCPFaultReceipt:
    """Create protocol evidence for one exact live stdio identity-drift relation."""
    if fault.kind is not MCPFaultKind.TOOL_IDENTITY_DRIFT:
        raise ValueError("agent identity-drift protocol receipt requires TOOL_IDENTITY_DRIFT")
    _require_fault_payload(
        fault,
        ttl_ms=ttl_ms,
        replacement_tool_name=replacement_tool_name,
    )
    if original_tool_name != fault.tool_name:
        raise ValueError("identity-drift original tool name does not match controlled fault")
    if not stale_protocol_text or "unknown tool" not in stale_protocol_text.lower():
        raise ValueError("identity-drift stale call must expose an unknown-tool rejection")
    if protocol_recovery_text != _EXPECTED_RECOVERY_TEXT:
        raise ValueError("identity-drift replacement call does not match controlled result")

    ordinals = (
        initial_list_ordinal,
        identity_swap_ordinal,
        cached_list_ordinal,
        stale_call_ordinal,
        cache_invalidation_ordinal,
        refreshed_list_ordinal,
        recovery_call_ordinal,
    )
    _require_protocol_chronology(ordinals)
    observation = _protocol_observation(
        ttl_ms=ttl_ms,
        original_tool_name=original_tool_name,
        replacement_tool_name=replacement_tool_name,
        stale_protocol_observation_sha256=_sha256_text(stale_protocol_text),
        protocol_recovery_observation_sha256=_sha256_text(protocol_recovery_text),
        ordinals=ordinals,
    )
    return MCPFaultReceipt.create(
        fault=fault,
        protocol_version=_PROTOCOL_VERSION,
        injection_point=_protocol_point(original_tool_name, replacement_tool_name),
        observed_text=observation,
    )


def _require_identity_drift_fault(
    *,
    fault: MCPFaultSpec,
    receipt: MCPFaultReceipt,
    ttl_ms: int,
    replacement_tool_name: str,
) -> None:
    _require_identity_drift_receipt_shape(
        receipt,
        replacement_tool_name=replacement_tool_name,
    )
    if fault.kind is not MCPFaultKind.TOOL_IDENTITY_DRIFT:
        raise ValueError("MCP identity-drift bridge requires TOOL_IDENTITY_DRIFT")
    _require_fault_payload(
        fault,
        ttl_ms=ttl_ms,
        replacement_tool_name=replacement_tool_name,
    )
    if receipt.fault_identity != fault.identity:
        raise ValueError("identity-drift protocol receipt identity does not match controlled fault")
    if receipt.tool_name != fault.tool_name:
        raise ValueError("identity-drift protocol receipt tool does not match controlled fault")
    if not hmac.compare_digest(receipt.payload_sha256, fault.payload_sha256):
        raise ValueError("identity-drift protocol receipt payload does not match controlled fault")


def _require_identity_drift_receipt_shape(
    receipt: MCPFaultReceipt,
    *,
    replacement_tool_name: str,
) -> None:
    if receipt.kind is not MCPFaultKind.TOOL_IDENTITY_DRIFT:
        raise ValueError("MCP identity-drift bridge requires TOOL_IDENTITY_DRIFT protocol receipt")
    if receipt.protocol_version != _PROTOCOL_VERSION:
        raise ValueError(f"MCP identity-drift bridge requires protocol version {_PROTOCOL_VERSION}")
    if receipt.injection_point != _protocol_point(receipt.tool_name, replacement_tool_name):
        raise ValueError("MCP identity-drift receipt uses an unexpected protocol boundary")


def _require_fault_payload(
    fault: MCPFaultSpec,
    *,
    ttl_ms: int,
    replacement_tool_name: str,
) -> None:
    payload = fault.payload
    if not isinstance(payload, dict):
        raise ValueError("MCP identity-drift fault payload must be an object")
    if payload.get("ttl_ms") != ttl_ms:
        raise ValueError("MCP identity-drift TTL does not match controlled fault")
    if payload.get("replacement_tool_name") != replacement_tool_name:
        raise ValueError("MCP identity-drift replacement name does not match controlled fault")


def _protocol_point(original_tool_name: str, replacement_tool_name: str) -> str:
    return (
        f"mcp:{_PROTOCOL_VERSION}:tools/list:agent-identity-drift:"
        f"{original_tool_name}->{replacement_tool_name}:"
        "swap-then-cached-old:call-rejects-old:host-refresh-new:call-succeeds-new"
    )


def _protocol_observation(
    *,
    ttl_ms: int,
    original_tool_name: str,
    replacement_tool_name: str,
    stale_protocol_observation_sha256: str,
    protocol_recovery_observation_sha256: str,
    ordinals: tuple[int, int, int, int, int, int, int],
) -> str:
    return _canonical_json(
        {
            "cache_invalidation_ordinal": ordinals[4],
            "cached_list_ordinal": ordinals[2],
            "initial_list_ordinal": ordinals[0],
            "identity_swap_ordinal": ordinals[1],
            "original_tool_name": original_tool_name,
            "protocol_recovery_observation_sha256": protocol_recovery_observation_sha256,
            "recovery_call_ordinal": ordinals[6],
            "refreshed_list_ordinal": ordinals[5],
            "replacement_tool_name": replacement_tool_name,
            "stale_call_ordinal": ordinals[3],
            "stale_protocol_observation_sha256": stale_protocol_observation_sha256,
            "ttl_ms": ttl_ms,
        }
    )


def _require_protocol_chronology(
    ordinals: tuple[int, int, int, int, int, int, int],
) -> None:
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in ordinals
    ):
        raise ValueError("MCP identity-drift protocol ordinals must be non-negative integers")
    if not all(left < right for left, right in pairwise(ordinals)):
        raise ValueError(
            "MCP identity-drift protocol chronology must be initial-list < swap < cached-list < "
            "stale-call < cache-invalidation < refreshed-list < recovery-call"
        )


def _canonical_tool_names(value: Sequence[str]) -> tuple[str, ...]:
    names = tuple(value)
    if any(not isinstance(name, str) for name in names):
        raise ValueError("model-visible tool identity set must contain only strings")
    for name in names:
        _validate_identity_text(name, label="model-visible tool name")
    if len(set(names)) != len(names):
        raise ValueError("model-visible controlled identity set must not contain duplicates")
    return tuple(sorted(names))


def _canonical_arguments(value: Mapping[str, object] | None) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("MCP identity-drift arguments must be a mapping or None")
    result = dict(value)
    if any(not isinstance(key, str) for key in result):
        raise ValueError("MCP identity-drift argument keys must be strings")
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
