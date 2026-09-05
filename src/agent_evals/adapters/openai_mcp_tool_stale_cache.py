"""OpenAI Agents SDK adapter for verified host-refreshed MCP stale-tool removal delivery."""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any, cast

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult
from agent_evals.adapters.openai_agents import OpenAIAgentsAdapter, ResourceResolver, StateReader
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.mcp.agent_stale_cache_bridge import (
    MCPAgentToolStaleCacheReceipt,
    create_stale_cache_protocol_receipt,
)
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_REQUIRED_PROTOCOL_VERSION = "2026-07-28"
_CONTROL_TOOL = "__agent_evals_remove_target__"
_EXPECTED_CONTROL_RESULT = "target-removed"


class OpenAIAgentsMCPToolStaleCacheAdapter:
    """Verify host-refreshed removal of one stale cached MCP tool at the model boundary.

    The controlled harness owns live target removal and this adapter owns one tools-cache
    invalidation after the real stale-call rejection. The model is not credited for initiating
    refresh; the bridge closes only after refreshed target absence and the exact rejection are both
    observed through the public SDK Model boundary.
    """

    def __init__(
        self,
        agent: object,
        *,
        stdio_params: Mapping[str, object],
        fault: MCPFaultSpec,
        state_reader: StateReader,
        resource_resolver: ResourceResolver | None = None,
        run_context: object | None = None,
        tracing_disabled: bool = True,
    ) -> None:
        if fault.kind is not MCPFaultKind.TOOL_LIST_STALE_CACHE:
            raise ValueError("OpenAI MCP stale-cache bridge requires a TOOL_LIST_STALE_CACHE fault")
        if fault.tool_name == _CONTROL_TOOL:
            raise ValueError("MCP stale-cache target must not collide with evaluator control tool")
        self._agent = agent
        self._stdio_params = _validated_stdio_params(stdio_params)
        self._fault = fault
        self._state_reader = state_reader
        self._resource_resolver = resource_resolver
        self._run_context = run_context
        self._tracing_disabled = tracing_disabled

    @property
    def name(self) -> str:
        return "openai-agents-mcp-tool-stale-cache"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        server = _new_stdio_server(self._stdio_params)
        await server.connect()
        try:
            protocol_version = _negotiated_protocol_version(server)
            if protocol_version != _REQUIRED_PROTOCOL_VERSION:
                raise AdapterPreconditionError(
                    code="mcp_protocol_version_mismatch",
                    reason="connected MCP session did not negotiate the required protocol revision",
                )

            recorder = _MCPToolStaleCacheRecorder(
                original_list_tools=server.list_tools,
                original_call_tool=server.call_tool,
                invalidate_tools_cache=server.invalidate_tools_cache,
                fault=self._fault,
                protocol_version=protocol_version,
            )
            server.list_tools = recorder.list_tools
            server.call_tool = recorder.call_tool
            runner_agent = _clone_agent_with_controlled_server_and_observer(
                self._agent,
                server=server,
                target_tool_name=self._fault.tool_name,
                recorder=recorder,
            )

            delegated = await OpenAIAgentsAdapter(
                runner_agent,
                state_reader=self._state_reader,
                resource_resolver=self._resource_resolver,
                run_context=self._run_context,
                tracing_disabled=self._tracing_disabled,
            ).execute(
                subject=subject,
                scenario=scenario,
                trial_id=trial_id,
            )

            recorder.require_complete_relation()
            protocol_receipt = recorder.require_protocol_receipt()
            return _attach_verified_stale_cache_bridge(
                delegated,
                scenario=scenario,
                fault=self._fault,
                protocol_receipt=protocol_receipt,
                recorder=recorder,
            )
        finally:
            await server.cleanup()


