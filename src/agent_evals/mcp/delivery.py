"""Fail-closed semantic verification for MCP-to-agent protocol delivery evidence."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any, TypeAlias

from pydantic import ValidationError

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.mcp.agent_bridge import MCPAgentToolResultReceipt
from agent_evals.mcp.agent_error_bridge import MCPAgentToolErrorRecoveryReceipt
from agent_evals.mcp.agent_identity_bridge import MCPAgentToolIdentityDriftReceipt
from agent_evals.mcp.agent_metadata_bridge import MCPAgentToolMetadataReceipt
from agent_evals.mcp.agent_schema_bridge import MCPAgentToolSchemaDriftReceipt
from agent_evals.mcp.agent_stale_cache_bridge import MCPAgentToolStaleCacheReceipt

_TOOL_RESULT_SOURCE = "bridge:mcp-agent:tool-result"
_TOOL_ERROR_RECOVERY_SOURCE = "bridge:mcp-agent:tool-error-recovery"
_TOOL_SCHEMA_DRIFT_SOURCE = "bridge:mcp-agent:tool-schema-drift"
_TOOL_IDENTITY_DRIFT_SOURCE = "bridge:mcp-agent:tool-identity-drift"
_TOOL_STALE_CACHE_SOURCE = "bridge:mcp-agent:tool-stale-cache"
_TOOL_METADATA_SOURCE = "bridge:mcp-agent:tool-metadata"
_METADATA_BEHAVIOR_KINDS = frozenset(
    {
        EvidenceKind.TOOL_REQUEST,
        EvidenceKind.TOOL_RESULT,
        EvidenceKind.HANDOFF,
        EvidenceKind.APPROVAL_REQUEST,
        EvidenceKind.APPROVAL,
        EvidenceKind.APPROVAL_DECISION,
        EvidenceKind.GUARDRAIL,
        EvidenceKind.STATE,
        EvidenceKind.OUTPUT,
        EvidenceKind.POLICY_VIOLATION,
        EvidenceKind.EVALUATION_ERROR,
        EvidenceKind.RUNTIME_ERROR,
    }
)

ProtocolDeliveryReceipt: TypeAlias = (
    MCPAgentToolResultReceipt
    | MCPAgentToolErrorRecoveryReceipt
    | MCPAgentToolSchemaDriftReceipt
    | MCPAgentToolIdentityDriftReceipt
    | MCPAgentToolStaleCacheReceipt
    | MCPAgentToolMetadataReceipt
)


class ProtocolDeliveryError(ValueError):
    """Recorded protocol-delivery evidence is unsupported or semantically invalid."""


def verify_protocol_delivery(evidence: TrialEvidence) -> tuple[ProtocolDeliveryReceipt, ...]:
    """Revalidate every known protocol-delivery receipt and its normalized evidence relation."""
    receipts: list[ProtocolDeliveryReceipt] = []
    for event in evidence.events:
        if event.kind is not EvidenceKind.PROTOCOL_DELIVERY:
            continue

        receipt_type: (
            type[MCPAgentToolResultReceipt]
            | type[MCPAgentToolErrorRecoveryReceipt]
            | type[MCPAgentToolSchemaDriftReceipt]
            | type[MCPAgentToolIdentityDriftReceipt]
            | type[MCPAgentToolStaleCacheReceipt]
            | type[MCPAgentToolMetadataReceipt]
        )
        if event.source == _TOOL_RESULT_SOURCE:
            receipt_type = MCPAgentToolResultReceipt
        elif event.source == _TOOL_ERROR_RECOVERY_SOURCE:
            receipt_type = MCPAgentToolErrorRecoveryReceipt
        elif event.source == _TOOL_SCHEMA_DRIFT_SOURCE:
            receipt_type = MCPAgentToolSchemaDriftReceipt
        elif event.source == _TOOL_IDENTITY_DRIFT_SOURCE:
            receipt_type = MCPAgentToolIdentityDriftReceipt
        elif event.source == _TOOL_STALE_CACHE_SOURCE:
            receipt_type = MCPAgentToolStaleCacheReceipt
        elif event.source == _TOOL_METADATA_SOURCE:
            receipt_type = MCPAgentToolMetadataReceipt
        else:
            raise ProtocolDeliveryError(
                f"unsupported protocol delivery evidence source: {event.source}"
            )

        try:
            receipt = receipt_type.model_validate(event.payload)
        except ValidationError as exc:
            raise ProtocolDeliveryError(
                "protocol delivery receipt is malformed or internally inconsistent"
            ) from exc

        if receipt.scenario_identity != evidence.scenario_identity:
            raise ProtocolDeliveryError(
                "protocol delivery receipt scenario identity does not match trial evidence"
            )

        if event.source == _TOOL_METADATA_SOURCE:
            _verify_metadata_delivery_chronology(evidence, delivery_sequence=event.sequence)
        elif event.source == _TOOL_RESULT_SOURCE:
            if not isinstance(receipt, MCPAgentToolResultReceipt):
                raise ProtocolDeliveryError("tool-result delivery parsed as the wrong receipt type")
            _verify_tool_result_delivery(
                evidence,
                receipt=receipt,
                delivery_sequence=event.sequence,
            )
        elif event.source == _TOOL_ERROR_RECOVERY_SOURCE:
            if not isinstance(receipt, MCPAgentToolErrorRecoveryReceipt):
                raise ProtocolDeliveryError("ToolError delivery parsed as the wrong receipt type")
            _verify_tool_error_recovery_delivery(
                evidence,
                receipt=receipt,
                delivery_sequence=event.sequence,
            )
        elif event.source == _TOOL_SCHEMA_DRIFT_SOURCE:
            if not isinstance(receipt, MCPAgentToolSchemaDriftReceipt):
                raise ProtocolDeliveryError("schema-drift delivery parsed as the wrong receipt type")
            _verify_schema_drift_delivery(
                evidence,
                receipt=receipt,
                delivery_sequence=event.sequence,
            )
        elif event.source == _TOOL_IDENTITY_DRIFT_SOURCE:
            if not isinstance(receipt, MCPAgentToolIdentityDriftReceipt):
                raise ProtocolDeliveryError("identity-drift delivery parsed as the wrong receipt type")
            _verify_identity_drift_delivery(
                evidence,
                receipt=receipt,
                delivery_sequence=event.sequence,
            )
        elif event.source == _TOOL_STALE_CACHE_SOURCE:
            if not isinstance(receipt, MCPAgentToolStaleCacheReceipt):
                raise ProtocolDeliveryError("stale-cache delivery parsed as the wrong receipt type")
            _verify_stale_cache_delivery_chronology(
                evidence,
                receipt=receipt,
                delivery_sequence=event.sequence,
            )
        receipts.append(receipt)

    return tuple(receipts)


def _verify_metadata_delivery_chronology(
    evidence: TrialEvidence,
    *,
    delivery_sequence: int,
) -> None:
    for event in evidence.events[:delivery_sequence]:
        if event.kind in _METADATA_BEHAVIOR_KINDS:
            raise ProtocolDeliveryError(
                "MCP tool-metadata delivery appears after normalized behavioral evidence"
            )


def _verify_tool_result_delivery(
    evidence: TrialEvidence,
    *,
    receipt: MCPAgentToolResultReceipt,
    delivery_sequence: int,
) -> None:
    requests = _requests_for_tools(evidence, {receipt.agent_tool_name})
    if len(requests) != 1:
        raise ProtocolDeliveryError(
            "MCP tool-result delivery requires exactly one normalized target request"
        )
    request = requests[0]
    _require_call_id(request, receipt.agent_call_id, phase="tool-result request")
    result = _unique_result(evidence, receipt.agent_call_id, phase="tool-result")
    if _sha256_text(_single_text_output(result.payload.get("output"))) != receipt.agent_observation_sha256:
        raise ProtocolDeliveryError(
            "MCP tool-result normalized output does not match the receipt-bound observation"
        )
    if not (request.sequence < delivery_sequence < result.sequence):
        raise ProtocolDeliveryError(
            "MCP tool-result delivery must occur between its normalized request and result"
        )


def _verify_tool_error_recovery_delivery(
    evidence: TrialEvidence,
    *,
    receipt: MCPAgentToolErrorRecoveryReceipt,
    delivery_sequence: int,
) -> None:
    requests = _requests_for_tools(evidence, {receipt.agent_tool_name})
    if len(requests) != 2:
        raise ProtocolDeliveryError(
            "MCP ToolError recovery requires exactly two normalized target requests"
        )
    error_request, retry_request = requests
    _require_call_id(error_request, receipt.error_call_id, phase="ToolError request")
    _require_call_id(retry_request, receipt.retry_call_id, phase="ToolError retry")
    _require_arguments_digest(
        error_request,
        receipt.error_arguments_sha256,
        phase="ToolError request",
    )
    _require_arguments_digest(
        retry_request,
        receipt.retry_arguments_sha256,
        phase="ToolError retry",
    )
    error_result = _unique_result(evidence, receipt.error_call_id, phase="ToolError")
    retry_result = _unique_result(evidence, receipt.retry_call_id, phase="ToolError recovery")
    _require_output_digest(
        error_result,
        receipt.agent_error_observation_sha256,
        phase="ToolError rejection",
    )
    _require_output_digest(
        retry_result,
        receipt.agent_recovery_observation_sha256,
        phase="ToolError recovery",
    )
    if not (
        error_request.sequence
        < error_result.sequence
        < retry_request.sequence
        < retry_result.sequence
        < delivery_sequence
    ):
        raise ProtocolDeliveryError(
            "MCP ToolError recovery evidence does not prove request-result-retry-result-delivery causality"
        )


def _verify_schema_drift_delivery(
    evidence: TrialEvidence,
    *,
    receipt: MCPAgentToolSchemaDriftReceipt,
    delivery_sequence: int,
) -> None:
    requests = _requests_for_tools(evidence, {receipt.agent_tool_name})
    if len(requests) != 2:
        raise ProtocolDeliveryError(
            "MCP schema-drift delivery requires exactly two normalized target requests"
        )
    stale_request, recovery_request = requests
    _require_call_id(stale_request, receipt.stale_call_id, phase="schema-drift stale request")
    _require_call_id(
        recovery_request,
        receipt.recovery_call_id,
        phase="schema-drift recovery request",
    )
    _require_arguments_digest(
        stale_request,
        receipt.stale_arguments_sha256,
        phase="schema-drift stale request",
    )
    _require_arguments_digest(
        recovery_request,
        receipt.recovery_arguments_sha256,
        phase="schema-drift recovery request",
    )
    stale_result = _unique_result(evidence, receipt.stale_call_id, phase="schema-drift stale call")
    recovery_result = _unique_result(
        evidence,
        receipt.recovery_call_id,
        phase="schema-drift recovery",
    )
    _require_output_digest(
        stale_result,
        receipt.agent_error_observation_sha256,
        phase="schema-drift rejection",
    )
    _require_output_digest(
        recovery_result,
        receipt.agent_recovery_observation_sha256,
        phase="schema-drift recovery",
    )
    if not (
        stale_request.sequence
        < stale_result.sequence
        < recovery_request.sequence
        < recovery_result.sequence
        < delivery_sequence
    ):
        raise ProtocolDeliveryError(
            "MCP schema-drift normalized evidence does not prove stale-result-recovery-result-delivery causality"
        )


def _verify_identity_drift_delivery(
    evidence: TrialEvidence,
    *,
    receipt: MCPAgentToolIdentityDriftReceipt,
    delivery_sequence: int,
) -> None:
    requests = _requests_for_tools(
        evidence,
        {receipt.original_tool_name, receipt.replacement_tool_name},
    )
    if len(requests) != 2:
        raise ProtocolDeliveryError(
            "MCP identity-drift delivery requires exactly two normalized controlled requests"
        )
    stale_request, recovery_request = requests
    if stale_request.payload.get("tool") != receipt.original_tool_name:
        raise ProtocolDeliveryError(
            "MCP identity-drift stale request does not use the receipt-bound original identity"
        )
    if recovery_request.payload.get("tool") != receipt.replacement_tool_name:
        raise ProtocolDeliveryError(
            "MCP identity-drift recovery request does not use the receipt-bound replacement identity"
        )
    _require_call_id(stale_request, receipt.stale_call_id, phase="identity-drift stale request")
    _require_call_id(
        recovery_request,
        receipt.recovery_call_id,
        phase="identity-drift recovery request",
    )
    _require_arguments_digest(
        stale_request,
        receipt.stale_arguments_sha256,
        phase="identity-drift stale request",
    )
    _require_arguments_digest(
        recovery_request,
        receipt.recovery_arguments_sha256,
        phase="identity-drift recovery request",
    )
    stale_result = _unique_result(evidence, receipt.stale_call_id, phase="identity-drift stale call")
    recovery_result = _unique_result(
        evidence,
        receipt.recovery_call_id,
        phase="identity-drift recovery",
    )
    _require_output_digest(
        stale_result,
        receipt.agent_error_observation_sha256,
        phase="identity-drift rejection",
    )
    _require_output_digest(
        recovery_result,
        receipt.agent_recovery_observation_sha256,
        phase="identity-drift recovery",
    )
    if not (
        stale_request.sequence
        < stale_result.sequence
        < recovery_request.sequence
        < recovery_result.sequence
        < delivery_sequence
    ):
        raise ProtocolDeliveryError(
            "MCP identity-drift normalized evidence does not prove stale-result-recovery-result-delivery causality"
        )


def _verify_stale_cache_delivery_chronology(
    evidence: TrialEvidence,
    *,
    receipt: MCPAgentToolStaleCacheReceipt,
    delivery_sequence: int,
) -> None:
    requests = _requests_for_tools(evidence, {receipt.tool_name})
    if len(requests) != 1:
        raise ProtocolDeliveryError(
            "MCP stale-cache delivery requires exactly one normalized controlled target request"
        )
    request = requests[0]
    _require_call_id(request, receipt.stale_call_id, phase="stale-cache request")
    if _strict_json_object(request.payload.get("arguments")) != {"query": "stale"}:
        raise ProtocolDeliveryError(
            "MCP stale-cache normalized request arguments do not match the bound v1 relation"
        )
    result = _unique_result(evidence, receipt.stale_call_id, phase="stale-cache stale call")
    _require_output_digest(
        result,
        receipt.agent_error_observation_sha256,
        phase="stale-cache rejection",
    )
    if not (request.sequence < result.sequence < delivery_sequence):
        raise ProtocolDeliveryError(
            "MCP stale-cache delivery must occur after its normalized stale request and result"
        )


def _requests_for_tools(
    evidence: TrialEvidence,
    tools: set[str],
) -> list[EvidenceEvent]:
    return [
        event
        for event in evidence.events
        if event.kind is EvidenceKind.TOOL_REQUEST and event.payload.get("tool") in tools
    ]


def _unique_result(
    evidence: TrialEvidence,
    call_id: str,
    *,
    phase: str,
) -> EvidenceEvent:
    matching = [
        event
        for event in evidence.events
        if event.kind is EvidenceKind.TOOL_RESULT and event.payload.get("call_id") == call_id
    ]
    if len(matching) != 1:
        raise ProtocolDeliveryError(
            f"MCP {phase} requires exactly one normalized result for call {call_id!r}"
        )
    return matching[0]


def _require_call_id(event: EvidenceEvent, expected: str, *, phase: str) -> None:
    if event.payload.get("call_id") != expected:
        raise ProtocolDeliveryError(
            f"MCP {phase} call identity does not match the delivery receipt"
        )


def _require_arguments_digest(
    event: EvidenceEvent,
    expected_digest: str,
    *,
    phase: str,
) -> None:
    actual_digest = _sha256_json(_strict_json_object(event.payload.get("arguments")))
    if actual_digest != expected_digest:
        raise ProtocolDeliveryError(
            f"MCP {phase} arguments do not match the delivery receipt"
        )


def _require_output_digest(
    event: EvidenceEvent,
    expected_digest: str,
    *,
    phase: str,
) -> None:
    actual_digest = _sha256_text(_single_text_output(event.payload.get("output")))
    if actual_digest != expected_digest:
        raise ProtocolDeliveryError(
            f"MCP {phase} output does not match the delivery receipt"
        )


def _strict_json_object(value: object) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        raise ProtocolDeliveryError("normalized MCP arguments are missing")

    def reject_constant(token: str) -> None:
        raise ValueError(f"non-finite JSON constant: {token}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = item
        return result

    try:
        parsed = json.loads(
            value,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
        _require_finite_json(parsed)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProtocolDeliveryError(
            "normalized MCP arguments are not strict finite JSON"
        ) from exc
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise ProtocolDeliveryError(
            "normalized MCP arguments are not a string-keyed object"
        )
    return parsed


def _require_finite_json(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("non-string JSON object key")
            _require_finite_json(item)
    elif isinstance(value, list):
        for item in value:
            _require_finite_json(item)


def _single_text_output(value: object) -> str:
    if not isinstance(value, Mapping) or set(value) != {"type", "text"}:
        raise ProtocolDeliveryError(
            "normalized MCP result is not one exact text output object"
        )
    text = value.get("text")
    if value.get("type") != "text" or not isinstance(text, str):
        raise ProtocolDeliveryError(
            "normalized MCP result is not one exact text output object"
        )
    return text


def _sha256_json(value: object) -> str:
    try:
        canonical = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolDeliveryError("normalized MCP value is not canonical finite JSON") from exc
    return hashlib.sha256(canonical).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
