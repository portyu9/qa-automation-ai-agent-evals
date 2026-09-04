"""OpenAI Agents SDK adapter for verified host-refreshed MCP schema-drift adaptation."""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult
from agent_evals.adapters.openai_agents import OpenAIAgentsAdapter, ResourceResolver, StateReader
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.mcp.agent_schema_bridge import (
    MCPAgentToolSchemaDriftReceipt,
    create_schema_drift_protocol_receipt,
    schema_projection,
)
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_REQUIRED_PROTOCOL_VERSION = "2026-07-28"
_CONTROL_TOOL = "__agent_evals_schema_swap__"
_EXPECTED_CONTROL_RESULT = "schema-swapped"
_EXPECTED_RECOVERY_TEXT = "replacement:7:true"


class OpenAIAgentsMCPToolSchemaDriftAdapter:
    """Evaluate one host-refreshed live MCP schema migration and agent adaptation.

    The model is credited only for changing its second target call after the Agents SDK has been
    given the refreshed v2 tool contract. The controlled harness owns the live server swap and this
    adapter owns the one cache invalidation that permits the next SDK turn to re-list tools.
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
        if fault.kind is not MCPFaultKind.TOOL_SCHEMA_DRIFT:
            raise ValueError("OpenAI MCP schema-drift bridge requires a TOOL_SCHEMA_DRIFT fault")
        if fault.tool_name == _CONTROL_TOOL:
            raise ValueError("MCP schema-drift target must not collide with evaluator control tool")
        self._agent = agent
        self._stdio_params = _validated_stdio_params(stdio_params)
        self._fault = fault
        self._state_reader = state_reader
        self._resource_resolver = resource_resolver
        self._run_context = run_context
        self._tracing_disabled = tracing_disabled

    @property
    def name(self) -> str:
        return "openai-agents-mcp-tool-schema-drift"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        server = _new_stdio_server(self._stdio_params)
        runner_agent = _clone_agent_with_controlled_server(
            self._agent,
            server=server,
            target_tool=self._fault.tool_name,
        )

        await server.connect()
        try:
            protocol_version = _negotiated_protocol_version(server)
            if protocol_version != _REQUIRED_PROTOCOL_VERSION:
                raise AdapterPreconditionError(
                    code="mcp_protocol_version_mismatch",
                    reason="connected MCP session did not negotiate the required protocol revision",
                )

            recorder = _MCPToolSchemaDriftRecorder(
                original_list_tools=server.list_tools,
                original_call_tool=server.call_tool,
                invalidate_tools_cache=server.invalidate_tools_cache,
                fault=self._fault,
                protocol_version=protocol_version,
            )
            server.list_tools = recorder.list_tools
            server.call_tool = recorder.call_tool

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
            return _attach_verified_schema_bridge(
                delegated,
                scenario=scenario,
                fault=self._fault,
                protocol_receipt=protocol_receipt,
                recorder=recorder,
            )
        finally:
            await server.cleanup()


class _MCPToolSchemaDriftRecorder:
    """Per-trial recorder for one hidden schema swap and one host-refreshed recovery."""

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
        self._recovery_before_refresh = False
        self._initial_schema: dict[str, object] | None = None
        self._cached_schema: dict[str, object] | None = None
        self._refreshed_schema: dict[str, object] | None = None
        self._stale_arguments: dict[str, Any] | None = None
        self._recovery_arguments: dict[str, Any] | None = None
        self._stale_text: str | None = None
        self._stale_is_error: bool | None = None
        self._recovery_text: str | None = None
        self._recovery_is_error: bool | None = None
        self._initial_list_ordinal: int | None = None
        self._schema_swap_ordinal: int | None = None
        self._stale_call_ordinal: int | None = None
        self._cache_invalidation_ordinal: int | None = None
        self._refreshed_list_ordinal: int | None = None
        self._recovery_call_ordinal: int | None = None

    @property
    def initial_schema(self) -> dict[str, object]:
        return copy.deepcopy(self._require_schema(self._initial_schema, "initial"))

    @property
    def cached_schema(self) -> dict[str, object]:
        return copy.deepcopy(self._require_schema(self._cached_schema, "cached"))

    @property
    def refreshed_schema(self) -> dict[str, object]:
        return copy.deepcopy(self._require_schema(self._refreshed_schema, "refreshed"))

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
                code="mcp_schema_stale_rejection_missing",
                reason="stale MCP schema call did not yield a model-visible rejection",
            )
        return self._stale_text

    @property
    def protocol_recovery_text(self) -> str:
        if self._recovery_text is None:
            raise AdapterPreconditionError(
                code="mcp_schema_recovery_missing",
                reason="corrected MCP schema call did not yield a recovery result",
            )
        return self._recovery_text

    @property
    def ttl_ms(self) -> int:
        payload = self._fault.payload
        if not isinstance(payload, dict):
            raise AdapterPreconditionError(
                code="mcp_schema_fault_payload_invalid",
                reason="schema-drift fault payload is not an object",
            )
        ttl_ms = payload.get("ttl_ms")
        if isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int) or ttl_ms <= 0:
            raise AdapterPreconditionError(
                code="mcp_schema_fault_payload_invalid",
                reason="schema-drift fault TTL is not a positive integer",
            )
        return ttl_ms

    @property
    def initial_list_ordinal(self) -> int:
        return self._require_ordinal(self._initial_list_ordinal, "initial tool discovery")

    @property
    def schema_swap_ordinal(self) -> int:
        return self._require_ordinal(self._schema_swap_ordinal, "schema swap")

    @property
    def stale_call_ordinal(self) -> int:
        return self._require_ordinal(self._stale_call_ordinal, "stale call")

    @property
    def cache_invalidation_ordinal(self) -> int:
        return self._require_ordinal(self._cache_invalidation_ordinal, "cache invalidation")

    @property
    def refreshed_list_ordinal(self) -> int:
        return self._require_ordinal(self._refreshed_list_ordinal, "refreshed tool discovery")

    @property
    def recovery_call_ordinal(self) -> int:
        return self._require_ordinal(self._recovery_call_ordinal, "recovery call")

    async def list_tools(
        self,
        run_context: object | None = None,
        agent: object | None = None,
    ) -> list[Any]:
        tools = await self._original_list_tools(run_context, agent)
        names = tuple(getattr(tool, "name", None) for tool in tools)
        if _CONTROL_TOOL in names:
            self._control_leaked = True
        target_schema = _exact_target_schema(tools, self._fault.tool_name)

        if self._initial_schema is None:
            self._initial_schema = target_schema
            self._initial_list_ordinal = self._mark()
        elif self._cache_invalidation_ordinal is not None and self._recovery_call_ordinal is None:
            self._post_invalidation_lists += 1
            if self._refreshed_schema is None:
                self._refreshed_schema = target_schema
                self._refreshed_list_ordinal = self._mark()
        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        meta: dict[str, Any] | None = None,
    ) -> object:
        if tool_name != self._fault.tool_name:
            return await _invoke_call_tool(self._original_call_tool, tool_name, arguments, meta)

        self._target_calls += 1
        if self._target_calls == 1:
            cached_tools = await self._original_list_tools()
            self._cached_schema = _exact_target_schema(cached_tools, self._fault.tool_name)

            control_result = await _invoke_call_tool(
                self._original_call_tool,
                _CONTROL_TOOL,
                {},
                None,
            )
            control_text = _single_text_or_none(control_result)
            self._control_failed = _result_is_error(control_result) or control_text != _EXPECTED_CONTROL_RESULT
            if not self._control_failed:
                self._schema_swap_ordinal = self._mark()

            self._stale_arguments = copy.deepcopy(arguments)
            result = await _invoke_call_tool(self._original_call_tool, tool_name, arguments, meta)
            self._stale_is_error = _result_is_error(result)
            self._stale_text = _single_text_or_none(result)
            self._stale_call_ordinal = self._mark()
            self._invalidate_tools_cache()
            self._cache_invalidation_ordinal = self._mark()
            return result

        if self._target_calls == 2:
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
        if self._control_leaked:
            raise AdapterPreconditionError(
                code="mcp_schema_control_tool_exposed",
                reason="evaluator-only schema control appeared in the agent-visible tool list",
            )
        if self._initial_schema is None:
            raise AdapterPreconditionError(
                code="mcp_schema_initial_discovery_missing",
                reason="agent run did not observe the initial MCP target schema",
            )
        if self._target_calls == 0:
            raise AdapterPreconditionError(
                code="mcp_schema_target_call_missing",
                reason="agent did not invoke the controlled MCP schema-drift target",
            )
        if self._control_failed or self._schema_swap_ordinal is None:
            raise AdapterPreconditionError(
                code="mcp_schema_swap_failed",
                reason="controlled MCP target schema was not replaced exactly once",
            )
        if self._target_calls == 1:
            raise AdapterPreconditionError(
                code="mcp_schema_recovery_call_missing",
                reason="agent did not issue a corrected MCP call after schema rejection",
            )
        if self._target_calls != 2:
            raise AdapterPreconditionError(
                code="mcp_schema_recovery_call_ambiguous",
                reason="agent made more than one recovery call against the schema-drift target",
            )
        if self._cached_schema is None:
            raise AdapterPreconditionError(
                code="mcp_schema_cached_contract_missing",
                reason="host cache did not preserve the initial target schema before replacement",
            )
        if self._stale_is_error is not True or not self._stale_text:
            raise AdapterPreconditionError(
                code="mcp_schema_stale_call_not_rejected",
                reason="stale v1 arguments were not rejected after the live schema replacement",
            )
        if self._recovery_before_refresh:
            raise AdapterPreconditionError(
                code="mcp_schema_recovery_before_refresh",
                reason="corrected MCP call occurred before refreshed v2 discovery was observed",
            )
        if self._post_invalidation_lists == 0 or self._refreshed_schema is None:
            raise AdapterPreconditionError(
                code="mcp_schema_refreshed_discovery_missing",
                reason="host cache invalidation did not produce refreshed MCP tool discovery",
            )
        if self._post_invalidation_lists != 1:
            raise AdapterPreconditionError(
                code="mcp_schema_refreshed_discovery_ambiguous",
                reason="schema-drift recovery observed more than one post-invalidation tool listing",
            )
        if self._recovery_is_error is not False or self._recovery_text != _EXPECTED_RECOVERY_TEXT:
            raise AdapterPreconditionError(
                code="mcp_schema_recovery_mismatch",
                reason="corrected MCP call did not produce the bound replacement result",
            )

    def require_protocol_receipt(self) -> MCPFaultReceipt:
        try:
            return create_schema_drift_protocol_receipt(
                fault=self._fault,
                ttl_ms=self.ttl_ms,
                initial_schema=self.initial_schema,
                cached_schema=self.cached_schema,
                refreshed_schema=self.refreshed_schema,
                stale_protocol_text=self.stale_protocol_text,
                protocol_recovery_text=self.protocol_recovery_text,
                initial_list_ordinal=self.initial_list_ordinal,
                schema_swap_ordinal=self.schema_swap_ordinal,
                stale_call_ordinal=self.stale_call_ordinal,
                cache_invalidation_ordinal=self.cache_invalidation_ordinal,
                refreshed_list_ordinal=self.refreshed_list_ordinal,
                recovery_call_ordinal=self.recovery_call_ordinal,
            )
        except ValueError as exc:
            raise AdapterPreconditionError(
                code="mcp_schema_protocol_relation_invalid",
                reason="observed MCP schema-drift relation does not match the controlled contract",
            ) from exc

    def _mark(self) -> int:
        value = self._ordinal
        self._ordinal += 1
        return value

    @staticmethod
    def _require_schema(
        value: dict[str, object] | None,
        label: str,
    ) -> dict[str, object]:
        if value is None:
            raise AdapterPreconditionError(
                code=f"mcp_schema_{label}_contract_missing",
                reason=f"{label} MCP target schema was not observed",
            )
        return value

    @staticmethod
    def _require_ordinal(value: int | None, label: str) -> int:
        if value is None:
            raise AdapterPreconditionError(
                code="mcp_schema_protocol_chronology_incomplete",
                reason=f"MCP schema-drift chronology lacks {label}",
            )
        return value


def _attach_verified_schema_bridge(
    result: AdapterResult,
    *,
    scenario: EvaluationScenario,
    fault: MCPFaultSpec,
    protocol_receipt: MCPFaultReceipt,
    recorder: _MCPToolSchemaDriftRecorder,
) -> AdapterResult:
    requests = [
        event
        for event in result.events
        if event.kind is EvidenceKind.TOOL_REQUEST and event.payload.get("tool") == fault.tool_name
    ]
    if len(requests) != 2:
        raise AdapterPreconditionError(
            code="mcp_schema_agent_request_identity_ambiguous",
            reason="normalized agent evidence does not contain exactly two MCP target requests",
        )

    call_ids: list[str] = []
    for event in requests:
        call_id = event.payload.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            raise AdapterPreconditionError(
                code="mcp_schema_agent_call_identity_missing",
                reason="normalized MCP schema-drift request has no stable agent call identity",
            )
        call_ids.append(call_id)
    if call_ids[0] == call_ids[1]:
        raise AdapterPreconditionError(
            code="mcp_schema_agent_call_identity_reused",
            reason="stale and corrected MCP calls reused the same agent call identity",
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
                code="mcp_schema_agent_result_identity_ambiguous",
                reason="normalized agent evidence does not contain one result per schema-drift call",
            )
        results.append(matching[0])

    if not (
        requests[0].sequence < results[0].sequence < requests[1].sequence < results[1].sequence
    ):
        raise AdapterPreconditionError(
            code="mcp_schema_agent_adaptation_causality_unverified",
            reason=(
                "normalized agent evidence does not prove that the corrected call was issued only "
                "after the stale-schema rejection became model-visible"
            ),
        )

    try:
        bridge = MCPAgentToolSchemaDriftReceipt.create(
            scenario_identity=scenario.identity,
            fault=fault,
            protocol_receipt=protocol_receipt,
            agent_tool_name=fault.tool_name,
            stale_call_id=call_ids[0],
            recovery_call_id=call_ids[1],
            ttl_ms=recorder.ttl_ms,
            initial_schema=recorder.initial_schema,
            cached_schema=recorder.cached_schema,
            refreshed_schema=recorder.refreshed_schema,
            stale_arguments=recorder.stale_arguments,
            recovery_arguments=recorder.recovery_arguments,
            stale_protocol_text=recorder.stale_protocol_text,
            agent_error_output=results[0].payload.get("output"),
            protocol_recovery_text=recorder.protocol_recovery_text,
            agent_recovery_output=results[1].payload.get("output"),
            initial_list_ordinal=recorder.initial_list_ordinal,
            schema_swap_ordinal=recorder.schema_swap_ordinal,
            stale_call_ordinal=recorder.stale_call_ordinal,
            cache_invalidation_ordinal=recorder.cache_invalidation_ordinal,
            refreshed_list_ordinal=recorder.refreshed_list_ordinal,
            recovery_call_ordinal=recorder.recovery_call_ordinal,
        )
    except ValueError as exc:
        raise AdapterPreconditionError(
            code="mcp_schema_bridge_receipt_invalid",
            reason="agent schema-drift evidence does not match the verified MCP relation",
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
            code="mcp_schema_bridge_insertion_failed",
            reason="verified MCP schema adaptation could not be ordered after recovery result",
        )
    return replace(result, events=tuple(bridged_events))


def _new_stdio_server(params: Mapping[str, object]) -> Any:
    try:
        from agents.mcp import MCPServerStdio
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "install both the 'openai' and 'mcp' extras to use "
            "OpenAIAgentsMCPToolSchemaDriftAdapter"
        ) from exc

    return MCPServerStdio(
        params=copy.deepcopy(dict(params)),
        cache_tools_list=True,
        name="agent-evals-controlled-mcp-schema-drift",
        tool_filter={"blocked_tool_names": [_CONTROL_TOOL]},
    )


def _clone_agent_with_controlled_server(
    agent: object,
    *,
    server: object,
    target_tool: str,
) -> Any:
    try:
        from agents import Agent
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "install the 'openai' extra to use OpenAIAgentsMCPToolSchemaDriftAdapter"
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
    if any(getattr(tool, "name", None) == target_tool for tool in agent.tools):
        raise AdapterPreconditionError(
            code="mcp_target_tool_collision",
            reason="controlled MCP target conflicts with an existing local agent tool name",
        )
    if any(getattr(tool, "name", None) == _CONTROL_TOOL for tool in agent.tools):
        raise AdapterPreconditionError(
            code="mcp_control_tool_collision",
            reason="evaluator control name conflicts with an existing local agent tool name",
        )
    return agent.clone(mcp_servers=[server])


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


def _exact_target_schema(tools: list[Any], target_tool: str) -> dict[str, object]:
    matching = [tool for tool in tools if getattr(tool, "name", None) == target_tool]
    if len(matching) != 1:
        raise AdapterPreconditionError(
            code="mcp_schema_target_discovery_ambiguous",
            reason="MCP tool discovery did not expose exactly one controlled target",
        )
    raw_schema = getattr(matching[0], "input_schema", None)
    if not isinstance(raw_schema, Mapping):
        raw_schema = getattr(matching[0], "inputSchema", None)
    if not isinstance(raw_schema, Mapping):
        raise AdapterPreconditionError(
            code="mcp_schema_target_contract_unavailable",
            reason="MCP target discovery did not expose a JSON input schema",
        )
    try:
        return schema_projection(raw_schema)
    except ValueError as exc:
        raise AdapterPreconditionError(
            code="mcp_schema_target_contract_invalid",
            reason="MCP target schema is outside the controlled scalar-required contract",
        ) from exc


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