class _MCPToolStaleCacheRecorder:
    """Record one stale cached target, live rejection, host refresh, and model-visible absence."""

    def __init__(
        self,
        *,
        original_list_tools: Callable[..., Awaitable[list[Any]]],
        original_call_tool: Callable[..., Awaitable[object]],
        invalidate_tools_cache: Callable[[], None],
        fault: MCPFaultSpec,
        protocol_version: str,
    ) -> None:
        self._original_list_tools = original_list_tools
        self._original_call_tool = original_call_tool
        self._invalidate_tools_cache = invalidate_tools_cache
        self._fault = fault
        self._protocol_version = protocol_version
        self._ordinal = 0
        self._target_calls = 0
        self._post_invalidation_lists = 0
        self._control_failed = False
        self._control_leaked = False
        self._initial_protocol_names: tuple[str, ...] | None = None
        self._cached_protocol_names: tuple[str, ...] | None = None
        self._refreshed_protocol_names: tuple[str, ...] | None = None
        self._initial_model_names: tuple[str, ...] | None = None
        self._refreshed_model_names: tuple[str, ...] | None = None
        self._stale_arguments: dict[str, Any] | None = None
        self._stale_text: str | None = None
        self._stale_is_error: bool | None = None
        self._model_error_text: str | None = None
        self._model_error_call_id: str | None = None
        self._initial_list_ordinal: int | None = None
        self._removal_ordinal: int | None = None
        self._cached_list_ordinal: int | None = None
        self._stale_call_ordinal: int | None = None
        self._cache_invalidation_ordinal: int | None = None
        self._refreshed_list_ordinal: int | None = None

    @property
    def ttl_ms(self) -> int:
        payload = self._fault.payload
        if not isinstance(payload, dict):
            raise AdapterPreconditionError(
                code="mcp_stale_cache_fault_payload_invalid",
                reason="stale-cache fault payload is not an object",
            )
        ttl_ms = payload.get("ttl_ms")
        if isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int) or ttl_ms <= 0:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_fault_payload_invalid",
                reason="stale-cache fault TTL is not a positive integer",
            )
        return ttl_ms

    @property
    def stale_arguments(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._stale_arguments)

    @property
    def stale_protocol_text(self) -> str:
        if self._stale_text is None:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_rejection_missing",
                reason="removed MCP target did not yield a stale-call rejection",
            )
        return self._stale_text

    @property
    def model_error_output(self) -> dict[str, str]:
        if self._model_error_text is None:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_model_rejection_missing",
                reason="post-refresh model boundary did not expose the stale-call rejection",
            )
        return {"type": "text", "text": self._model_error_text}

    @property
    def model_error_call_id(self) -> str:
        if self._model_error_call_id is None:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_model_call_identity_missing",
                reason="post-refresh model boundary did not preserve stale OpenAI call identity",
            )
        return self._model_error_call_id

    @property
    def initial_model_names(self) -> tuple[str, ...]:
        return self._require_names(self._initial_model_names, "initial model-visible")

    @property
    def refreshed_model_names(self) -> tuple[str, ...]:
        return self._require_names(self._refreshed_model_names, "refreshed model-visible")

    @property
    def initial_protocol_names(self) -> tuple[str, ...]:
        return self._require_names(self._initial_protocol_names, "initial protocol")

    @property
    def cached_protocol_names(self) -> tuple[str, ...]:
        return self._require_names(self._cached_protocol_names, "cached protocol")

    @property
    def refreshed_protocol_names(self) -> tuple[str, ...]:
        return self._require_names(self._refreshed_protocol_names, "refreshed protocol")

    @property
    def initial_list_ordinal(self) -> int:
        return self._require_ordinal(self._initial_list_ordinal, "initial tool discovery")

    @property
    def removal_ordinal(self) -> int:
        return self._require_ordinal(self._removal_ordinal, "live target removal")

    @property
    def cached_list_ordinal(self) -> int:
        return self._require_ordinal(self._cached_list_ordinal, "post-removal cached discovery")

    @property
    def stale_call_ordinal(self) -> int:
        return self._require_ordinal(self._stale_call_ordinal, "stale target call")

    @property
    def cache_invalidation_ordinal(self) -> int:
        return self._require_ordinal(self._cache_invalidation_ordinal, "cache invalidation")

    @property
    def refreshed_list_ordinal(self) -> int:
        return self._require_ordinal(self._refreshed_list_ordinal, "refreshed discovery")

    async def list_tools(
        self,
        run_context: object | None = None,
        agent: object | None = None,
    ) -> list[Any]:
        tools = await self._original_list_tools(run_context, agent)
        names = tuple(getattr(tool, "name", None) for tool in tools)
        if _CONTROL_TOOL in names:
            self._control_leaked = True
        controlled = _controlled_names(tools, target_tool_name=self._fault.tool_name)

        if self._initial_protocol_names is None:
            self._initial_protocol_names = controlled
            self._initial_list_ordinal = self._mark()
        elif self._cache_invalidation_ordinal is not None:
            self._post_invalidation_lists += 1
            if self._refreshed_protocol_names is None:
                self._refreshed_protocol_names = controlled
                self._refreshed_list_ordinal = self._mark()
        return tools

    def observe_model_boundary(self, tools: list[Any], input_items: object) -> None:
        controlled = _controlled_names(tools, target_tool_name=self._fault.tool_name)
        if self._initial_model_names is None:
            self._initial_model_names = controlled
            return
        if self._refreshed_list_ordinal is None or self._refreshed_model_names is not None:
            return

        self._refreshed_model_names = controlled
        call_id, text = _extract_model_visible_stale_result(input_items)
        self._model_error_call_id = call_id
        self._model_error_text = text

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        meta: dict[str, Any] | None = None,
    ) -> object:
        if tool_name != self._fault.tool_name:
            return await _invoke_call_tool(self._original_call_tool, tool_name, arguments, meta)

        self._target_calls += 1
        if self._target_calls != 1:
            return await _invoke_call_tool(self._original_call_tool, tool_name, arguments, meta)

        control_result = await _invoke_call_tool(
            self._original_call_tool,
            _CONTROL_TOOL,
            {},
            None,
        )
        control_text = _single_text_or_none(control_result)
        self._control_failed = (
            _result_is_error(control_result) or control_text != _EXPECTED_CONTROL_RESULT
        )
        if not self._control_failed:
            self._removal_ordinal = self._mark()

        cached_tools = await self._original_list_tools()
        self._cached_protocol_names = _controlled_names(
            cached_tools,
            target_tool_name=self._fault.tool_name,
        )
        self._cached_list_ordinal = self._mark()

        self._stale_arguments = copy.deepcopy(arguments)
        result = await _invoke_call_tool(self._original_call_tool, tool_name, arguments, meta)
        self._stale_is_error = _result_is_error(result)
        self._stale_text = _single_text_or_none(result)
        self._stale_call_ordinal = self._mark()
        self._invalidate_tools_cache()
        self._cache_invalidation_ordinal = self._mark()
        return result

    def require_complete_relation(self) -> None:
        expected_initial = (self._fault.tool_name,)
        if self._control_leaked:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_control_tool_exposed",
                reason="evaluator-only removal control appeared in the agent-visible tool list",
            )
        if self._initial_protocol_names != expected_initial:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_initial_discovery_ambiguous",
                reason="initial MCP discovery did not expose exactly the controlled target",
            )
        if self._initial_model_names != expected_initial:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_initial_model_exposure_ambiguous",
                reason="initial model boundary did not expose exactly the controlled target",
            )
        if self._target_calls == 0:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_stale_call_missing",
                reason="agent did not invoke the controlled stale MCP target",
            )
        if self._target_calls != 1:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_extra_target_call",
                reason="agent made an extra controlled target request after stale-cache refresh",
            )
        if self._control_failed or self._removal_ordinal is None:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_removal_failed",
                reason="controlled MCP target was not removed exactly once before live lookup",
            )
        if self._cached_protocol_names != expected_initial:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_cached_discovery_mismatch",
                reason="post-removal cached discovery did not retain the controlled target",
            )
        if self._stale_is_error is not True or not self._stale_text:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_stale_call_not_rejected",
                reason="live MCP lookup did not reject the removed stale target",
            )
        if "unknown tool" not in self._stale_text.lower():
            raise AdapterPreconditionError(
                code="mcp_stale_cache_rejection_mismatch",
                reason="removed-target rejection did not establish an unknown-tool failure",
            )
        if self._post_invalidation_lists == 0 or self._refreshed_protocol_names != ():
            raise AdapterPreconditionError(
                code="mcp_stale_cache_refreshed_discovery_mismatch",
                reason="host refresh did not prove the controlled target absent",
            )
        if self._refreshed_model_names != ():
            raise AdapterPreconditionError(
                code="mcp_stale_cache_refreshed_model_exposure_mismatch",
                reason="post-refresh model boundary still exposed the controlled target",
            )
        if self._model_error_text != self._stale_text:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_model_rejection_mismatch",
                reason="post-refresh model boundary did not receive the exact MCP rejection",
            )

    def require_protocol_receipt(self) -> MCPFaultReceipt:
        try:
            return create_stale_cache_protocol_receipt(
                fault=self._fault,
                ttl_ms=self.ttl_ms,
                initial_tool_names=self.initial_protocol_names,
                cached_tool_names=self.cached_protocol_names,
                refreshed_tool_names=self.refreshed_protocol_names,
            )
        except ValueError as exc:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_protocol_relation_invalid",
                reason="observed MCP stale-cache relation does not match the controlled contract",
            ) from exc

    def _mark(self) -> int:
        value = self._ordinal
        self._ordinal += 1
        return value

    @staticmethod
    def _require_names(value: tuple[str, ...] | None, label: str) -> tuple[str, ...]:
        if value is None:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_observation_missing",
                reason=f"{label} controlled target set was not observed",
            )
        return value

    @staticmethod
    def _require_ordinal(value: int | None, label: str) -> int:
        if value is None:
            raise AdapterPreconditionError(
                code="mcp_stale_cache_protocol_chronology_incomplete",
                reason=f"MCP stale-cache chronology lacks {label}",
            )
        return value


