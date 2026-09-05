"""Fail-closed semantic verification for MCP-to-agent protocol delivery evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, TypeAlias

from pydantic import ValidationError

from agent_evals.evidence.models import EvidenceKind, TrialEvidence
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
    """Revalidate every known protocol-delivery receipt inside one trial envelope.

    Live adapters already create validated receipt objects. This verifier is intentionally run again
    by the evaluator so historical replay cannot downgrade a typed cross-domain trust boundary into
    an opaque JSON event. Unknown protocol-delivery sources fail closed until an explicit verifier
    is added for that evidence domain.
    """
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
        elif event.source == _TOOL_STALE_CACHE_SOURCE:
            if not isinstance(receipt, MCPAgentToolStaleCacheReceipt):
                raise ProtocolDeliveryError(
                    "stale-cache delivery did not parse as its typed receipt"
                )
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
    """Require metadata exposure to close before normalized model/agent behavior.

    Leading ``ATTACK_DELIVERY`` evidence is allowed because user input, session memory, resources,
    and local tool-description injections can be installed before the first model request. A valid
    MCP metadata receipt proves that the target definition reached that first model boundary, so it
    cannot truthfully appear after tool, handoff, approval, guardrail, output, or error evidence.
    """
    for event in evidence.events[:delivery_sequence]:
        if event.kind in _METADATA_BEHAVIOR_KINDS:
            raise ProtocolDeliveryError(
                "MCP tool-metadata delivery appears after normalized behavioral evidence"
            )


def _verify_stale_cache_delivery_chronology(
    evidence: TrialEvidence,
    *,
    receipt: MCPAgentToolStaleCacheReceipt,
    delivery_sequence: int,
) -> None:
    """Bind stale-cache delivery to the exact normalized request/result pair on replay."""
    target_requests = [
        event
        for event in evidence.events
        if event.kind is EvidenceKind.TOOL_REQUEST
        and event.payload.get("tool") == receipt.tool_name
    ]
    if len(target_requests) != 1:
        raise ProtocolDeliveryError(
            "MCP stale-cache delivery requires exactly one normalized controlled target request"
        )
    request = target_requests[0]
    if request.payload.get("call_id") != receipt.stale_call_id:
        raise ProtocolDeliveryError(
            "MCP stale-cache normalized request call identity does not match delivery receipt"
        )
    if _strict_json_object(request.payload.get("arguments")) != {"query": "stale"}:
        raise ProtocolDeliveryError(
            "MCP stale-cache normalized request arguments do not match the bound v1 relation"
        )

    matching_results = [
        event
        for event in evidence.events
        if event.kind is EvidenceKind.TOOL_RESULT
        and event.payload.get("call_id") == receipt.stale_call_id
    ]
    if len(matching_results) != 1:
        raise ProtocolDeliveryError(
            "MCP stale-cache delivery requires exactly one normalized result for the stale call"
        )
    result = matching_results[0]
    result_text = _single_text_output(result.payload.get("output"))
    if _sha256_text(result_text) != receipt.agent_error_observation_sha256:
        raise ProtocolDeliveryError(
            "MCP stale-cache normalized rejection does not match the receipt-bound model rejection"
        )
    if not (request.sequence < result.sequence < delivery_sequence):
        raise ProtocolDeliveryError(
            "MCP stale-cache delivery must occur after its normalized stale request and result"
        )


def _strict_json_object(value: object) -> dict[str, Any]:
    if not isinstance(value, str) or not value:
        raise ProtocolDeliveryError("normalized MCP stale-cache arguments are missing")

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
    except (json.JSONDecodeError, ValueError) as exc:
        raise ProtocolDeliveryError(
            "normalized MCP stale-cache arguments are not strict finite JSON"
        ) from exc
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise ProtocolDeliveryError(
            "normalized MCP stale-cache arguments are not a string-keyed object"
        )
    return parsed


def _single_text_output(value: object) -> str:
    if not isinstance(value, Mapping) or set(value) != {"type", "text"}:
        raise ProtocolDeliveryError(
            "normalized MCP stale-cache result is not one exact text output object"
        )
    text = value.get("text")
    if value.get("type") != "text" or not isinstance(text, str):
        raise ProtocolDeliveryError(
            "normalized MCP stale-cache result is not one exact text output object"
        )
    return text


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
