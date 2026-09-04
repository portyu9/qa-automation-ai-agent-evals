"""OpenAI Agents SDK adapter for exact human-in-the-loop approval intent assurance."""

from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter
from typing import Any

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult
from agent_evals.adapters.openai_agents import _stringify_output
from agent_evals.adapters.openai_handoff_authority import OpenAIAgentsHandoffAuthorityAdapter
from agent_evals.contracts.models import ApprovalDecision, EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.approval_intent import ApprovalIntentError, ApprovalIntentReceipt
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind


class OpenAIAgentsHITLApprovalAdapter(OpenAIAgentsHandoffAuthorityAdapter):
    """Pause, decide, resume, and bind one exact native SDK approval interruption.

    The SDK owns interruption and ``RunState`` continuation mechanics. This adapter owns only the
    evaluator-side evidence relation: the scenario-bound decision is attached to one public SDK
    ``ToolApprovalItem`` and must match the same invocation intent after resume. Authorization and
    terminal correctness remain framework-owned by deterministic oracles.
    """

    @property
    def name(self) -> str:
        return "openai-agents-hitl-approval-intent"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, trial_id

        spec = scenario.approval_intent
        if spec is None:
            raise AdapterPreconditionError(
                code="approval_intent_missing",
                reason="HITL approval adapter requires a scenario-bound approval intent",
            )

        self._validate_root_agent(scenario)

        try:
            from agents import RunConfig, Runner
            from agents.items import ToolApprovalItem
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "install the 'openai' extra to use OpenAIAgentsHITLApprovalAdapter"
            ) from exc

        prepared = self._prepare_execution(scenario)
        run_config = RunConfig(
            tracing_disabled=self._tracing_disabled,
            trace_include_sensitive_data=False,
            workflow_name=f"agent-eval:{scenario.scenario_id}",
            handoff_input_filter=prepared.handoff_input_filter,
        )
        started = perf_counter()

        first = await Runner.run(
            prepared.agent,
            prepared.runner_input,
            context=prepared.run_context,
            max_turns=scenario.authority.max_turns,
            run_config=run_config,
            session=prepared.session,
        )
        self._raise_recorder_identity_errors(prepared)

        interruptions = [
            item
            for item in first.interruptions
            if isinstance(item, ToolApprovalItem)
            and getattr(getattr(item, "agent", None), "name", None) == spec.agent
            and item.name == spec.tool
        ]

        if not interruptions:
            normalized = self._normalize_items(
                first.new_items,
                start_sequence=0,
                tool_result_recorder=prepared.tool_result_recorder,
                environment_recorder=prepared.environment_recorder,
                handoff_recorder=prepared.handoff_recorder,
            )
            normalized.extend(self._normalize_guardrails(first, start_sequence=len(normalized)))
            target_executed = any(
                event.kind is EvidenceKind.TOOL_REQUEST
                and event.payload.get("agent") == spec.agent
                and event.payload.get("tool") == spec.tool
                for event in normalized
            )
            if not target_executed:
                raise AdapterPreconditionError(
                    code="approval_interruption_missing",
                    reason="configured approval target produced no native SDK approval interruption",
                )
            return await self._result_from_sdk_run(first, normalized, started=started)

        if len(interruptions) != 1:
            raise AdapterPreconditionError(
                code="approval_interruption_ambiguous",
                reason="configured approval target produced multiple native SDK interruptions",
            )

        interruption = interruptions[0]
        call_id = _required_identity(interruption.call_id, phase="approval call")
        arguments = interruption.arguments
        if not isinstance(arguments, str):
            raise AdapterPreconditionError(
                code="approval_arguments_unavailable",
                reason="native SDK approval interruption lacks string tool arguments",
            )
        try:
            ApprovalIntentReceipt.create(
                scenario=scenario,
                agent=spec.agent,
                tool=spec.tool,
                call_id=call_id,
                arguments=arguments,
                resource=None,
                authority_epoch=0,
                approval_request_sequence=0,
            )
        except ApprovalIntentError as exc:
            raise AdapterPreconditionError(
                code="approval_arguments_unverifiable",
                reason="native SDK approval arguments are not canonical finite JSON intent",
            ) from exc

        resource = self._resolve_approval_resource(
            scenario=scenario,
            tool=spec.tool,
            arguments=arguments,
        )

        state = first.to_state()
        if spec.decision is ApprovalDecision.APPROVE:
            state.approve(interruption, always_approve=False)
        else:
            state.reject(interruption)

        resumed = await Runner.run(
            prepared.agent,
            state,
            max_turns=scenario.authority.max_turns,
            run_config=run_config,
            session=prepared.session,
        )
        self._raise_recorder_identity_errors(prepared)

        unresolved = [
            item
            for item in resumed.interruptions
            if isinstance(item, ToolApprovalItem)
            and getattr(getattr(item, "agent", None), "name", None) == spec.agent
            and item.name == spec.tool
            and item.call_id == call_id
        ]
        if unresolved:
            raise AdapterPreconditionError(
                code="approval_decision_not_applied",
                reason="native SDK resumed with the decided approval interruption still pending",
            )

        complete_items = _merge_run_items(first.new_items, resumed.new_items)
        normalized = self._normalize_items(
            complete_items,
            start_sequence=0,
            tool_result_recorder=prepared.tool_result_recorder,
            environment_recorder=prepared.environment_recorder,
            handoff_recorder=prepared.handoff_recorder,
        )
        normalized.extend(self._normalize_guardrails(resumed, start_sequence=len(normalized)))
        stitched = self._stitch_approval_lifecycle(
            scenario=scenario,
            normalized=normalized,
            call_id=call_id,
            arguments=arguments,
            resource=resource,
        )

        if resumed.final_output is not None:
            stitched.append(
                EvidenceEvent(
                    sequence=len(stitched),
                    kind=EvidenceKind.OUTPUT,
                    source="openai-agents:final-output",
                    payload={"output": _json_safe(resumed.final_output)},
                )
            )

        final_state = await self._read_state()
        usage = resumed.context_wrapper.usage
        return AdapterResult(
            events=tuple(stitched),
            final_state=final_state,
            final_output=_stringify_output(resumed.final_output),
            elapsed_ms=(perf_counter() - started) * 1000.0,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

    def _resolve_approval_resource(
        self,
        *,
        scenario: EvaluationScenario,
        tool: str,
        arguments: str,
    ) -> str | None:
        resource_scope_exists = bool(scenario.authority.allowed_resource_prefixes) or any(
            grant.allowed_resource_prefixes for grant in scenario.authority.handoff_grants
        )
        if self._resource_resolver is None:
            if resource_scope_exists:
                raise AdapterPreconditionError(
                    code="approval_resource_unverifiable",
                    reason="resource-scoped approval intent requires a resource resolver",
                )
            return None
        resource = self._resource_resolver(tool, arguments)
        if resource is None and resource_scope_exists:
            raise AdapterPreconditionError(
                code="approval_resource_unverifiable",
                reason="resource-scoped approval intent did not resolve an exact resource identity",
            )
        if resource is not None and (
            not isinstance(resource, str) or not resource or resource != resource.strip()
        ):
            raise AdapterPreconditionError(
                code="approval_resource_unverifiable",
                reason="approval resource resolver returned an unstable resource identity",
            )
        return resource

    def _stitch_approval_lifecycle(
        self,
        *,
        scenario: EvaluationScenario,
        normalized: list[EvidenceEvent],
        call_id: str,
        arguments: str,
        resource: str | None,
    ) -> list[EvidenceEvent]:
        spec = scenario.approval_intent
        if spec is None:  # pragma: no cover - guarded at execute entry
            raise AssertionError("approval intent disappeared during execution")

        target_requests = [
            event
            for event in normalized
            if event.kind is EvidenceKind.TOOL_REQUEST
            and event.payload.get("call_id") == call_id
        ]
        target_approvals = [
            event
            for event in normalized
            if event.kind is EvidenceKind.APPROVAL_REQUEST
            and event.payload.get("call_id") == call_id
        ]
        target_results = [
            event
            for event in normalized
            if event.kind is EvidenceKind.TOOL_RESULT
            and event.payload.get("call_id") == call_id
        ]

        if len(target_requests) != 1:
            raise AdapterPreconditionError(
                code="approval_request_identity_ambiguous",
                reason="native approval call does not map to exactly one SDK tool request",
            )
        if len(target_approvals) != 1:
            raise AdapterPreconditionError(
                code="approval_request_evidence_ambiguous",
                reason="native approval call does not map to exactly one normalized approval request",
            )
        if len(target_results) != 1:
            raise AdapterPreconditionError(
                code="approval_result_identity_ambiguous",
                reason="native approval call does not map to exactly one SDK tool result after resume",
            )

        model_request = target_requests[0]
        approval_request = target_approvals[0]
        result = target_results[0]

        if model_request.payload.get("agent") != spec.agent:
            raise AdapterPreconditionError(
                code="approval_request_agent_mismatch",
                reason="native tool request generating agent does not match approval scenario target",
            )
        if approval_request.payload.get("agent") != spec.agent:
            raise AdapterPreconditionError(
                code="approval_interruption_agent_mismatch",
                reason="native approval interruption generating agent does not match scenario target",
            )
        if model_request.payload.get("tool") != spec.tool:
            raise AdapterPreconditionError(
                code="approval_request_tool_mismatch",
                reason="native tool request identity does not match approval scenario target",
            )
        if model_request.payload.get("arguments") != arguments:
            raise AdapterPreconditionError(
                code="approval_interruption_arguments_mismatch",
                reason="native SDK tool request and approval interruption arguments disagree",
            )

        enriched_approval_payload = dict(approval_request.payload)
        enriched_approval_payload["arguments"] = arguments
        if resource is not None:
            enriched_approval_payload["resource"] = resource
        else:
            enriched_approval_payload.pop("resource", None)

        target_sequences = {
            model_request.sequence,
            approval_request.sequence,
            result.sequence,
        }
        before_approval = [
            event
            for event in normalized
            if event.sequence < approval_request.sequence and event.sequence not in target_sequences
        ]
        after_approval = [
            event
            for event in normalized
            if event.sequence > approval_request.sequence and event.sequence not in target_sequences
        ]

        stitched: list[EvidenceEvent] = []
        for event in before_approval:
            stitched.append(_renumber(event, len(stitched)))

        request_sequence = len(stitched)
        enriched_request = approval_request.model_copy(
            update={
                "sequence": request_sequence,
                "payload": enriched_approval_payload,
            }
        )
        stitched.append(enriched_request)
        authority_epoch = sum(event.kind is EvidenceKind.HANDOFF for event in stitched[:request_sequence])

        try:
            receipt = ApprovalIntentReceipt.create(
                scenario=scenario,
                agent=spec.agent,
                tool=spec.tool,
                call_id=call_id,
                arguments=arguments,
                resource=resource,
                authority_epoch=authority_epoch,
                approval_request_sequence=request_sequence,
            )
        except ApprovalIntentError as exc:  # pragma: no cover - validated earlier
            raise AdapterPreconditionError(
                code="approval_intent_receipt_unavailable",
                reason="approval intent receipt could not be constructed from normalized evidence",
            ) from exc

        stitched.append(
            receipt.to_event(
                sequence=len(stitched),
                source="evaluator:openai-hitl-approval-intent",
            )
        )

        if spec.decision is ApprovalDecision.APPROVE:
            execution_payload = dict(model_request.payload)
            if resource is not None:
                execution_payload["resource"] = resource
            else:
                execution_payload.pop("resource", None)
            stitched.append(
                EvidenceEvent(
                    sequence=len(stitched),
                    kind=EvidenceKind.TOOL_REQUEST,
                    source="openai-agents:approved-execution",
                    payload=execution_payload,
                )
            )
            stitched.append(_renumber(result, len(stitched)))
        else:
            rejection_payload = dict(result.payload)
            rejection_payload["approval_rejected"] = True
            stitched.append(
                EvidenceEvent(
                    sequence=len(stitched),
                    kind=EvidenceKind.TOOL_RESULT,
                    source="openai-agents:approval-rejection-result",
                    payload=rejection_payload,
                )
            )

        for event in after_approval:
            stitched.append(_renumber(event, len(stitched)))
        return stitched

    async def _result_from_sdk_run(
        self,
        result: Any,
        normalized: list[EvidenceEvent],
        *,
        started: float,
    ) -> AdapterResult:
        if result.final_output is not None:
            normalized.append(
                EvidenceEvent(
                    sequence=len(normalized),
                    kind=EvidenceKind.OUTPUT,
                    source="openai-agents:final-output",
                    payload={"output": _json_safe(result.final_output)},
                )
            )
        final_state = await self._read_state()
        usage = result.context_wrapper.usage
        return AdapterResult(
            events=tuple(normalized),
            final_state=final_state,
            final_output=_stringify_output(result.final_output),
            elapsed_ms=(perf_counter() - started) * 1000.0,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )


def _merge_run_items(first: Sequence[object], resumed: Sequence[object]) -> list[object]:
    """Return one logical run-item history whether resume returns cumulative or delta items."""
    first_items = list(first)
    resumed_items = list(resumed)
    if len(resumed_items) >= len(first_items) and all(
        _item_signature(left) == _item_signature(right)
        for left, right in zip(first_items, resumed_items, strict=False)
    ):
        return resumed_items
    return [*first_items, *resumed_items]


def _item_signature(item: object) -> tuple[object, ...]:
    raw = getattr(item, "raw_item", None)
    call_id = getattr(item, "call_id", None)
    if call_id is None:
        call_id = _raw_attr(raw, "call_id") or _raw_attr(raw, "id")
    return (
        getattr(item, "type", type(item).__name__),
        getattr(getattr(item, "agent", None), "name", None),
        call_id,
        getattr(item, "name", None),
        getattr(getattr(item, "source_agent", None), "name", None),
        getattr(getattr(item, "target_agent", None), "name", None),
        repr(raw),
    )


def _renumber(event: EvidenceEvent, sequence: int) -> EvidenceEvent:
    return event.model_copy(update={"sequence": sequence})


def _required_identity(value: object, *, phase: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise AdapterPreconditionError(
            code="approval_identity_unavailable",
            reason=f"native SDK {phase} lacks a stable non-empty identity",
        )
    return value


def _raw_attr(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value == value and value not in (float("inf"), float("-inf")):
            return value
        return repr(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump(mode="json"))
    return repr(value)
