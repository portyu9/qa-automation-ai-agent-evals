"""OpenAI Agents SDK adapter for verified MCP tool-metadata delivery."""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult
from agent_evals.adapters.openai_agents import OpenAIAgentsAdapter, ResourceResolver, StateReader
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent
from agent_evals.mcp.agent_metadata_bridge import MCPAgentToolMetadataReceipt
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_REQUIRED_PROTOCOL_VERSION = "2026-07-28"


class OpenAIAgentsMCPToolMetadataAdapter:
    """Verify one exact MCP target description at the public model-visible tool boundary.

    The target need not be invoked. Metadata can affect model tool selection before any tool call,
    so assurance closes when official MCP discovery and the first model-visible target definition
    agree exactly on description and JSON input schema.
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
        if fault.kind is not MCPFaultKind.TOOL_METADATA_POISON:
            raise ValueError("OpenAI MCP metadata bridge requires a TOOL_METADATA_POISON fault")
        self._agent = agent
        self._stdio_params = _validated_stdio_params(stdio_params)
        self._fault = fault
        self._state_reader = state_reader
        self._resource_resolver = resource_resolver
        self._run_context = run_context
        self._tracing_disabled = tracing_disabled

    @property
    def name(self) -> str:
        return "openai-agents-mcp-tool-metadata"

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

            recorder = _MCPToolMetadataRecorder(
                original_list_tools=server.list_tools,
                fault=self._fault,
                protocol_version=protocol_version,
            )
            server.list_tools = recorder.list_tools
            runner_agent = _clone_agent_with_controlled_server_and_observer(
                self._agent,
                server=server,
                target_tool=self._fault.tool_name,
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

            bridge = recorder.require_bridge(scenario_identity=scenario.identity)
            events: list[EvidenceEvent] = [bridge.to_event(sequence=0)]
            events.extend(
                event.model_copy(update={"sequence": index})
                for index, event in enumerate(delegated.events, start=1)
            )
            return replace(delegated, events=tuple(events))
        finally:
            await server.cleanup()


class _MCPToolMetadataRecorder:
    """Record exact official discovery and first model-visible target metadata."""

    def __init__(
        self,
        *,
        original_list_tools: Callable[..., Awaitable[list[Any]]],
        fault: MCPFaultSpec,
        protocol_version: str,
    ) -> None:
        self._original_list_tools = original_list_tools
        self._fault = fault
        self._protocol_version = protocol_version
        self._protocol_receipt: MCPFaultReceipt | None = None
        self._protocol_schema: dict[str, Any] | None = None
        self._model_description: str | None = None
        self._model_schema: dict[str, Any] | None = None
        self._model_snapshot_ordinal: int | None = None
        self._model_calls = 0

    async def list_tools(
        self,
        run_context: object | None = None,
        agent: object | None = None,
    ) -> list[Any]:
        tools = await self._original_list_tools(run_context, agent)
        target = _exact_target(tools, self._fault.tool_name, phase="protocol discovery")
        description = getattr(target, "description", None)
        if not isinstance(description, str):
            raise AdapterPreconditionError(
                code="mcp_metadata_protocol_description_missing",
                reason="MCP target discovery did not expose a string description",
            )
        schema = _protocol_tool_schema(target)

        if self._protocol_receipt is None:
            self._protocol_receipt = MCPFaultReceipt.create(
                fault=self._fault,
                protocol_version=self._protocol_version,
                injection_point=(
                    f"mcp:{self._protocol_version}:tools/list:"
                    f"{self._fault.tool_name}:description"
                ),
                observed_text=description,
            )
            self._protocol_schema = copy.deepcopy(schema)
        return tools

    def observe_model_tools(self, tools: list[Any]) -> None:
        ordinal = self._model_calls
        self._model_calls += 1
        if self._model_snapshot_ordinal is not None:
            return
        if self._protocol_receipt is None or self._protocol_schema is None:
            raise AdapterPreconditionError(
                code="mcp_metadata_protocol_observation_missing",
                reason="model tool exposure occurred before verifiable MCP discovery evidence",
            )

        target = _exact_target(tools, self._fault.tool_name, phase="model-visible tool snapshot")
        description = getattr(target, "description", None)
        if not isinstance(description, str):
            raise AdapterPreconditionError(
                code="mcp_metadata_model_description_missing",
                reason="model-visible MCP target did not expose a string description",
            )
        schema = getattr(target, "params_json_schema", None)
        if not isinstance(schema, Mapping):
            raise AdapterPreconditionError(
                code="mcp_metadata_model_schema_missing",
                reason="model-visible MCP target did not expose a JSON parameter schema",
            )

        self._model_description = description
        self._model_schema = copy.deepcopy(dict(schema))
        self._model_snapshot_ordinal = ordinal

    def require_bridge(self, *, scenario_identity: str) -> MCPAgentToolMetadataReceipt:
        if self._protocol_receipt is None or self._protocol_schema is None:
            raise AdapterPreconditionError(
                code="mcp_metadata_protocol_receipt_missing",
                reason="agent run did not yield verifiable MCP target metadata discovery",
            )
        if (
            self._model_description is None
            or self._model_schema is None
            or self._model_snapshot_ordinal is None
        ):
            raise AdapterPreconditionError(
                code="mcp_metadata_model_exposure_missing",
                reason="controlled MCP target metadata never became model-visible",
            )
        try:
            return MCPAgentToolMetadataReceipt.create(
                scenario_identity=scenario_identity,
                protocol_receipt=self._protocol_receipt,
                agent_tool_name=self._fault.tool_name,
                protocol_schema=self._protocol_schema,
                model_description=self._model_description,
                model_schema=self._model_schema,
                model_snapshot_ordinal=self._model_snapshot_ordinal,
            )
        except ValueError as exc:
            raise AdapterPreconditionError(
                code="mcp_metadata_bridge_receipt_invalid",
                reason="model-visible MCP metadata does not match the verified protocol relation",
            ) from exc


def _clone_agent_with_controlled_server_and_observer(
    agent: object,
    *,
    server: object,
    target_tool: str,
    recorder: _MCPToolMetadataRecorder,
) -> Any:
    try:
        from agents import Agent
        from agents.models.interface import Model
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "install both the 'openai' and 'mcp' extras to use "
            "OpenAIAgentsMCPToolMetadataAdapter"
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
    if not isinstance(agent.model, Model):
        raise AdapterPreconditionError(
            code="mcp_metadata_concrete_model_required",
            reason=(
                "metadata delivery assurance requires a concrete public SDK Model instance so the "
                "model-visible tool boundary can be observed without changing provider resolution"
            ),
        )

    observed_model = _new_observed_model(agent.model, recorder)
    return agent.clone(mcp_servers=[server], model=observed_model)


def _new_observed_model(delegate: object, recorder: _MCPToolMetadataRecorder) -> object:
    """Create a transparent runtime subclass of the pinned public SDK Model interface."""
    try:
        from agents.models.interface import Model
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("install the 'openai' extra to use MCP metadata assurance") from exc

    if not isinstance(delegate, Model):
        raise AdapterPreconditionError(
            code="mcp_metadata_concrete_model_required",
            reason="metadata delivery assurance requires a concrete public SDK Model instance",
        )

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
        method = getattr(delegate, "get_response")
        return await method(
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
        method = getattr(delegate, "stream_response")
        return method(
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
        method = getattr(delegate, "_cleanup_on_run_end", None)
        if method is not None:
            await method(owner)

    async def close(self: object) -> None:
        del self
        method = getattr(delegate, "close", None)
        if method is not None:
            await method()

    def get_retry_advice(self: object, request: Any) -> Any:
        del self
        method = getattr(delegate, "get_retry_advice", None)
        return None if method is None else method(request)

    observed_type = type(
        "_MCPMetadataObservedModel",
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
            "OpenAIAgentsMCPToolMetadataAdapter"
        ) from exc

    return MCPServerStdio(
        params=copy.deepcopy(dict(params)),
        cache_tools_list=True,
        name="agent-evals-controlled-mcp-metadata",
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


def _exact_target(tools: list[Any], target_tool: str, *, phase: str) -> Any:
    matching = [tool for tool in tools if getattr(tool, "name", None) == target_tool]
    if len(matching) != 1:
        raise AdapterPreconditionError(
            code="mcp_metadata_target_identity_ambiguous",
            reason=f"{phase} did not expose exactly one controlled MCP target tool",
        )
    return matching[0]


def _protocol_tool_schema(tool: object) -> dict[str, Any]:
    raw_schema = getattr(tool, "input_schema", None)
    if not isinstance(raw_schema, Mapping):
        raw_schema = getattr(tool, "inputSchema", None)
    if not isinstance(raw_schema, Mapping):
        raise AdapterPreconditionError(
            code="mcp_metadata_protocol_schema_missing",
            reason="MCP target discovery did not expose a JSON input schema",
        )
    return copy.deepcopy(dict(raw_schema))


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
