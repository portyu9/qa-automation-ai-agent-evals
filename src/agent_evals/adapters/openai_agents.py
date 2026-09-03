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
from typing import Any

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult
from agent_evals.adversarial.cases import AttackChannel, AttackFixture, extract_attack
from agent_evals.adversarial.channels import (
    HandoffAttackPayload,
    MemoryAttackPayload,
    ToolMetadataAttackPayload,
    ToolResultAttackPayload,
)
from agent_evals.adversarial.delivery import AttackDeliveryReceipt
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind

StateReader = Callable[[], Mapping[str, object] | Awaitable[Mapping[str, object]]]
ResourceResolver = Callable[[str, str | None], str | None]
RunnerInput = str | list[dict[str, str]]


@dataclass(slots=True)
class _ToolResultDeliveryRecorder:
    """Per-execution mutable state for one-shot local tool-result delivery."""

    event: EvidenceEvent | None = None
    call_id: str | None = None
    attempted: bool = False
    identity_error: bool = False


@dataclass(slots=True)
class _HandoffDeliveryRecorder:
    """Per-execution state proving that the first SDK handoff filter actually ran."""

    event: EvidenceEvent | None = None
    attempted: bool = False


@dataclass(frozen=True, slots=True)
class _PreparedExecution:
    """All provider-specific execution inputs prepared for exactly one trial."""

    agent: object
    runner_input: RunnerInput
    delivery_events: tuple[EvidenceEvent, ...] = ()
    tool_result_recorder: _ToolResultDeliveryRecorder | None = None
    session: object | None = None
    handoff_input_filter: Any | None = None
    handoff_recorder: _HandoffDeliveryRecorder | None = None


