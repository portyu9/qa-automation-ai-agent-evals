"""Typed, versioned projections of historical EvidenceEvent payloads.

Projection never rewrites TrialEvidence/v2. It validates a detached event into a new v1 typed view
for consumers that need schema discrimination. Receipt-bearing kinds stay subordinate to their
existing domain-specific verifiers; this module only requires the common schema/root shape.
"""

from __future__ import annotations

from typing import Any, Literal, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field

from agent_evals.evidence.models import EvidenceEvent, EvidenceKind

_PAYLOAD_SCHEMA: Literal["agent-evals/event-payload/v1"] = "agent-evals/event-payload/v1"


class _AllowExtraPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="allow")


class EvaluationErrorPayloadV1(_AllowExtraPayload):
    code: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=4000)
    deadline_seconds: float | None = Field(
        default=None,
        gt=0.0,
        allow_inf_nan=False,
        strict=True,
    )


class RuntimeErrorPayloadV1(_AllowExtraPayload):
    exception_type: str = Field(min_length=1, max_length=512)
    detail_retained: bool = Field(strict=True)


class PolicyViolationPayloadV1(_AllowExtraPayload):
    reason: str = Field(min_length=1, max_length=4000)


class ToolRequestPayloadV1(_AllowExtraPayload):
    tool: str | None = Field(default=None, min_length=1, max_length=512)
    call_id: str | None = Field(default=None, min_length=1, max_length=1024)
    arguments: Any = None


class ToolResultPayloadV1(_AllowExtraPayload):
    call_id: str | None = Field(default=None, min_length=1, max_length=1024)
    output: Any = None
    approval_rejected: bool | None = Field(default=None, strict=True)


class HandoffPayloadV1(_AllowExtraPayload):
    source_agent: str | None = Field(default=None, min_length=1, max_length=512)
    target_agent: str | None = Field(default=None, min_length=1, max_length=512)


class ApprovalPayloadV1(_AllowExtraPayload):
    tool: str | None = Field(default=None, min_length=1, max_length=512)
    call_id: str | None = Field(default=None, min_length=1, max_length=1024)
    scope: str | None = Field(default=None, min_length=1, max_length=64)
    agent: str | None = Field(default=None, min_length=1, max_length=512)


class GuardrailPayloadV1(_AllowExtraPayload):
    triggered: bool | None = Field(default=None, strict=True)
    tripwire_triggered: bool | None = Field(default=None, strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=512)
    boundary: str | None = Field(default=None, min_length=1, max_length=128)


class OutputPayloadV1(_AllowExtraPayload):
    output: Any = None


class GenericObjectPayloadV1(_AllowExtraPayload):
    pass


class ReceiptPayloadV1(_AllowExtraPayload):
    schema_version: str = Field(pattern=r"^agent-evals/[a-z0-9._/-]+/v[0-9]+$")
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvaluationErrorEventV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["agent-evals/event-payload/v1"] = _PAYLOAD_SCHEMA
    kind: Literal[EvidenceKind.EVALUATION_ERROR]
    source: str
    critical: bool
    payload: EvaluationErrorPayloadV1


class RuntimeErrorEventV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["agent-evals/event-payload/v1"] = _PAYLOAD_SCHEMA
    kind: Literal[EvidenceKind.RUNTIME_ERROR]
    source: str
    critical: bool
    payload: RuntimeErrorPayloadV1


class PolicyViolationEventV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["agent-evals/event-payload/v1"] = _PAYLOAD_SCHEMA
    kind: Literal[EvidenceKind.POLICY_VIOLATION]
    source: str
    critical: bool
    payload: PolicyViolationPayloadV1


class ToolRequestEventV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["agent-evals/event-payload/v1"] = _PAYLOAD_SCHEMA
    kind: Literal[EvidenceKind.TOOL_REQUEST]
    source: str
    critical: bool
    payload: ToolRequestPayloadV1


class ToolResultEventV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["agent-evals/event-payload/v1"] = _PAYLOAD_SCHEMA
    kind: Literal[EvidenceKind.TOOL_RESULT]
    source: str
    critical: bool
    payload: ToolResultPayloadV1


class HandoffEventV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["agent-evals/event-payload/v1"] = _PAYLOAD_SCHEMA
    kind: Literal[EvidenceKind.HANDOFF]
    source: str
    critical: bool
    payload: HandoffPayloadV1