def _attach_verified_stale_cache_bridge(
    result: AdapterResult,
    *,
    scenario: EvaluationScenario,
    fault: MCPFaultSpec,
    protocol_receipt: MCPFaultReceipt,
    recorder: _MCPToolStaleCacheRecorder,
) -> AdapterResult:
    requests = [
        event
        for event in result.events
        if event.kind is EvidenceKind.TOOL_REQUEST and event.payload.get("tool") == fault.tool_name
    ]
    if len(requests) != 1:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_agent_request_ambiguous",
            reason="normalized evidence does not contain exactly one controlled stale-target request",
        )
    request = requests[0]
    call_id = request.payload.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_agent_call_identity_missing",
            reason="normalized stale-target request has no stable OpenAI call identity",
        )
    if call_id != recorder.model_error_call_id:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_model_call_identity_mismatch",
            reason="post-refresh model-visible rejection is bound to a different OpenAI call ID",
        )

    normalized_arguments = _normalized_request_arguments(request)
    if normalized_arguments != recorder.stale_arguments:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_argument_provenance_mismatch",
            reason="normalized stale request arguments differ from the live MCP invocation",
        )

    matching_results = [
        event
        for event in result.events
        if event.kind is EvidenceKind.TOOL_RESULT and event.payload.get("call_id") == call_id
    ]
    if len(matching_results) != 1:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_agent_result_identity_ambiguous",
            reason="normalized evidence does not contain exactly one result for the stale call",
        )
    stale_result = matching_results[0]
    if request.sequence >= stale_result.sequence:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_agent_causality_unverified",
            reason="normalized stale result does not occur after its target request",
        )
    normalized_output = stale_result.payload.get("output")
    if _extract_normalized_text_output(normalized_output) != recorder.stale_protocol_text:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_normalized_rejection_mismatch",
            reason="normalized stale result differs from the live MCP rejection",
        )

    try:
        bridge = MCPAgentToolStaleCacheReceipt.create(
            scenario_identity=scenario.identity,
            fault=fault,
            protocol_receipt=protocol_receipt,
            tool_name=fault.tool_name,
            stale_call_id=call_id,
            ttl_ms=recorder.ttl_ms,
            stale_arguments=recorder.stale_arguments,
            stale_protocol_text=recorder.stale_protocol_text,
            agent_error_output=recorder.model_error_output,
            initial_model_tool_names=recorder.initial_model_names,
            refreshed_model_tool_names=recorder.refreshed_model_names,
            initial_list_ordinal=recorder.initial_list_ordinal,
            removal_ordinal=recorder.removal_ordinal,
            cached_list_ordinal=recorder.cached_list_ordinal,
            stale_call_ordinal=recorder.stale_call_ordinal,
            cache_invalidation_ordinal=recorder.cache_invalidation_ordinal,
            refreshed_list_ordinal=recorder.refreshed_list_ordinal,
        )
    except ValueError as exc:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_bridge_receipt_invalid",
            reason="stale-tool removal evidence does not match the verified MCP relation",
        ) from exc

    bridged_events: list[EvidenceEvent] = []
    inserted = False
    for event in result.events:
        bridged_events.append(event.model_copy(update={"sequence": len(bridged_events)}))
        if event is stale_result and not inserted:
            bridged_events.append(bridge.to_event(sequence=len(bridged_events)))
            inserted = True
    if not inserted:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_bridge_insertion_failed",
            reason="verified stale-cache delivery could not be ordered after stale result",
        )
    return replace(result, events=tuple(bridged_events))


