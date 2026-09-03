"""OpenAI Agents SDK adapter using only documented public result surfaces.

This module is optional. Importing the package core does not import or require ``openai-agents``.
The adapter normalizes SDK-owned events, while a separately supplied state reader owns terminal
outcome observation. Provider output never becomes the state oracle by construction.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import copy
from dataclasses import asdict, dataclass, is_dataclass
from time import perf_counter

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult
from agent_evals.adversarial.cases import AttackChannel, AttackFixture, extract_attack
from agent_evals.adversarial.channels import ToolResultAttackPayload
from agent_evals.adversarial.delivery import AttackDeliveryReceipt
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind

StateReader = Callable[[], Mapping[str, object] | Awaitable[Mapping[str, object]]]
ResourceResolver = Callable[[str, str | None], str | None]
RunnerInput = str | list[dict[str, str]]


@dataclass(slots=True)
class _ToolResultDeliveryRecorder:
    """Per-execution mutable state; never stored on the reusable adapter or original agent."""

    event: EvidenceEvent | None = None
    call_id: str | None = None
    attempted: bool = False
    identity_error: bool = False


class OpenAIAgentsAdapter:
    """Evaluate an OpenAI Agents SDK workflow without granting the SDK grading authority."""

    def __init__(
        self,
        agent: object,
        *,
        state_reader: StateReader,
        resource_resolver: ResourceResolver | None = None,
        tracing_disabled: bool = True,
    ) -> None:
        self._agent = agent
        self._state_reader = state_reader
        self._resource_resolver = resource_resolver
        self._tracing_disabled = tracing_disabled

    @property
    def name(self) -> str:
        return "openai-agents"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        del subject, trial_id

        try:
            from agents import RunConfig, Runner
            from agents.exceptions import (
                InputGuardrailTripwireTriggered,
                MaxTurnsExceeded,
                OutputGuardrailTripwireTriggered,
                ToolInputGuardrailTripwireTriggered,
                ToolOutputGuardrailTripwireTriggered,
            )
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("install the 'openai' extra to use OpenAIAgentsAdapter") from exc

        runner_agent, runner_input, delivery_events, tool_result_recorder = self._prepare_execution(
            scenario
        )
        started = perf_counter()
        run_config = RunConfig(
            tracing_disabled=self._tracing_disabled,
            trace_include_sensitive_data=False,
            workflow_name=f"agent-eval:{scenario.scenario_id}",
        )

        try:
            result = await Runner.run(
                runner_agent,
                runner_input,
                max_turns=scenario.authority.max_turns,
                run_config=run_config,
            )
        except MaxTurnsExceeded:
            self._raise_recorder_identity_error(tool_result_recorder)
            final_state = await self._read_state()
            events = self._exception_delivery_events(delivery_events, tool_result_recorder)
            events.append(
                EvidenceEvent(
                    sequence=len(events),
                    kind=EvidenceKind.POLICY_VIOLATION,
                    source="openai-agents:runner",
                    payload={
                        "reason": "turn budget exceeded",
                        "max_turns": scenario.authority.max_turns,
                    },
                    critical=True,
                )
            )
            return AdapterResult(
                events=tuple(events),
                final_state=final_state,
                elapsed_ms=(perf_counter() - started) * 1000.0,
            )
        except (
            InputGuardrailTripwireTriggered,
            OutputGuardrailTripwireTriggered,
            ToolInputGuardrailTripwireTriggered,
            ToolOutputGuardrailTripwireTriggered,
        ) as exc:
            self._raise_recorder_identity_error(tool_result_recorder)
            final_state = await self._read_state()
            events = self._exception_delivery_events(delivery_events, tool_result_recorder)
            events.append(
                EvidenceEvent(
                    sequence=len(events),
                    kind=EvidenceKind.GUARDRAIL,
                    source="openai-agents:guardrail",
                    payload={
                        "tripwire_triggered": True,
                        "exception_type": type(exc).__name__,
                    },
                )
            )
            return AdapterResult(
                events=tuple(events),
                final_state=final_state,
                elapsed_ms=(perf_counter() - started) * 1000.0,
            )

        self._raise_recorder_identity_error(tool_result_recorder)
        events = list(delivery_events)
        events.extend(
            self._normalize_items(
                result.new_items,
                start_sequence=len(events),
                tool_result_recorder=tool_result_recorder,
            )
        )
        events.extend(self._normalize_guardrails(result, start_sequence=len(events)))
        if result.final_output is not None:
            events.append(
                EvidenceEvent(
                    sequence=len(events),
                    kind=EvidenceKind.OUTPUT,
                    source="openai-agents:final-output",
                    payload={"output": _json_safe(result.final_output)},
                )
            )

        final_state = await self._read_state()
        usage = result.context_wrapper.usage
        return AdapterResult(
            events=tuple(events),
            final_state=final_state,
            final_output=_stringify_output(result.final_output),
            elapsed_ms=(perf_counter() - started) * 1000.0,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

    def _prepare_execution(
        self,
        scenario: EvaluationScenario,
    ) -> tuple[object, RunnerInput, tuple[EvidenceEvent, ...], _ToolResultDeliveryRecorder | None]:
        attack = extract_attack(scenario)
        if attack is None:
            return self._agent, scenario.objective, (), None
        if attack.channel is AttackChannel.USER_INPUT:
            injection_point = "openai-agents:Runner.run.input[1]"
            receipt = AttackDeliveryReceipt.from_scenario(
                scenario,
                injection_point=injection_point,
            )
            event = receipt.to_event(
                sequence=0,
                source="injector:openai-agents:user-input",
            )
            runner_input: list[dict[str, str]] = [
                {"role": "user", "content": scenario.objective},
                {"role": "user", "content": attack.payload_json},
            ]
            return self._agent, runner_input, (event,), None
        if attack.channel is AttackChannel.TOOL_RESULT:
            runner_agent, recorder = self._prepare_tool_result_agent(scenario, attack)
            return runner_agent, scenario.objective, (), recorder
        raise AdapterPreconditionError(
            code="unsupported_attack_channel",
            reason=(
                "openai-agents adapter does not implement adversarial channel "
                f"{attack.channel.value!r}"
            ),
        )

    def _prepare_tool_result_agent(
        self,
        scenario: EvaluationScenario,
        attack: AttackFixture,
    ) -> tuple[object, _ToolResultDeliveryRecorder]:
        try:
            from agents import Agent, FunctionTool
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("install the 'openai' extra to use OpenAIAgentsAdapter") from exc

        try:
            spec = ToolResultAttackPayload.from_fixture(attack)
        except ValueError as exc:
            raise AdapterPreconditionError(
                code="invalid_tool_result_attack",
                reason="tool-result attack payload does not satisfy the required routing contract",
            ) from exc

        if not isinstance(self._agent, Agent):
            raise AdapterPreconditionError(
                code="unsupported_agent_type",
                reason="tool-result injection requires an OpenAI Agents SDK Agent instance",
            )

        same_name = [tool for tool in self._agent.tools if _raw_attr(tool, "name") == spec.tool]
        function_matches = [tool for tool in same_name if isinstance(tool, FunctionTool)]
        if not same_name:
            raise AdapterPreconditionError(
                code="attack_target_unavailable",
                reason=f"local tool-result attack target {spec.tool!r} is unavailable",
            )
        if not function_matches:
            raise AdapterPreconditionError(
                code="unsupported_attack_target_type",
                reason=(f"tool-result attack target {spec.tool!r} is not a local FunctionTool"),
            )
        if len(same_name) != 1 or len(function_matches) != 1:
            raise AdapterPreconditionError(
                code="ambiguous_attack_target",
                reason=f"tool-result attack target {spec.tool!r} is not unique",
            )

        target = function_matches[0]
        wrapped_target = copy(target)
        original_invoke = wrapped_target.on_invoke_tool
        recorder = _ToolResultDeliveryRecorder()

        async def inject_tool_result(context: object, arguments: str) -> object:
            if recorder.attempted:
                return await original_invoke(context, arguments)
            recorder.attempted = True
            call_id = _raw_attr(context, "tool_call_id")
            if not isinstance(call_id, str) or not call_id:
                recorder.identity_error = True
                return await original_invoke(context, arguments)

            injection_point = f"openai-agents:FunctionTool:{spec.tool}:call:{call_id}:output"
            receipt = AttackDeliveryReceipt.from_scenario(
                scenario,
                injection_point=injection_point,
            )
            recorder.call_id = call_id
            recorder.event = receipt.to_event(
                sequence=0,
                source="injector:openai-agents:tool-result",
            )
            return attack.payload_json

        wrapped_target.on_invoke_tool = inject_tool_result
        tools = [wrapped_target if tool is target else tool for tool in self._agent.tools]
        return self._agent.clone(tools=tools), recorder

    @staticmethod
    def _raise_recorder_identity_error(
        recorder: _ToolResultDeliveryRecorder | None,
    ) -> None:
        if recorder is not None and recorder.identity_error:
            raise AdapterPreconditionError(
                code="tool_call_identity_unavailable",
                reason="tool-result injector could not bind delivery to a tool call identity",
            )

    @staticmethod
    def _exception_delivery_events(
        delivery_events: tuple[EvidenceEvent, ...],
        recorder: _ToolResultDeliveryRecorder | None,
    ) -> list[EvidenceEvent]:
        events = list(delivery_events)
        if recorder is not None and recorder.event is not None:
            events.append(recorder.event.model_copy(update={"sequence": len(events)}))
        return events

    async def _read_state(self) -> dict[str, object]:
        observed = self._state_reader()
        if inspect.isawaitable(observed):
            observed = await observed
        return dict(observed)

    def _normalize_items(
        self,
        items: Sequence[object],
        *,
        start_sequence: int = 0,
        tool_result_recorder: _ToolResultDeliveryRecorder | None = None,
    ) -> list[EvidenceEvent]:
        from agents.items import (
            HandoffOutputItem,
            ToolApprovalItem,
            ToolCallItem,
            ToolCallOutputItem,
        )

        events: list[EvidenceEvent] = []
        delivery_inserted = False
        for item in items:
            if isinstance(item, ToolCallItem):
                tool = item.tool_name
                arguments = _raw_attr(item.raw_item, "arguments")
                payload: dict[str, object] = {
                    "tool": tool,
                    "call_id": _raw_attr(item.raw_item, "call_id")
                    or _raw_attr(item.raw_item, "id"),
                    "arguments": arguments,
                }
                if isinstance(tool, str) and self._resource_resolver is not None:
                    resource = self._resource_resolver(
                        tool,
                        arguments if isinstance(arguments, str) else None,
                    )
                    if resource is not None:
                        payload["resource"] = resource
                events.append(
                    EvidenceEvent(
                        sequence=start_sequence + len(events),
                        kind=EvidenceKind.TOOL_REQUEST,
                        source="openai-agents:new_items",
                        payload=_json_safe_mapping(payload),
                    )
                )
            elif isinstance(item, ToolCallOutputItem):
                if (
                    not delivery_inserted
                    and tool_result_recorder is not None
                    and tool_result_recorder.event is not None
                    and item.call_id == tool_result_recorder.call_id
                ):
                    events.append(
                        tool_result_recorder.event.model_copy(
                            update={"sequence": start_sequence + len(events)}
                        )
                    )
                    delivery_inserted = True
                events.append(
                    EvidenceEvent(
                        sequence=start_sequence + len(events),
                        kind=EvidenceKind.TOOL_RESULT,
                        source="openai-agents:new_items",
                        payload={"call_id": item.call_id, "output": _json_safe(item.output)},
                    )
                )
            elif isinstance(item, HandoffOutputItem):
                events.append(
                    EvidenceEvent(
                        sequence=start_sequence + len(events),
                        kind=EvidenceKind.HANDOFF,
                        source="openai-agents:new_items",
                        payload={
                            "source_agent": item.source_agent.name,
                            "target_agent": item.target_agent.name,
                        },
                    )
                )
            elif isinstance(item, ToolApprovalItem):
                events.append(
                    EvidenceEvent(
                        sequence=start_sequence + len(events),
                        kind=EvidenceKind.APPROVAL_REQUEST,
                        source="openai-agents:new_items",
                        payload={
                            "tool": item.name,
                            "call_id": item.call_id,
                            "arguments": item.arguments,
                        },
                    )
                )

        if (
            not delivery_inserted
            and tool_result_recorder is not None
            and tool_result_recorder.event is not None
        ):
            events.append(
                tool_result_recorder.event.model_copy(
                    update={"sequence": start_sequence + len(events)}
                )
            )
        return events

    @staticmethod
    def _normalize_guardrails(
        result: object,
        *,
        start_sequence: int,
    ) -> list[EvidenceEvent]:
        events: list[EvidenceEvent] = []
        groups = (
            ("input", getattr(result, "input_guardrail_results", ())),
            ("output", getattr(result, "output_guardrail_results", ())),
            ("tool_input", getattr(result, "tool_input_guardrail_results", ())),
            ("tool_output", getattr(result, "tool_output_guardrail_results", ())),
        )
        for boundary, results in groups:
            for guardrail_result in results:
                guardrail = getattr(guardrail_result, "guardrail", None)
                output = getattr(guardrail_result, "output", None)
                get_name = getattr(guardrail, "get_name", None)
                name = get_name() if callable(get_name) else type(guardrail).__name__
                triggered = bool(getattr(output, "tripwire_triggered", False))
                behavior = getattr(output, "behavior", None)
                events.append(
                    EvidenceEvent(
                        sequence=start_sequence + len(events),
                        kind=EvidenceKind.GUARDRAIL,
                        source="openai-agents:guardrail-result",
                        payload={
                            "boundary": boundary,
                            "name": name,
                            "triggered": triggered,
                            "behavior": _json_safe(behavior),
                        },
                    )
                )
        return events


def _raw_attr(raw: object, name: str) -> object | None:
    if isinstance(raw, dict):
        return raw.get(name)
    return getattr(raw, name, None)


def _json_safe_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _json_safe(item) for key, item in value.items()}


def _json_safe(value: object) -> object:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if value == value and value not in (float("inf"), float("-inf")):
            return value
        return repr(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    return repr(value)


def _stringify_output(value: object | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    safe = _json_safe(value)
    try:
        return json.dumps(safe, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return repr(value)
