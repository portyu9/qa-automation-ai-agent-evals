"""Fail-closed semantic verification for MCP-to-agent protocol delivery evidence."""

from __future__ import annotations

from typing import TypeAlias

from pydantic import ValidationError

from agent_evals.evidence.models import EvidenceKind, TrialEvidence
from agent_evals.mcp.agent_bridge import MCPAgentToolResultReceipt
from agent_evals.mcp.agent_error_bridge import MCPAgentToolErrorRecoveryReceipt

_TOOL_RESULT_SOURCE = "bridge:mcp-agent:tool-result"
_TOOL_ERROR_RECOVERY_SOURCE = "bridge:mcp-agent:tool-error-recovery"

ProtocolDeliveryReceipt: TypeAlias = MCPAgentToolResultReceipt | MCPAgentToolErrorRecoveryReceipt


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

        receipt_type: type[MCPAgentToolResultReceipt] | type[MCPAgentToolErrorRecoveryReceipt]
        if event.source == _TOOL_RESULT_SOURCE:
            receipt_type = MCPAgentToolResultReceipt
        elif event.source == _TOOL_ERROR_RECOVERY_SOURCE:
            receipt_type = MCPAgentToolErrorRecoveryReceipt
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
        receipts.append(receipt)

    return tuple(receipts)