def _clone_agent_with_controlled_server_and_observer(
    agent: object,
    *,
    server: object,
    target_tool_name: str,
    recorder: _MCPToolStaleCacheRecorder,
) -> Any:
    try:
        from agents import Agent
        from agents.models.interface import Model
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "install both the 'openai' and 'mcp' extras to use OpenAIAgentsMCPToolStaleCacheAdapter"
        ) from exc

    if not isinstance(agent, Agent):
        raise AdapterPreconditionError(
            code="unsupported_agent_type",
            reason="OpenAI MCP assurance requires an OpenAI Agents SDK Agent instance",
        )
    if agent.mcp_servers:
        raise AdapterPreconditionError(
            code="existing_mcp_servers_unsupported",
            reason="controlled MCP assurance requires a base agent with no preconfigured MCP servers",
        )
    if agent.mcp_config.get("include_server_in_tool_names", False):
        raise AdapterPreconditionError(
            code="prefixed_mcp_tool_names_unsupported",
            reason="controlled MCP assurance requires unprefixed MCP tool names",
        )
    collisions = {target_tool_name, _CONTROL_TOOL}
    if any(getattr(tool, "name", None) in collisions for tool in agent.tools):
        raise AdapterPreconditionError(
            code="mcp_stale_cache_tool_collision",
            reason="controlled MCP stale-cache identity conflicts with a local agent tool name",
        )
    if not isinstance(agent.model, Model):
        raise AdapterPreconditionError(
            code="mcp_stale_cache_concrete_model_required",
            reason=(
                "stale-cache assurance requires a concrete public SDK Model instance so exact "
                "target presence, target absence, and rejection delivery can be observed"
            ),
        )

    observed_model = _new_observed_model(agent.model, recorder)
    return agent.clone(mcp_servers=[server], model=observed_model)


