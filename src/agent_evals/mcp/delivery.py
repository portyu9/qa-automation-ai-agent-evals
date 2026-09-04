"""Fail-closed semantic verification for MCP-to-agent protocol delivery evidence."""

from __future__ import annotations

from typing import TypeAlias

from pydantic import ValidationError

from agent_evals.evidence.models import EvidenceKind, TrialEvidence
from agent_evals.mcp.agent_bridge import MCPAgentToolResultReceipt
from agent_evals.mcp.agent_error_bridge import MCPAgentToolErrorRecoveryReceipt
from agent_evals.mcp.agent_metadata_bridge import MCPAgentToolMetadataReceipt
from agent_evals.mcp.agent_schema_bridge import MCPAgentToolSchemaDriftReceipt

_TOOL_RESULT_SOURCE = "bridge:mcp-agent:tool-result"
_TOOL_ERROR_RECOVERY_SOURCE = "bridge:mcp-agent:tool-error-recovery"
_TOOL_SCHEMA_DRIFT_SOURCE = "bridge:mcp-agent:tool-schema-drift"
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
            | type[MCPAgentToolMetadataReceipt]
        )
        if event.source == _TOOL_RESULT_SOURCE:
            receipt_type = MCPAgentToolResultReceipt
        elif event.source == _TOOL_ERROR_RECOVERY_SOURCE:
            receipt_type = MCPAgentToolErrorRecoveryReceipt
        elif event.source == _TOOL_SCHEMA_DRIFT_SOURCE:
            receipt_type = MCPAgentToolSchemaDriftReceipt
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
