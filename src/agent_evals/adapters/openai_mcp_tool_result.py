"""OpenAI Agents SDK adapter for same-call MCP tool-result delivery assurance.

This optional module composes the existing OpenAI adapter with one official
``MCPServerStdio`` connection. It instruments only the public ``call_tool``
boundary, captures the exact result consumed by the agent, verifies one-shot
server recovery on the same live session, and closes the provider-neutral
``MCPAgentToolResultReceipt`` bridge before returning normalized evidence.

Importing :mod:`agent_evals` does not import this module or require optional
OpenAI/MCP dependencies.
"""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult
from agent_evals.adapters.openai_agents import OpenAIAgentsAdapter, ResourceResolver, StateReader
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.mcp.agent_bridge import MCPAgentToolResultReceipt
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_REQUIRED_PROTOCOL_VERSION = "2026-07-28"


class OpenAIAgentsMCPToolResultAdapter:
    """Evaluate one controlled MCP tool-result delivery through an OpenAI agent.

    A fresh official ``MCPServerStdio`` client is created for every trial. The
    supplied base agent must not already own MCP servers: the adapter clones it
    with exactly one controlled server so tool provenance remains unambiguous.
    """

    def __init__(
        self,
        agent: object,
        *,
        stdio_params: Mapping[str, object],
        fault: MCPFaultSpec,
        expected_recovery_text: str,
        state_reader: StateReader,
        resource_resolver: ResourceResolver | None = None,
        run_context: object | None = None,
        tracing_disabled: bool = True,
    ) -> None:
        if fault.kind is not MCPFaultKind.TOOL_RESULT_POISON:
            raise ValueError("OpenAI MCP bridge requires a TOOL_RESULT_POISON fault")
        if not expected_recovery_text:
            raise ValueError("expected MCP recovery text must be non-empty")
        self._agent = agent
        self._stdio_params = _validated_stdio_params(stdio_params)
        self._fault = fault
        self._expected_recovery_text = expected_recovery_text
        self._state_reader = state_reader
        self._resource_resolver = resource_resolver
        self._run_context = run_context
        self._tracing_disabled = tracing_disabled

    @property
    def name(self) -> str:
        return "openai-agents-mcp-tool-result"

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

            original_call_tool = server.call_tool
            recorder = _MCPToolResultRecorder(
                original_call_tool=original_call_tool,
                fault=self._fault,
                protocol_version=protocol_version,
                expected_recovery_text=self._expected_recovery_text,
            )
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

            recorder.require_exactly_one_behavioral_call()
            await recorder.verify_recovery()
            return _attach_verified_bridge(
                delegated,
                scenario=scenario,
                fault=self._fault,
                protocol_receipt=recorder.require_receipt(),
            )
        finally:
            await server.cleanup()


class _MCPToolResultRecorder:
    """Per-trial same-call MCP observation and recovery verifier."""

    def __init__(
        self,
        *,
        original_call_tool: Callable[..., Awaitable[object]],
        fault: MCPFaultSpec,
        protocol_version: str,
        expected_recovery_text: str,
    ) -> None:
        self._original_call_tool = original_call_tool
        self._fault = fault
        self._protocol_version = protocol_version
        self._expected_recovery_text = expected_recovery_text
        self._target_calls = 0
        self._arguments: dict[str, Any] | None = None
        self._meta: dict[str, Any] | None = None
        self._receipt: MCPFaultReceipt | None = None

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        meta: dict[str, Any] | None = None,
    ) -> object:
        if tool_name != self._fault.tool_name:
            return await _invoke_call_tool(self._original_call_tool, tool_name, arguments, meta)

        self._target_calls += 1
        result = await _invoke_call_tool(self._original_call_tool, tool_name, arguments, meta)
        if self._target_calls != 1:
            return result

        observed_text = _single_success_text(result, phase="controlled")
        self._arguments = copy.deepcopy(arguments)
        self._meta = copy.deepcopy(meta)
        self._receipt = MCPFaultReceipt.create(
            fault=self._fault,
            protocol_version=self._protocol_version,
            injection_point=(
                f"mcp:{self._protocol_version}:tools/call:"
                f"{self._fault.tool_name}:result.content[0].text"
            ),
            observed_text=observed_text,
        )
        return result

    def require_exactly_one_behavioral_call(self) -> None:
        if self._target_calls == 0:
            raise AdapterPreconditionError(
                code="mcp_target_call_missing",
                reason="agent did not consume the controlled MCP target tool result",
            )
        if self._target_calls != 1:
            raise AdapterPreconditionError(
                code="mcp_target_call_ambiguous",
                reason="agent invoked the controlled MCP target tool more than once",
            )

    def require_receipt(self) -> MCPFaultReceipt:
        if self._receipt is None:
            raise AdapterPreconditionError(
                code="mcp_protocol_receipt_missing",
                reason="controlled MCP target call did not yield verifiable protocol evidence",
            )
        return self._receipt

    async def verify_recovery(self) -> None:
        if self._target_calls != 1 or self._receipt is None:
            raise AdapterPreconditionError(
                code="mcp_recovery_precondition_failed",
                reason="MCP recovery cannot be verified without one controlled target call",
            )

        recovery = await _invoke_call_tool(
            self._original_call_tool,
            self._fault.tool_name,
            copy.deepcopy(self._arguments),
            copy.deepcopy(self._meta),
        )
        recovery_text = _single_success_text(recovery, phase="recovery")
        if recovery_text != self._expected_recovery_text:
            raise AdapterPreconditionError(
                code="mcp_recovery_mismatch",
                reason="MCP target tool did not recover to the expected benign result",
            )


