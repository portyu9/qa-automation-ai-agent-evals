"""OpenAI Agents SDK adapter for verified host-refreshed MCP tool-identity adaptation."""

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
from agent_evals.mcp.agent_identity_bridge import (
    MCPAgentToolIdentityDriftReceipt,
    create_identity_drift_protocol_receipt,
)
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_REQUIRED_PROTOCOL_VERSION = "2026-07-28"
_CONTROL_TOOL = "__agent_evals_identity_swap__"
_EXPECTED_CONTROL_RESULT = "identity-swapped"
_EXPECTED_RECOVERY_TEXT = "replacement:fresh"


class OpenAIAgentsMCPToolIdentityDriftAdapter:
    """Evaluate one host-refreshed live MCP rename and exact agent identity adaptation.

    The controlled harness owns the live registry mutation and this adapter owns one cache
    invalidation. The model is credited only for switching to the replacement tool after that exact
    identity becomes visible through the public SDK Model boundary.
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
        if fault.kind is not MCPFaultKind.TOOL_IDENTITY_DRIFT:
            raise ValueError(
                "OpenAI MCP identity-drift bridge requires a TOOL_IDENTITY_DRIFT fault"
            )
        replacement = _replacement_tool_name(fault)
        if _CONTROL_TOOL in {fault.tool_name, replacement}:
            raise ValueError(
                "MCP identity-drift target must not collide with evaluator control tool"
            )
        self._agent = agent
        self._stdio_params = _validated_stdio_params(stdio_params)
        self._fault = fault
        self._replacement_tool_name = replacement
        self._state_reader = state_reader
        self._resource_resolver = resource_resolver
        self._run_context = run_context
        self._tracing_disabled = tracing_disabled

    @property
    def name(self) -> str:
        return "openai-agents-mcp-tool-identity-drift"

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

            recorder = _MCPToolIdentityDriftRecorder(
                original_list_tools=server.list_tools,
                original_call_tool=server.call_tool,
                invalidate_tools_cache=server.invalidate_tools_cache,
                fault=self._fault,
                protocol_version=protocol_version,
                replacement_tool_name=self._replacement_tool_name,
            )
            server.list_tools = recorder.list_tools
            server.call_tool = recorder.call_tool
            runner_agent = _clone_agent_with_controlled_server_and_observer(
                self._agent,
                server=server,
                original_tool_name=self._fault.tool_name,
                replacement_tool_name=self._replacement_tool_name,
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
            return _attach_verified_identity_bridge(
                delegated,
                scenario=scenario,
                fault=self._fault,
                replacement_tool_name=self._replacement_tool_name,
                protocol_receipt=protocol_receipt,
                recorder=recorder,
            )
        finally:
            await server.cleanup()


class _MCPToolIdentityDriftRecorder:
    """Record one old-name rejection, host refresh, model exposure, and replacement call."""

    def __init__(
        self,
        *,
        original_list_tools: Callable[..., Awaitable[list[Any]]],
        original_call_tool: Callable[..., Awaitable[object]],
        invalidate_tools_cache: Callable[[], None],
        fault: MCPFaultSpec,
        protocol_version: str,
        replacement_tool_name: str,
    ) -> None:
        self._original_list_tools = original_list_tools
        self._original_call_tool = original_call_tool
        self._invalidate_tools_cache = invalidate_tools_cache
        self._fault = fault
        self._protocol_version = protocol_version
        self._replacement_tool_name = replacement_tool_name
        self._ordinal = 0
        self._target_calls = 0
        self._post_invalidation_lists = 0
        self._control_failed = False
        self._control_leaked = False
        self._recovery_before_refresh = False
        self._initial_protocol_names: tuple[str, ...] | None = None
        self._cached_protocol_names: tuple[str, ...] | None = None
        self._refreshed_protocol_names: tuple[str, ...] | None = None
        self._initial_model_names: tuple[str, ...] | None = None
        self._refreshed_model_names: tuple[str, ...] | None = None
        self._first_tool_name: str | None = None
        self._recovery_tool_name: str | None = None
        self._stale_arguments: dict[str, Any] | None = None
        self._recovery_arguments: dict[str, Any] | None = None
        self._stale_text: str | None = None
        self._stale_is_error: bool | None = None
        self._recovery_text: str | None = None
        self._recovery_is_error: bool | None = None
        self._initial_list_ordinal: int | None = None
        self._identity_swap_ordinal: int | None = None
        self._cached_list_ordinal: int | None = None
        self._stale_call_ordinal: int | None = None
        self._cache_invalidation_ordinal: int | None = None
        self._refreshed_list_ordinal: int | None = None
        self._recovery_call_ordinal: int | None = None

    @property
    def mcp_cache_hint_ttl_ms(self) -> int:
        payload = self._fault.payload
        if not isinstance(payload, dict):
            raise AdapterPreconditionError(
                code="mcp_identity_fault_payload_invalid",
                reason="identity-drift fault payload is not an object",
            )
        ttl_ms = payload.get("ttl_ms")
        if isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int) or ttl_ms <= 0:
            raise AdapterPreconditionError(
                code="mcp_identity_fault_payload_invalid",
                reason="identity-drift MCP cache-hint TTL is not a positive integer",
            )
        return ttl_ms

    @property
    def stale_arguments(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._stale_arguments)

    @property
    def recovery_arguments(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._recovery_arguments)

    @property
    def stale_protocol_text(self) -> str:
        if self._stale_text is None:
            raise AdapterPreconditionError(
                code="mcp_identity_stale_rejection_missing",
                reason="old-name MCP call did not yield a model-visible rejection",
            )
        return self._stale_text

    @property
    def protocol_recovery_text(self) -> str:
        if self._recovery_text is None:
            raise AdapterPreconditionError(
                code="mcp_identity_recovery_missing",
                reason="replacement-name MCP call did not yield a recovery result",
            )
        return self._recovery_text

    @property
    def initial_model_names(self) -> tuple[str, ...]:
        return self._require_names(self._initial_model_names, "initial model-visible")

    @property
    def refreshed_model_names(self) -> tuple[str, ...]:
        return self._require_names(self._refreshed_model_names, "refreshed model-visible")

    @property
    def initial_list_ordinal(self) -> int:
        return self._require_ordinal(self._initial_list_ordinal, "initial tool discovery")

    @property
    def identity_swap_ordinal(self) -> int:
        return self._require_ordinal(self._identity_swap_ordinal, "identity swap")

    @property
    def cached_list_ordinal(self) -> int:
        return self._require_ordinal(self._cached_list_ordinal, "post-swap cached discovery")

    @property
    def stale_call_ordinal(self) -> int:
        return self._require_ordinal(self._stale_call_ordinal, "stale old-name call")

    @property
    def cache_invalidation_ordinal(self) -> int:
        return self._require_ordinal(self._cache_invalidation_ordinal, "cache invalidation")

    @property
    def refreshed_list_ordinal(self) -> int:
        return self._require_ordinal(self._refreshed_list_ordinal, "refreshed discovery")

    @property
    def recovery_call_ordinal(self) -> int:
        return self._require_ordinal(self._recovery_call_ordinal, "replacement call")

    async def list_tools(
        self,
        run_context: object | None = None,
        agent: object | None = None,
    ) -> list[Any]:
        tools = await self._original_list_tools(run_context, agent)
        names = tuple(getattr(tool, "name", None) for tool in tools)
        if _CONTROL_TOOL in names:
            self._control_leaked = True
        controlled = _controlled_names(
            tools,
            original_tool_name=self._fault.tool_name,
            replacement_tool_name=self._replacement_tool_name,
        )

        if self._initial_protocol_names is None:
            self._initial_protocol_names = controlled
            self._initial_list_ordinal = self._mark()
        elif self._cache_invalidation_ordinal is not None and self._recovery_call_ordinal is None:
            self._post_invalidation_lists += 1
            if self._refreshed_protocol_names is None:
                self._refreshed_protocol_names = controlled
                self._refreshed_list_ordinal = self._mark()
        return tools

    def observe_model_tools(self, tools: list[Any]) -> None:
        controlled = _controlled_names(
            tools,
            original_tool_name=self._fault.tool_name,
            replacement_tool_name=self._replacement_tool_name,
        )
        if self._initial_model_names is None:
            self._initial_model_names = controlled
            return
        if self._refreshed_list_ordinal is not None and self._refreshed_model_names is None:
            self._refreshed_model_names = controlled

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        meta: dict[str, Any] | None = None,
    ) -> object:
        controlled_names = {self._fault.tool_name, self._replacement_tool_name}
        if tool_name not in controlled_names:
            return await _invoke_call_tool(self._original_call_tool, tool_name, arguments, meta)

        self._target_calls += 1
        if self._target_calls == 1:
            self._first_tool_name = tool_name
            if tool_name != self._fault.tool_name:
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
                self._identity_swap_ordinal = self._mark()
                cached_tools = await self._original_list_tools()
                self._cached_protocol_names = _controlled_names(
                    cached_tools,
                    original_tool_name=self._fault.tool_name,
                    replacement_tool_name=self._replacement_tool_name,
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

        if self._target_calls == 2:
            self._recovery_tool_name = tool_name
            if self._refreshed_list_ordinal is None:
                self._recovery_before_refresh = True
            self._recovery_arguments = copy.deepcopy(arguments)
            result = await _invoke_call_tool(self._original_call_tool, tool_name, arguments, meta)
            self._recovery_is_error = _result_is_error(result)
            self._recovery_text = _single_text_or_none(result)
            self._recovery_call_ordinal = self._mark()
            return result

        return await _invoke_call_tool(self._original_call_tool, tool_name, arguments, meta)

    def require_complete_relation(self) -> None:
        expected_initial = (self._fault.tool_name,)
        expected_replacement = (self._replacement_tool_name,)
        if self._control_leaked:
            raise AdapterPreconditionError(
                code="mcp_identity_control_tool_exposed",
                reason="evaluator-only identity control appeared in the agent-visible tool list",
            )
        if self._initial_protocol_names != expected_initial:
            raise AdapterPreconditionError(
                code="mcp_identity_initial_discovery_ambiguous",
                reason="initial MCP discovery did not expose exactly the controlled original identity",
            )
        if self._initial_model_names != expected_initial:
            raise AdapterPreconditionError(
                code="mcp_identity_initial_model_exposure_ambiguous",
                reason="initial model boundary did not expose exactly the controlled original identity",
            )
        if self._target_calls == 0:
            raise AdapterPreconditionError(
                code="mcp_identity_stale_call_missing",
                reason="agent did not invoke the controlled original MCP tool identity",
            )
        if self._first_tool_name != self._fault.tool_name:
            raise AdapterPreconditionError(
                code="mcp_identity_stale_call_identity_mismatch",
                reason="first controlled call did not use the original MCP tool identity",
            )
        if self._control_failed or self._identity_swap_ordinal is None:
            raise AdapterPreconditionError(
                code="mcp_identity_swap_failed",
                reason="controlled MCP target identity was not replaced exactly once",
            )
        if self._cached_protocol_names != expected_initial:
            raise AdapterPreconditionError(
                code="mcp_identity_cached_discovery_mismatch",
                reason="host cache did not preserve the original identity after live replacement",
            )
        if self._stale_is_error is not True or not self._stale_text:
            raise AdapterPreconditionError(
                code="mcp_identity_stale_call_not_rejected",
                reason="live MCP lookup did not reject the removed original tool identity",
            )
        if "unknown tool" not in self._stale_text.lower():
            raise AdapterPreconditionError(
                code="mcp_identity_stale_rejection_mismatch",
                reason="old-name rejection did not establish an unknown-tool identity failure",
            )
        if self._target_calls == 1:
            raise AdapterPreconditionError(
                code="mcp_identity_recovery_call_missing",
                reason="agent did not issue a call under the replacement MCP identity",
            )
        if self._target_calls != 2:
            raise AdapterPreconditionError(
                code="mcp_identity_recovery_call_ambiguous",
                reason="agent made more than one recovery attempt across the controlled identities",
            )
        if self._recovery_before_refresh:
            raise AdapterPreconditionError(
                code="mcp_identity_recovery_before_refresh",
                reason="replacement call occurred before refreshed identity discovery",
            )
        if (
            self._post_invalidation_lists == 0
            or self._refreshed_protocol_names != expected_replacement
        ):
            raise AdapterPreconditionError(
                code="mcp_identity_refreshed_discovery_mismatch",
                reason="host refresh did not expose exactly the replacement MCP identity",
            )
        if self._refreshed_model_names != expected_replacement:
            raise AdapterPreconditionError(
                code="mcp_identity_refreshed_model_exposure_mismatch",
                reason="recovery model boundary did not expose exactly the replacement identity",
            )
        if self._recovery_tool_name != self._replacement_tool_name:
            raise AdapterPreconditionError(
                code="mcp_identity_recovery_name_mismatch",
                reason="agent recovery call did not use the refreshed replacement tool identity",
            )
        if self._recovery_is_error is not False or self._recovery_text != _EXPECTED_RECOVERY_TEXT:
            raise AdapterPreconditionError(
                code="mcp_identity_recovery_result_mismatch",
                reason="replacement identity call did not produce the bound deterministic result",
            )

    def require_protocol_receipt(self) -> MCPFaultReceipt:
        try:
            return create_identity_drift_protocol_receipt(
                fault=self._fault,
                ttl_ms=self.mcp_cache_hint_ttl_ms,
                original_tool_name=self._fault.tool_name,
                replacement_tool_name=self._replacement_tool_name,
                stale_protocol_text=self.stale_protocol_text,
                protocol_recovery_text=self.protocol_recovery_text,
                initial_list_ordinal=self.initial_list_ordinal,
                identity_swap_ordinal=self.identity_swap_ordinal,
                cached_list_ordinal=self.cached_list_ordinal,
                stale_call_ordinal=self.stale_call_ordinal,
                cache_invalidation_ordinal=self.cache_invalidation_ordinal,
                refreshed_list_ordinal=self.refreshed_list_ordinal,
                recovery_call_ordinal=self.recovery_call_ordinal,
            )
        except ValueError as exc:
            raise AdapterPreconditionError(
                code="mcp_identity_protocol_relation_invalid",
                reason="observed MCP identity-drift relation does not match the controlled contract",
            ) from exc

    def _mark(self) -> int:
        value = self._ordinal
        self._ordinal += 1
        return value

    @staticmethod
    def _require_names(value: tuple[str, ...] | None, label: str) -> tuple[str, ...]:
        if value is None:
            raise AdapterPreconditionError(
                code="mcp_identity_model_exposure_missing",
                reason=f"{label} controlled identity set was not observed",
            )
        return value

    @staticmethod
    def _require_ordinal(value: int | None, label: str) -> int:
        if value is None:
            raise AdapterPreconditionError(
                code="mcp_identity_protocol_chronology_incomplete",
                reason=f"MCP identity-drift chronology lacks {label}",
            )
        return value


def _attach_verified_identity_bridge(
    result: AdapterResult,
    *,
    scenario: EvaluationScenario,
    fault: MCPFaultSpec,
    replacement_tool_name: str,
    protocol_receipt: MCPFaultReceipt,
    recorder: _MCPToolIdentityDriftRecorder,
) -> AdapterResult:
    controlled_names = {fault.tool_name, replacement_tool_name}
    requests = [
        event
        for event in result.events
        if event.kind is EvidenceKind.TOOL_REQUEST and event.payload.get("tool") in controlled_names
    ]
    if len(requests) != 2:
        raise AdapterPreconditionError(
            code="mcp_identity_agent_request_identity_ambiguous",
            reason="normalized evidence does not contain exactly two controlled identity requests",
        )
    if requests[0].payload.get("tool") != fault.tool_name:
        raise AdapterPreconditionError(
            code="mcp_identity_agent_stale_name_mismatch",
            reason="first normalized controlled request does not use the original tool identity",
        )
    if requests[1].payload.get("tool") != replacement_tool_name:
        raise AdapterPreconditionError(
            code="mcp_identity_agent_recovery_name_mismatch",
            reason="second normalized controlled request does not use the replacement identity",
        )

    call_ids: list[str] = []
    for event in requests:
        call_id = event.payload.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            raise AdapterPreconditionError(
                code="mcp_identity_agent_call_identity_missing",
                reason="normalized identity-drift request has no stable agent call identity",
            )
        call_ids.append(call_id)
    if call_ids[0] == call_ids[1]:
        raise AdapterPreconditionError(
            code="mcp_identity_agent_call_identity_reused",
            reason="old-name and replacement calls reused the same OpenAI call identity",
        )

    normalized_stale_arguments = _normalized_request_arguments(requests[0])
    normalized_recovery_arguments = _normalized_request_arguments(requests[1])
    if normalized_stale_arguments != recorder.stale_arguments:
        raise AdapterPreconditionError(
            code="mcp_identity_stale_argument_provenance_mismatch",
            reason="normalized old-name request arguments differ from the live MCP invocation",
        )
    if normalized_recovery_arguments != recorder.recovery_arguments:
        raise AdapterPreconditionError(
            code="mcp_identity_recovery_argument_provenance_mismatch",
            reason="normalized replacement request arguments differ from the live MCP invocation",
        )

    results: list[EvidenceEvent] = []
    for call_id in call_ids:
        matching = [
            event
            for event in result.events
            if event.kind is EvidenceKind.TOOL_RESULT and event.payload.get("call_id") == call_id
        ]
        if len(matching) != 1:
            raise AdapterPreconditionError(
                code="mcp_identity_agent_result_identity_ambiguous",
                reason="normalized evidence does not contain one result per identity-drift call",
            )
        results.append(matching[0])

    if not (
        requests[0].sequence < results[0].sequence < requests[1].sequence < results[1].sequence
    ):
        raise AdapterPreconditionError(
            code="mcp_identity_agent_adaptation_causality_unverified",
            reason=(
                "normalized evidence does not prove replacement identity use only after the "
                "old-name rejection became model-visible"
            ),
        )

    try:
        bridge = MCPAgentToolIdentityDriftReceipt.create(
            scenario_identity=scenario.identity,
            fault=fault,
            protocol_receipt=protocol_receipt,
            original_tool_name=fault.tool_name,
            replacement_tool_name=replacement_tool_name,
            stale_call_id=call_ids[0],
            recovery_call_id=call_ids[1],
            mcp_cache_hint_ttl_ms=recorder.mcp_cache_hint_ttl_ms,
            stale_arguments=recorder.stale_arguments,
            recovery_arguments=recorder.recovery_arguments,
            stale_protocol_text=recorder.stale_protocol_text,
            agent_error_output=results[0].payload.get("output"),
            protocol_recovery_text=recorder.protocol_recovery_text,
            agent_recovery_output=results[1].payload.get("output"),
            initial_model_tool_names=recorder.initial_model_names,
            refreshed_model_tool_names=recorder.refreshed_model_names,
            initial_list_ordinal=recorder.initial_list_ordinal,
            identity_swap_ordinal=recorder.identity_swap_ordinal,
            cached_list_ordinal=recorder.cached_list_ordinal,
            stale_call_ordinal=recorder.stale_call_ordinal,
            cache_invalidation_ordinal=recorder.cache_invalidation_ordinal,
            refreshed_list_ordinal=recorder.refreshed_list_ordinal,
            recovery_call_ordinal=recorder.recovery_call_ordinal,
        )
    except ValueError as exc:
        raise AdapterPreconditionError(
            code="mcp_identity_bridge_receipt_invalid",
            reason="agent identity-adaptation evidence does not match the verified MCP relation",
        ) from exc

    bridged_events: list[EvidenceEvent] = []
    inserted = False
    for event in result.events:
        bridged_events.append(event.model_copy(update={"sequence": len(bridged_events)}))
        if event is results[1] and not inserted:
            bridged_events.append(bridge.to_event(sequence=len(bridged_events)))
            inserted = True
    if not inserted:
        raise AdapterPreconditionError(
            code="mcp_identity_bridge_insertion_failed",
            reason="verified MCP identity adaptation could not be ordered after recovery result",
        )
    return replace(result, events=tuple(bridged_events))


def _clone_agent_with_controlled_server_and_observer(
    agent: object,
    *,
    server: object,
    original_tool_name: str,
    replacement_tool_name: str,
    recorder: _MCPToolIdentityDriftRecorder,
) -> Any:
    try:
        from agents import Agent
        from agents.models.interface import Model
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "install both the 'openai' and 'mcp' extras to use "
            "OpenAIAgentsMCPToolIdentityDriftAdapter"
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
    collisions = {original_tool_name, replacement_tool_name, _CONTROL_TOOL}
    if any(getattr(tool, "name", None) in collisions for tool in agent.tools):
        raise AdapterPreconditionError(
            code="mcp_identity_tool_collision",
            reason="controlled MCP identity conflicts with an existing local agent tool name",
        )
    if not isinstance(agent.model, Model):
        raise AdapterPreconditionError(
            code="mcp_identity_concrete_model_required",
            reason=(
                "identity-drift assurance requires a concrete public SDK Model instance so exact "
                "old and replacement model-visible tool identities can be observed"
            ),
        )

    observed_model = _new_observed_model(agent.model, recorder)
    return agent.clone(mcp_servers=[server], model=observed_model)


def _new_observed_model(delegate: object, recorder: _MCPToolIdentityDriftRecorder) -> object:
    try:
        from agents.models.interface import Model
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "install the 'openai' extra to use MCP identity-drift assurance"
        ) from exc

    if not isinstance(delegate, Model):
        raise AdapterPreconditionError(
            code="mcp_identity_concrete_model_required",
            reason="identity-drift assurance requires a concrete public SDK Model instance",
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
        recorder.observe_model_tools(tools)
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
        recorder.observe_model_tools(tools)
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
        "_MCPIdentityDriftObservedModel",
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
            "install both the 'openai' and 'mcp' extras to use "
            "OpenAIAgentsMCPToolIdentityDriftAdapter"
        ) from exc

    return MCPServerStdio(
        params=copy.deepcopy(dict(params)),
        cache_tools_list=True,
        name="agent-evals-controlled-mcp-identity-drift",
        tool_filter={"blocked_tool_names": [_CONTROL_TOOL]},
    )


def _replacement_tool_name(fault: MCPFaultSpec) -> str:
    payload = fault.payload
    if not isinstance(payload, dict):
        raise ValueError("MCP identity-drift fault payload must be an object")
    replacement = payload.get("replacement_tool_name")
    if not isinstance(replacement, str) or not replacement.strip():
        raise ValueError("MCP identity-drift replacement tool name must be a non-empty string")
    return replacement


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


def _controlled_names(
    tools: list[Any],
    *,
    original_tool_name: str,
    replacement_tool_name: str,
) -> tuple[str, ...]:
    controlled = {original_tool_name, replacement_tool_name}
    names = [getattr(tool, "name", None) for tool in tools]
    selected = [name for name in names if isinstance(name, str) and name in controlled]
    return tuple(sorted(selected))


def _normalized_request_arguments(event: EvidenceEvent) -> dict[str, Any]:
    arguments = event.payload.get("arguments")
    if not isinstance(arguments, str) or not arguments:
        raise AdapterPreconditionError(
            code="mcp_identity_agent_arguments_missing",
            reason="normalized identity-drift request lacks serialized arguments",
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
            code="mcp_identity_agent_arguments_invalid",
            reason="normalized identity-drift request arguments are not strict finite JSON",
        ) from exc
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise AdapterPreconditionError(
            code="mcp_identity_agent_arguments_invalid",
            reason="normalized identity-drift request arguments are not a string-keyed object",
        )
    if _contains_non_finite_json(parsed):
        raise AdapterPreconditionError(
            code="mcp_identity_agent_arguments_invalid",
            reason="normalized identity-drift request arguments contain non-finite numbers",
        )
    return parsed


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
