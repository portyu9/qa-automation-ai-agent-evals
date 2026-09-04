"""Integrity-bound evidence for exact native approval interruption decisions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agent_evals.contracts.models import ApprovalDecision, EvaluationScenario
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence

_APPROVAL_INTENT_DOMAIN = b"agent-evals/approval-intent/v1\0"
_APPROVAL_INTENT_SCHEMA = "agent-evals/approval-intent/v1"


class ApprovalIntentError(ValueError):
    """Raised when stronger approval intent evidence cannot be established exactly."""


class ApprovalIntentReceipt(BaseModel):
    """Bind one evaluator decision to one exact observed approval interruption.

    Raw arguments are deliberately excluded. The receipt stores a digest of canonical finite JSON
    arguments, the normalized resource identity, and the handoff epoch observed before the request.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema: str = Field(default=_APPROVAL_INTENT_SCHEMA, pattern=r"^agent-evals/approval-intent/v1$")
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: ApprovalDecision
    agent: str = Field(min_length=1, max_length=256)
    tool: str = Field(min_length=1, max_length=256)
    call_id: str = Field(min_length=1, max_length=512)
    arguments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    resource: str | None = None
    authority_epoch: int = Field(ge=0, strict=True)
    approval_request_sequence: int = Field(ge=0, strict=True)
    root_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_identities_and_root(self) -> ApprovalIntentReceipt:
        for value in (self.agent, self.tool, self.call_id):
            if value != value.strip():
                raise ValueError("approval receipt identities must not contain surrounding whitespace")
        if self.resource is not None and (
            not self.resource or self.resource != self.resource.strip()
        ):
            raise ValueError("approval receipt resource must be a stable non-empty identity")
        if self.root_sha256 != self.expected_root:
            raise ValueError("approval intent receipt root mismatch")
        return self

    @classmethod
    def create(
        cls,
        *,
        scenario: EvaluationScenario,
        agent: str,
        tool: str,
        call_id: str,
        arguments: str,
        resource: str | None,
        authority_epoch: int,
        approval_request_sequence: int,
    ) -> ApprovalIntentReceipt:
        spec = scenario.approval_intent
        if spec is None:
            raise ApprovalIntentError("scenario does not declare an approval intent")
        arguments_sha256 = canonical_arguments_sha256(arguments)
        material = {
            "schema": _APPROVAL_INTENT_SCHEMA,
            "scenario_identity": scenario.identity,
            "decision": spec.decision.value,
            "agent": agent,
            "tool": tool,
            "call_id": call_id,
            "arguments_sha256": arguments_sha256,
            "resource": resource,
            "authority_epoch": authority_epoch,
            "approval_request_sequence": approval_request_sequence,
        }
        return cls(**material, root_sha256=_root(material))

    @property
    def expected_root(self) -> str:
        return _root(self.model_dump(mode="json", exclude={"root_sha256"}))

    def to_event(self, *, sequence: int, source: str) -> EvidenceEvent:
        return EvidenceEvent(
            sequence=sequence,
            kind=EvidenceKind.APPROVAL_DECISION,
            source=source,
            payload={"receipt": self.model_dump(mode="json")},
        )