async def _invoke_call_tool(
    call_tool: Callable[..., Awaitable[object]],
    tool_name: str,
    arguments: dict[str, Any] | None,
    meta: dict[str, Any] | None,
) -> object:
    if meta is None:
        return await call_tool(tool_name, arguments)
    return await call_tool(tool_name, arguments, meta=meta)


def _attach_verified_bridge(
    result: AdapterResult,
    *,
    scenario: EvaluationScenario,
    fault: MCPFaultSpec,
    protocol_receipt: MCPFaultReceipt,
) -> AdapterResult:
    matching_requests = [
        event
        for event in result.events
        if event.kind is EvidenceKind.TOOL_REQUEST and event.payload.get("tool") == fault.tool_name
    ]
    if len(matching_requests) != 1:
        raise AdapterPreconditionError(
            code="mcp_agent_request_identity_ambiguous",
            reason="normalized agent evidence does not contain one exact MCP target tool request",
        )

    call_id = matching_requests[0].payload.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        raise AdapterPreconditionError(
            code="mcp_agent_call_identity_missing",
            reason="normalized MCP target request has no stable agent call identity",
        )

    matching_results = [
        event
        for event in result.events
        if event.kind is EvidenceKind.TOOL_RESULT and event.payload.get("call_id") == call_id
    ]
    if len(matching_results) != 1:
        raise AdapterPreconditionError(
            code="mcp_agent_result_identity_ambiguous",
            reason="normalized agent evidence does not contain one exact MCP target tool result",
        )

    bridge = MCPAgentToolResultReceipt.create(
        scenario_identity=scenario.identity,
        protocol_receipt=protocol_receipt,
        agent_tool_name=fault.tool_name,
        agent_call_id=call_id,
        agent_output=matching_results[0].payload.get("output"),
    )

    bridged_events: list[EvidenceEvent] = []
    inserted = False
    for event in result.events:
        if event is matching_results[0] and not inserted:
            bridged_events.append(bridge.to_event(sequence=len(bridged_events)))
            inserted = True
        bridged_events.append(event.model_copy(update={"sequence": len(bridged_events)}))

    if not inserted:
        raise AdapterPreconditionError(
            code="mcp_bridge_insertion_failed",
            reason="verified MCP delivery could not be ordered beside the matching agent result",
        )

    return replace(result, events=tuple(bridged_events))


def _new_stdio_server(params: Mapping[str, object]) -> Any:
    try:
        from agents.mcp import MCPServerStdio
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "install both the 'openai' and 'mcp' extras to use OpenAIAgentsMCPToolResultAdapter"
        ) from exc

    return MCPServerStdio(
        params=copy.deepcopy(dict(params)),
        cache_tools_list=True,
        name="agent-evals-controlled-mcp",
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
            "install the 'openai' extra to use OpenAIAgentsMCPToolResultAdapter"
        ) from exc

    if not isinstance(agent, Agent):
        raise AdapterPreconditionError(
            code="unsupported_agent_type",
            reason="OpenAI MCP assurance requires an OpenAI Agents SDK Agent instance",
        )
    if agent.mcp_servers:
        raise AdapterPreconditionError(
            code="existing_mcp_servers_unsupported",
            reason=(
                "controlled MCP assurance requires a base agent with no preconfigured MCP servers"
            ),
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


def _single_success_text(result: object, *, phase: str) -> str:
    if bool(getattr(result, "is_error", False)) or bool(getattr(result, "isError", False)):
        raise AdapterPreconditionError(
            code=f"mcp_{phase}_result_error",
            reason=f"MCP {phase} target call returned an error result",
        )

    content = getattr(result, "content", None)
    if not isinstance(content, list) or len(content) != 1:
        raise AdapterPreconditionError(
            code=f"mcp_{phase}_result_shape",
            reason=f"MCP {phase} target call must return exactly one content block",
        )
    item = content[0]
    if getattr(item, "type", None) != "text":
        raise AdapterPreconditionError(
            code=f"mcp_{phase}_result_shape",
            reason=f"MCP {phase} target call must return one text content block",
        )
    text = getattr(item, "text", None)
    if not isinstance(text, str):
        raise AdapterPreconditionError(
            code=f"mcp_{phase}_result_shape",
            reason=f"MCP {phase} target call text content is unavailable",
        )
    return text


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