class ApprovalRequestEventV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["agent-evals/event-payload/v1"] = _PAYLOAD_SCHEMA
    kind: Literal[EvidenceKind.APPROVAL_REQUEST]
    source: str
    critical: bool
    payload: ApprovalPayloadV1


class ApprovalEventV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["agent-evals/event-payload/v1"] = _PAYLOAD_SCHEMA
    kind: Literal[EvidenceKind.APPROVAL]
    source: str
    critical: bool
    payload: ApprovalPayloadV1


class ApprovalDecisionEventV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["agent-evals/event-payload/v1"] = _PAYLOAD_SCHEMA
    kind: Literal[EvidenceKind.APPROVAL_DECISION]
    source: str
    critical: bool
    payload: GenericObjectPayloadV1


class GuardrailEventV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["agent-evals/event-payload/v1"] = _PAYLOAD_SCHEMA
    kind: Literal[EvidenceKind.GUARDRAIL]
    source: str
    critical: bool
    payload: GuardrailPayloadV1


class StateEventV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["agent-evals/event-payload/v1"] = _PAYLOAD_SCHEMA
    kind: Literal[EvidenceKind.STATE]
    source: str
    critical: bool
    payload: GenericObjectPayloadV1


class OutputEventV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["agent-evals/event-payload/v1"] = _PAYLOAD_SCHEMA
    kind: Literal[EvidenceKind.OUTPUT]
    source: str
    critical: bool
    payload: OutputPayloadV1


class ReceiptEventV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal["agent-evals/event-payload/v1"] = _PAYLOAD_SCHEMA
    kind: Literal[
        EvidenceKind.ATTACK_DELIVERY,
        EvidenceKind.PROTOCOL_DELIVERY,
        EvidenceKind.RETRIEVAL_DELIVERY,
        EvidenceKind.SIDE_EFFECT_OBSERVATION,
        EvidenceKind.SEMANTIC_JUDGMENT,
    ]
    source: str
    critical: bool
    payload: ReceiptPayloadV1


TypedEvidenceEventV1: TypeAlias = (
    EvaluationErrorEventV1
    | RuntimeErrorEventV1
    | PolicyViolationEventV1
    | ToolRequestEventV1
    | ToolResultEventV1
    | HandoffEventV1
    | ApprovalRequestEventV1
    | ApprovalEventV1
    | ApprovalDecisionEventV1
    | GuardrailEventV1
    | StateEventV1
    | OutputEventV1
    | ReceiptEventV1
)


_EVENT_MODELS: dict[EvidenceKind, type[BaseModel]] = {
    EvidenceKind.EVALUATION_ERROR: EvaluationErrorEventV1,
    EvidenceKind.RUNTIME_ERROR: RuntimeErrorEventV1,
    EvidenceKind.POLICY_VIOLATION: PolicyViolationEventV1,
    EvidenceKind.TOOL_REQUEST: ToolRequestEventV1,
    EvidenceKind.TOOL_RESULT: ToolResultEventV1,
    EvidenceKind.HANDOFF: HandoffEventV1,
    EvidenceKind.APPROVAL_REQUEST: ApprovalRequestEventV1,
    EvidenceKind.APPROVAL: ApprovalEventV1,
    EvidenceKind.APPROVAL_DECISION: ApprovalDecisionEventV1,
    EvidenceKind.GUARDRAIL: GuardrailEventV1,
    EvidenceKind.STATE: StateEventV1,
    EvidenceKind.OUTPUT: OutputEventV1,
    EvidenceKind.ATTACK_DELIVERY: ReceiptEventV1,
    EvidenceKind.PROTOCOL_DELIVERY: ReceiptEventV1,
    EvidenceKind.RETRIEVAL_DELIVERY: ReceiptEventV1,
    EvidenceKind.SIDE_EFFECT_OBSERVATION: ReceiptEventV1,
    EvidenceKind.SEMANTIC_JUDGMENT: ReceiptEventV1,
}


def project_typed_event(event: EvidenceEvent) -> TypedEvidenceEventV1:
    """Validate one historical event into the additive typed-payload v1 view."""

    if type(event) is not EvidenceEvent:
        raise ValueError("typed event projection requires an exact EvidenceEvent")
    model = _EVENT_MODELS[event.kind]
    projected = model.model_validate(
        {
            "kind": event.kind,
            "source": event.source,
            "critical": event.critical,
            "payload": event.payload,
        }
    )
    return cast(TypedEvidenceEventV1, projected)
