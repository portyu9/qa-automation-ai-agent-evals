"""OpenAI Agents SDK adapter using only documented public result surfaces.

This module is optional. Importing the package core does not import or require ``openai-agents``.
The adapter normalizes SDK-owned events, while a separately supplied state reader owns terminal
outcome observation. Provider output never becomes the state oracle by construction.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from time import perf_counter

from agent_evals.adapters.base import AdapterResult
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind

StateReader = Callable[[], Mapping[str, object] | Awaitable[Mapping[str, object]]]
ResourceResolver = Callable[[str, str | None], str | None]


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

        started = perf_counter()
        run_config = RunConfig(
            tracing_disabled=self._tracing_disabled,
            trace_include_sensitive_data=False,
            workflow_name=f"agent-eval:{scenario.scenario_id}",
        )

        try:
            result = await Runner.run(
                self._agent,
                scenario.objective,
                max_turns=scenario.authority.max_turns,
                run_config=run_config,
            )
        except MaxTurnsExceeded:
            final_state = await self._read_state()
            return AdapterResult(
                events=(
                    EvidenceEvent(
                        sequence=0,
                        kind=EvidenceKind.POLICY_VIOLATION,
                        source="openai-agents:runner",
                        payload={
                            "reason": "turn budget exceeded",
                            "max_turns": scenario.authority.max_turns,
                        },
                        critical=True,
                    ),
                ),
                final_state=final_state,
                elapsed_ms=(perf_counter() - started) * 1000.0,
            )
        except (
            InputGuardrailTripwireTriggered,
            OutputGuardrailTripwireTriggered,
            ToolInputGuardrailTripwireTriggered,
            ToolOutputGuardrailTripwireTriggered,
        ) as exc:
            final_state = await self._read_state()
            return AdapterResult(
                events=(
                    EvidenceEvent(
                        sequence=0,
                        kind=EvidenceKind.GUARDRAIL,
                        source="openai-agents:guardrail",
                        payload={
                            "tripwire_triggered": True,
                            "exception_type": type(exc).__name__,
                        },
                    ),
                ),
                final_state=final_state,
                elapsed_ms=(perf_counter() - started) * 1000.0,
            )

        events = self._normalize_items(result.new_items)
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

    async def _read_state(self) -> dict[str, object]:
        observed = self._state_reader()
        if inspect.isawaitable(observed):
            observed = await observed
        return dict(observed)

    def _normalize_items(self, items: Sequence[object]) -> list[EvidenceEvent]:
        from agents.items import (
            HandoffOutputItem,
            ToolApprovalItem,
            ToolCallItem,
            ToolCallOutputItem,
        )

        events: list[EvidenceEvent] = []
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
                        sequence=len(events),
                        kind=EvidenceKind.TOOL_REQUEST,
                        source="openai-agents:new_items",
                        payload=_json_safe_mapping(payload),
                    )
                )
            elif isinstance(item, ToolCallOutputItem):
                events.append(
                    EvidenceEvent(
                        sequence=len(events),
                        kind=EvidenceKind.TOOL_RESULT,
                        source="openai-agents:new_items",
                        payload={"call_id": item.call_id, "output": _json_safe(item.output)},
                    )
                )
            elif isinstance(item, HandoffOutputItem):
                events.append(
                    EvidenceEvent(
                        sequence=len(events),
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
                        sequence=len(events),
                        kind=EvidenceKind.APPROVAL_REQUEST,
                        source="openai-agents:new_items",
                        payload={
                            "tool": item.name,
                            "call_id": item.call_id,
                            "arguments": item.arguments,
                        },
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