def _new_observed_model(delegate: object, recorder: _MCPToolStaleCacheRecorder) -> object:
    try:
        from agents.models.interface import Model
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("install the 'openai' extra to use MCP stale-cache assurance") from exc

    if not isinstance(delegate, Model):
        raise AdapterPreconditionError(
            code="mcp_stale_cache_concrete_model_required",
            reason="stale-cache assurance requires a concrete public SDK Model instance",
        )
    delegated_model = cast(Any, delegate)

    async def get_response(
        self: object,
        system_instructions: Any,
        input: Any,
        model_settings: Any,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> Any:
        del self
        recorder.observe_model_boundary(tools, input)
        return await delegated_model.get_response(
            system_instructions,
            input,
            model_settings,
            tools,
            output_schema,
            handoffs,
            tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        )

    def stream_response(
        self: object,
        system_instructions: Any,
        input: Any,
        model_settings: Any,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: Any,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> Any:
        del self
        recorder.observe_model_boundary(tools, input)
        return delegated_model.stream_response(
            system_instructions,
            input,
            model_settings,
            tools,
            output_schema,
            handoffs,
            tracing,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            prompt=prompt,
        )

    async def cleanup_on_run_end(self: object, owner: object) -> None:
        del self
        method = getattr(delegated_model, "_cleanup_on_run_end", None)
        if method is not None:
            await method(owner)

    async def close(self: object) -> None:
        del self
        method = getattr(delegated_model, "close", None)
        if method is not None:
            await method()

    def get_retry_advice(self: object, request: Any) -> Any:
        del self
        method = getattr(delegated_model, "get_retry_advice", None)
        return None if method is None else method(request)

    observed_type = type(
        "_MCPStaleCacheObservedModel",
        (Model,),
        {
            "get_response": get_response,
            "stream_response": stream_response,
            "_cleanup_on_run_end": cleanup_on_run_end,
            "close": close,
            "get_retry_advice": get_retry_advice,
        },
    )
    return observed_type()


def _new_stdio_server(params: Mapping[str, object]) -> Any:
    try:
        from agents.mcp import MCPServerStdio
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "install both the 'openai' and 'mcp' extras to use OpenAIAgentsMCPToolStaleCacheAdapter"
        ) from exc

    return MCPServerStdio(
        params=copy.deepcopy(dict(params)),
        cache_tools_list=True,
        name="agent-evals-controlled-mcp-stale-cache",
        tool_filter={"blocked_tool_names": [_CONTROL_TOOL]},
    )


def _negotiated_protocol_version(server: object) -> str:
    session = getattr(server, "session", None)
    protocol_version = getattr(session, "protocol_version", None)
    if not isinstance(protocol_version, str) or not protocol_version:
        initialize_result = getattr(server, "server_initialize_result", None)
        protocol_version = getattr(initialize_result, "protocol_version", None)
    if not isinstance(protocol_version, str) or not protocol_version:
        raise AdapterPreconditionError(
            code="mcp_protocol_version_unavailable",
            reason="connected MCP session did not expose a negotiated protocol revision",
        )
    return protocol_version


async def _invoke_call_tool(
    call_tool: Callable[..., Awaitable[object]],
    tool_name: str,
    arguments: dict[str, Any] | None,
    meta: dict[str, Any] | None,
) -> object:
    if meta is None:
        return await call_tool(tool_name, arguments)
    return await call_tool(tool_name, arguments, meta=meta)


def _controlled_names(tools: list[Any], *, target_tool_name: str) -> tuple[str, ...]:
    names = [getattr(tool, "name", None) for tool in tools]
    selected = [name for name in names if isinstance(name, str) and name == target_tool_name]
    return tuple(sorted(selected))


def _extract_model_visible_stale_result(input_items: object) -> tuple[str, str]:
    if not isinstance(input_items, list):
        raise AdapterPreconditionError(
            code="mcp_stale_cache_model_input_unobservable",
            reason="post-refresh public Model input is not a concrete SDK input list",
        )
    outputs = [
        item
        for item in input_items
        if isinstance(item, dict) and item.get("type") == "function_call_output"
    ]
    if len(outputs) != 1:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_model_rejection_ambiguous",
            reason="post-refresh model input does not contain exactly one stale-call output",
        )
    call_id = outputs[0].get("call_id")
    output = outputs[0].get("output")
    if not isinstance(call_id, str) or not call_id:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_model_call_identity_missing",
            reason="post-refresh model input lacks a stable stale-call identity",
        )
    if not isinstance(output, list) or len(output) != 1:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_model_rejection_ambiguous",
            reason="post-refresh model input does not contain one exact rejection output",
        )
    item = output[0]
    if not isinstance(item, dict) or item.get("type") != "input_text":
        raise AdapterPreconditionError(
            code="mcp_stale_cache_model_rejection_ambiguous",
            reason="post-refresh stale-call output is not one public SDK input_text item",
        )
    text = item.get("text")
    if not isinstance(text, str) or not text:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_model_rejection_ambiguous",
            reason="post-refresh stale-call output has no exact text payload",
        )
    return call_id, text