class _InjectedMemorySession:
    """Per-trial SDK Session protocol implementation seeded with one poisoned history item."""

    session_settings: None = None

    def __init__(self, *, session_id: str, memory_text: str) -> None:
        self.session_id = session_id
        self._items: list[Any] = [{"role": "user", "content": memory_text}]

    async def get_items(self, limit: int | None = None) -> list[Any]:
        if limit is None:
            return list(self._items)
        if limit <= 0:
            return []
        return list(self._items[-limit:])

    async def add_items(self, items: list[Any]) -> None:
        self._items.extend(items)

    async def pop_item(self) -> Any | None:
        if not self._items:
            return None
        return self._items.pop()

    async def clear_session(self) -> None:
        self._items.clear()


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

        prepared = self._prepare_execution(scenario)
        started = perf_counter()
        run_config = RunConfig(
            tracing_disabled=self._tracing_disabled,
            trace_include_sensitive_data=False,
            workflow_name=f"agent-eval:{scenario.scenario_id}",
            handoff_input_filter=prepared.handoff_input_filter,
        )

        try:
            result = await Runner.run(
                prepared.agent,
                prepared.runner_input,
                max_turns=scenario.authority.max_turns,
                run_config=run_config,
                session=prepared.session,
            )
        except MaxTurnsExceeded:
            self._raise_recorder_identity_error(prepared.tool_result_recorder)
            final_state = await self._read_state()
            events = self._exception_delivery_events(prepared)
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
            self._raise_recorder_identity_error(prepared.tool_result_recorder)
            final_state = await self._read_state()
            events = self._exception_delivery_events(prepared)
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

        self._raise_recorder_identity_error(prepared.tool_result_recorder)
        events = list(prepared.delivery_events)
        events.extend(
            self._normalize_items(
                result.new_items,
                start_sequence=len(events),
                tool_result_recorder=prepared.tool_result_recorder,
                handoff_recorder=prepared.handoff_recorder,
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

    def _prepare_execution(self, scenario: EvaluationScenario) -> _PreparedExecution:
        attack = extract_attack(scenario)
        if attack is None:
            return _PreparedExecution(agent=self._agent, runner_input=scenario.objective)
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
            return _PreparedExecution(
                agent=self._agent,
                runner_input=runner_input,
                delivery_events=(event,),
            )
        if attack.channel is AttackChannel.TOOL_RESULT:
            runner_agent, recorder = self._prepare_tool_result_agent(scenario, attack)
            return _PreparedExecution(
                agent=runner_agent,
                runner_input=scenario.objective,
                tool_result_recorder=recorder,
            )
        if attack.channel is AttackChannel.TOOL_METADATA:
            runner_agent, events = self._prepare_tool_metadata_agent(scenario, attack)
            return _PreparedExecution(
                agent=runner_agent,
                runner_input=scenario.objective,
                delivery_events=events,
            )
        if attack.channel is AttackChannel.MEMORY:
            runner_session, events = self._prepare_memory_session(scenario, attack)
            return _PreparedExecution(
                agent=self._agent,
                runner_input=scenario.objective,
                delivery_events=events,
                session=runner_session,
            )
        if attack.channel is AttackChannel.HANDOFF:
            handoff_filter, handoff_recorder = self._prepare_handoff_filter(scenario, attack)
            return _PreparedExecution(
                agent=self._agent,
                runner_input=scenario.objective,
                handoff_input_filter=handoff_filter,
                handoff_recorder=handoff_recorder,
            )
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
            spec = ToolResultAttackPayload.from_fixture(attack)
        except ValueError as exc:
            raise AdapterPreconditionError(
                code="invalid_tool_result_attack",
                reason="tool-result attack payload does not satisfy the required routing contract",
            ) from exc

        agent, target = self._resolve_local_function_tool(
            tool_name=spec.tool,
            attack_label="tool-result",
        )
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
        tools = [wrapped_target if tool is target else tool for tool in agent.tools]
        return agent.clone(tools=tools), recorder

    def _prepare_tool_metadata_agent(
        self,
        scenario: EvaluationScenario,
        attack: AttackFixture,
    ) -> tuple[object, tuple[EvidenceEvent, ...]]:
        try:
            spec = ToolMetadataAttackPayload.from_fixture(attack)
        except ValueError as exc:
            raise AdapterPreconditionError(
                code="invalid_tool_metadata_attack",
                reason="tool-metadata attack payload does not satisfy the required routing contract",
            ) from exc

        agent, target = self._resolve_local_function_tool(
            tool_name=spec.tool,
            attack_label="tool-metadata",
        )
        wrapped_target = copy(target)
        wrapped_target.description = attack.payload_json
        tools = [wrapped_target if tool is target else tool for tool in agent.tools]
        runner_agent = agent.clone(tools=tools)

        injection_point = f"openai-agents:FunctionTool:{spec.tool}:description"
        receipt = AttackDeliveryReceipt.from_scenario(
            scenario,
            injection_point=injection_point,
        )
        event = receipt.to_event(
            sequence=0,
            source="injector:openai-agents:tool-metadata",
        )
        return runner_agent, (event,)

    @staticmethod
    def _prepare_memory_session(
        scenario: EvaluationScenario,
        attack: AttackFixture,
    ) -> tuple[_InjectedMemorySession, tuple[EvidenceEvent, ...]]:
        try:
            MemoryAttackPayload.from_fixture(attack)
        except ValueError as exc:
            raise AdapterPreconditionError(
                code="invalid_memory_attack",
                reason="memory attack payload does not satisfy the session-history contract",
            ) from exc

        session = _InjectedMemorySession(
            session_id=f"agent-evals-memory:{scenario.identity[:16]}",
            memory_text=attack.payload_json,
        )
        receipt = AttackDeliveryReceipt.from_scenario(
            scenario,
            injection_point="openai-agents:Session.get_items[0]",
        )
        event = receipt.to_event(
            sequence=0,
            source="injector:openai-agents:memory-session-history",
        )
        return session, (event,)

    @staticmethod
    def _prepare_handoff_filter(
        scenario: EvaluationScenario,
        attack: AttackFixture,
    ) -> tuple[Any, _HandoffDeliveryRecorder]:
        try:
            HandoffAttackPayload.from_fixture(attack)
        except ValueError as exc:
            raise AdapterPreconditionError(
                code="invalid_handoff_attack",
                reason="handoff attack payload does not satisfy the context-transfer contract",
            ) from exc

        recorder = _HandoffDeliveryRecorder()

        def inject_first_handoff_context(handoff_input_data: Any) -> Any:
            if recorder.attempted:
                return handoff_input_data

            history = handoff_input_data.input_history
            poison = {"role": "user", "content": attack.payload_json}
            if isinstance(history, str):
                injected_history = (
                    {"role": "user", "content": history},
                    poison,
                )
            elif isinstance(history, tuple):
                injected_history = (*history, poison)
            else:
                raise AdapterPreconditionError(
                    code="handoff_input_contract_unavailable",
                    reason="handoff injector received an unsupported SDK input-history shape",
                )

            clone = getattr(handoff_input_data, "clone", None)
            if not callable(clone):
                raise AdapterPreconditionError(
                    code="handoff_input_contract_unavailable",
                    reason="handoff injector cannot clone the SDK handoff input contract",
                )

            injected = clone(input_history=injected_history)
            receipt = AttackDeliveryReceipt.from_scenario(
                scenario,
                injection_point=(
                    "openai-agents:RunConfig.handoff_input_filter:first:input_history[-1]"
                ),
            )
            recorder.event = receipt.to_event(
                sequence=0,
                source="injector:openai-agents:handoff-context",
            )
            recorder.attempted = True
            return injected

        return inject_first_handoff_context, recorder

    def _resolve_local_function_tool(
        self,
        *,
        tool_name: str,
        attack_label: str,
    ) -> tuple[Any, Any]:
        try:
            from agents import Agent, FunctionTool
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("install the 'openai' extra to use OpenAIAgentsAdapter") from exc

        if not isinstance(self._agent, Agent):
            raise AdapterPreconditionError(
                code="unsupported_agent_type",
                reason=(f"{attack_label} injection requires an OpenAI Agents SDK Agent instance"),
            )

        same_name = [tool for tool in self._agent.tools if _raw_attr(tool, "name") == tool_name]
        function_matches = [tool for tool in same_name if isinstance(tool, FunctionTool)]
        if not same_name:
            raise AdapterPreconditionError(
                code="attack_target_unavailable",
                reason=f"local {attack_label} attack target {tool_name!r} is unavailable",
            )
        if not function_matches:
            raise AdapterPreconditionError(
                code="unsupported_attack_target_type",
                reason=f"{attack_label} attack target {tool_name!r} is not a local FunctionTool",
            )
        if len(same_name) != 1 or len(function_matches) != 1:
            raise AdapterPreconditionError(
                code="ambiguous_attack_target",
                reason=f"{attack_label} attack target {tool_name!r} is not unique",
            )
        return self._agent, function_matches[0]

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
    def _exception_delivery_events(prepared: _PreparedExecution) -> list[EvidenceEvent]:
        events = list(prepared.delivery_events)
        for recorder in (prepared.tool_result_recorder, prepared.handoff_recorder):
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
        handoff_recorder: _HandoffDeliveryRecorder | None = None,
    ) -> list[EvidenceEvent]:
        from agents.items import (
            HandoffOutputItem,
            ToolApprovalItem,
            ToolCallItem,
            ToolCallOutputItem,
        )

        events: list[EvidenceEvent] = []
        tool_delivery_inserted = False
        handoff_delivery_inserted = False
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
                    not tool_delivery_inserted
                    and tool_result_recorder is not None
                    and tool_result_recorder.event is not None
                    and item.call_id == tool_result_recorder.call_id
                ):
                    events.append(
                        tool_result_recorder.event.model_copy(
                            update={"sequence": start_sequence + len(events)}
                        )
                    )
                    tool_delivery_inserted = True
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
                if (
                    not handoff_delivery_inserted
                    and handoff_recorder is not None
                    and handoff_recorder.event is not None
                ):
                    events.append(
                        handoff_recorder.event.model_copy(
                            update={"sequence": start_sequence + len(events)}
                        )
                    )
                    handoff_delivery_inserted = True
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
            not tool_delivery_inserted
            and tool_result_recorder is not None
            and tool_result_recorder.event is not None
        ):
            events.append(
                tool_result_recorder.event.model_copy(
                    update={"sequence": start_sequence + len(events)}
                )
            )
        if (
            not handoff_delivery_inserted
            and handoff_recorder is not None
            and handoff_recorder.event is not None
        ):
            events.append(
                handoff_recorder.event.model_copy(update={"sequence": start_sequence + len(events)})
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