def canonical_arguments_sha256(arguments: str) -> str:
    """Hash one finite JSON object by semantic content rather than source formatting."""
    if not isinstance(arguments, str) or not arguments:
        raise ApprovalIntentError("approval intent requires non-empty string arguments")
    try:
        parsed = json.loads(arguments, parse_constant=_reject_json_constant)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ApprovalIntentError("approval intent arguments must be finite JSON") from exc
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise ApprovalIntentError("approval intent arguments must be a JSON object with string keys")
    canonical = json.dumps(
        parsed,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def parse_approval_intent_event(event: EvidenceEvent) -> ApprovalIntentReceipt:
    if event.kind is not EvidenceKind.APPROVAL_DECISION:
        raise ApprovalIntentError("event is not approval-decision evidence")
    if set(event.payload) != {"receipt"}:
        raise ApprovalIntentError("approval-decision event must contain exactly one receipt")
    try:
        return ApprovalIntentReceipt.model_validate(event.payload["receipt"])
    except (ValidationError, TypeError, ValueError) as exc:
        raise ApprovalIntentError("approval-decision receipt is malformed") from exc


def verify_approval_intent(scenario: EvaluationScenario, evidence: TrialEvidence) -> None:
    """Reverify exact request → decision → resumed invocation intent before grading.

    Absence of a decision is BLOCKED only when the target was never exercised. If the protected
    target actually executed with no stronger decision evidence, the verifier deliberately leaves
    that resolved bypass for ``PolicyOracle`` to grade as a critical subject failure.
    """

    decision_events = [
        event for event in evidence.events if event.kind is EvidenceKind.APPROVAL_DECISION
    ]
    spec = scenario.approval_intent

    if spec is None:
        if decision_events:
            raise ApprovalIntentError(
                "approval-decision evidence is present but the scenario has no approval intent"
            )
        return

    if evidence.scenario_identity != scenario.identity:
        raise ApprovalIntentError("trial evidence does not match the approval-intent scenario")

    if not decision_events:
        exercised = any(
            event.kind is EvidenceKind.TOOL_REQUEST
            and event.payload.get("agent") == spec.agent
            and event.payload.get("tool") == spec.tool
            for event in evidence.events
        )
        if exercised:
            return
        raise ApprovalIntentError("scenario approval target produced no bound decision evidence")

    if len(decision_events) != 1:
        raise ApprovalIntentError("approval intent requires exactly one decision event")

    decision_event = decision_events[0]
    receipt = parse_approval_intent_event(decision_event)
    if receipt.scenario_identity != scenario.identity:
        raise ApprovalIntentError("approval receipt scenario identity mismatch")
    if receipt.decision is not spec.decision:
        raise ApprovalIntentError("approval receipt decision does not match scenario intent")
    if receipt.agent != spec.agent or receipt.tool != spec.tool:
        raise ApprovalIntentError("approval receipt target does not match scenario intent")

    if receipt.approval_request_sequence >= decision_event.sequence:
        raise ApprovalIntentError("approval decision must follow its bound approval request")
    if receipt.approval_request_sequence >= len(evidence.events):
        raise ApprovalIntentError("approval receipt request sequence is outside trial evidence")

    request_event = evidence.events[receipt.approval_request_sequence]
    if request_event.kind is not EvidenceKind.APPROVAL_REQUEST:
        raise ApprovalIntentError("approval receipt does not reference an approval-request event")
    _verify_event_intent(
        request_event,
        receipt=receipt,
        expected_epoch=_authority_epoch_before(evidence, request_event.sequence),
        phase="approval request",
    )

    resumed_requests = [
        event
        for event in evidence.events[decision_event.sequence + 1 :]
        if event.kind is EvidenceKind.TOOL_REQUEST
        and event.payload.get("call_id") == receipt.call_id
    ]
    if len(resumed_requests) > 1:
        raise ApprovalIntentError("approval decision maps to multiple resumed tool requests")

    if receipt.decision is ApprovalDecision.APPROVE:
        if not resumed_requests:
            raise ApprovalIntentError("approved interruption produced no matching resumed tool request")
        resumed = resumed_requests[0]
        _verify_event_intent(
            resumed,
            receipt=receipt,
            expected_epoch=_authority_epoch_before(evidence, resumed.sequence),
            phase="resumed tool request",
        )
        results = [
            event
            for event in evidence.events[resumed.sequence + 1 :]
            if event.kind is EvidenceKind.TOOL_RESULT
            and event.payload.get("call_id") == receipt.call_id
        ]
        if len(results) != 1:
            raise ApprovalIntentError(
                "approved interruption must produce exactly one matching resumed tool result"
            )
    elif resumed_requests:
        # An exact rejected invocation reaching executable TOOL_REQUEST evidence is a resolved
        # subject violation. Its intent must still match the rejected request so PolicyOracle can
        # grade the bypass rather than having evaluator uncertainty mask it.
        _verify_event_intent(
            resumed_requests[0],
            receipt=receipt,
            expected_epoch=_authority_epoch_before(evidence, resumed_requests[0].sequence),
            phase="rejected resumed tool request",
        )


def _verify_event_intent(
    event: EvidenceEvent,
    *,
    receipt: ApprovalIntentReceipt,
    expected_epoch: int,
    phase: str,
) -> None:
    if event.payload.get("agent") != receipt.agent:
        raise ApprovalIntentError(f"{phase} agent identity does not match approval receipt")
    if event.payload.get("tool") != receipt.tool:
        raise ApprovalIntentError(f"{phase} tool identity does not match approval receipt")
    if event.payload.get("call_id") != receipt.call_id:
        raise ApprovalIntentError(f"{phase} call identity does not match approval receipt")

    arguments = event.payload.get("arguments")
    if not isinstance(arguments, str):
        raise ApprovalIntentError(f"{phase} lacks canonicalizable string arguments")
    if canonical_arguments_sha256(arguments) != receipt.arguments_sha256:
        raise ApprovalIntentError(f"{phase} arguments do not match approved intent")

    resource = event.payload.get("resource")
    if resource is not None and not isinstance(resource, str):
        raise ApprovalIntentError(f"{phase} resource identity is malformed")
    if resource != receipt.resource:
        raise ApprovalIntentError(f"{phase} resource does not match approved intent")
    if expected_epoch != receipt.authority_epoch:
        raise ApprovalIntentError(f"{phase} occurred in a different authority epoch")


def _authority_epoch_before(evidence: TrialEvidence, sequence: int) -> int:
    return sum(
        event.kind is EvidenceKind.HANDOFF
        for event in evidence.events[:sequence]
    )


def _root(material: dict[str, Any]) -> str:
    canonical = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(_APPROVAL_INTENT_DOMAIN + canonical).hexdigest()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")