def _normalized_request_arguments(event: EvidenceEvent) -> dict[str, Any]:
    arguments = event.payload.get("arguments")
    if not isinstance(arguments, str) or not arguments:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_agent_arguments_missing",
            reason="normalized stale-cache request lacks serialized arguments",
        )

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    try:
        parsed = json.loads(
            arguments,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_agent_arguments_invalid",
            reason="normalized stale-cache request arguments are not strict finite JSON",
        ) from exc
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise AdapterPreconditionError(
            code="mcp_stale_cache_agent_arguments_invalid",
            reason="normalized stale-cache request arguments are not a string-keyed object",
        )
    if _contains_non_finite_json(parsed):
        raise AdapterPreconditionError(
            code="mcp_stale_cache_agent_arguments_invalid",
            reason="normalized stale-cache request arguments contain non-finite numbers",
        )
    return parsed


def _extract_normalized_text_output(value: object) -> str:
    if not isinstance(value, Mapping) or set(value) != {"type", "text"}:
        raise AdapterPreconditionError(
            code="mcp_stale_cache_normalized_rejection_ambiguous",
            reason="normalized stale result is not one exact text output object",
        )
    text = value.get("text")
    if value.get("type") != "text" or not isinstance(text, str):
        raise AdapterPreconditionError(
            code="mcp_stale_cache_normalized_rejection_ambiguous",
            reason="normalized stale result is not one exact text output object",
        )
    return text


def _contains_non_finite_json(value: object) -> bool:
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, list):
        return any(_contains_non_finite_json(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_non_finite_json(item) for item in value.values())
    return False


def _result_is_error(result: object) -> bool:
    return bool(getattr(result, "is_error", False)) or bool(getattr(result, "isError", False))


def _single_text_or_none(result: object) -> str | None:
    content = getattr(result, "content", None)
    if not isinstance(content, list) or len(content) != 1:
        return None
    item = content[0]
    if getattr(item, "type", None) != "text":
        return None
    text = getattr(item, "text", None)
    return text if isinstance(text, str) else None


def _validated_stdio_params(value: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("stdio_params must be a mapping")
    if any(not isinstance(key, str) for key in value):
        raise TypeError("stdio_params keys must be strings")

    params = copy.deepcopy(dict(value))
    command = params.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("stdio_params.command must be a non-empty string")

    args = params.get("args")
    if args is not None and (
        not isinstance(args, list) or any(not isinstance(item, str) for item in args)
    ):
        raise TypeError("stdio_params.args must be a list of strings")

    env = params.get("env")
    if env is not None and (
        not isinstance(env, dict)
        or any(not isinstance(key, str) or not isinstance(item, str) for key, item in env.items())
    ):
        raise TypeError("stdio_params.env must map strings to strings")

    allowed = {"command", "args", "env", "cwd", "encoding", "encoding_error_handler"}
    unknown = sorted(set(params).difference(allowed))
    if unknown:
        raise ValueError(f"stdio_params contains unsupported keys: {', '.join(unknown)}")
    return params
