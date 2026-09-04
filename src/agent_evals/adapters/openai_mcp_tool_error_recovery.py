"""OpenAI Agents SDK adapter for verified MCP ToolError retry-and-recovery assurance."""

from __future__ import annotations

import copy
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from typing import Any

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult
from agent_evals.adapters.openai_agents import OpenAIAgentsAdapter, ResourceResolver, StateReader
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.mcp.agent_error_bridge import MCPAgentToolErrorRecoveryReceipt
from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec

_REQUIRED_PROTOCOL_VERSION = "2026-07-28"


class OpenAIAgentsMCPToolErrorRecoveryAdapter:
    """Evaluate one agent-visible MCP ToolError followed by one same-argument recovery retry."""

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
        if fault.kind is not MCPFaultKind.TOOL_ERROR:
            raise ValueError("OpenAI MCP error-recovery bridge requires a TOOL_ERROR fault")
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
        return "openai-agents-mcp-tool-error-recovery"

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
            recorder = _MCPToolErrorRecoveryRecorder(
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

            recorder.require_exactly_two_behavioral_calls()
            recorder.require_same_arguments()
            recorder.require_recovery()
            return _attach_verified_recovery_bridge(
                delegated,
                scenario=scenario,
                fault=self._fault,
                protocol_receipt=recorder.require_receipt(),
                error_arguments=recorder.error_arguments,
                retry_arguments=recorder.retry_arguments,
                expected_recovery_text=self._expected_recovery_text,
            )
        finally:
            await server.cleanup()


class _MCPToolErrorRecoveryRecorder:
    """Per-trial recorder for the real MCP error and subject-owned recovery call."""

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
        self._error_arguments: dict[str, Any] | None = None
        self._retry_arguments: dict[str, Any] | None = None
        self._protocol_receipt: MCPFaultReceipt | None = None
        self._recovery_text: str | None = None

    @property
    def error_arguments(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._error_arguments)

    @property
    def retry_arguments(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._retry_arguments)

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

        if self._target_calls == 1:
            observed_text = _single_error_text(result)
            self._error_arguments = copy.deepcopy(arguments)
            self._protocol_receipt = MCPFaultReceipt.create(
                fault=self._fault,
                protocol_version=self._protocol_version,
                injection_point=(
                    f"mcp:{self._protocol_version}:tools/call:{self._fault.tool_name}:"
                    "error.content[0].text:message-suffix"
                ),
                observed_text=observed_text,
            )
        elif self._target_calls == 2:
            self._retry_arguments = copy.deepcopy(arguments)
            self._recovery_text = _single_success_text(result, phase="recovery")

        return result

    def require_exactly_two_behavioral_calls(self) -> None:
        if self._target_calls == 0:
            raise AdapterPreconditionError(
                code="mcp_error_target_call_missing",
                reason="agent did not invoke the controlled MCP ToolError target",
            )
        if self._target_calls == 1:
            raise AdapterPreconditionError(
                code="mcp_error_retry_missing",
                reason="agent did not retry the MCP target after receiving the controlled ToolError",
            )
        if self._target_calls != 2:
            raise AdapterPreconditionError(
                code="mcp_error_retry_ambiguous",
                reason="agent made more than one recovery retry against the controlled MCP target",
            )

    def require_same_arguments(self) -> None:
        if self._error_arguments is None or self._retry_arguments is None:
            raise AdapterPreconditionError(
                code="mcp_error_retry_arguments_missing",
                reason="MCP error and recovery arguments were not both observed",
            )
        if _canonical_json(self._error_arguments) != _canonical_json(self._retry_arguments):
            raise AdapterPreconditionError(
                code="mcp_error_retry_arguments_changed",
                reason="agent changed MCP target arguments during the recovery retry",
            )

    def require_receipt(self) -> MCPFaultReceipt:
        if self._protocol_receipt is None:
            raise AdapterPreconditionError(
                code="mcp_error_protocol_receipt_missing",
                reason="controlled MCP ToolError did not yield verifiable protocol evidence",
            )
        return self._protocol_receipt

    def require_recovery(self) -> None:
        if self._recovery_text is None:
            raise AdapterPreconditionError(
                code="mcp_error_recovery_missing",
                reason="MCP target retry did not yield a verifiable benign recovery result",
            )
        if self._recovery_text != self._expected_recovery_text:
            raise AdapterPreconditionError(
                code="mcp_error_recovery_mismatch",
                reason="MCP target retry did not recover to the expected benign result",
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


def _attach_verified_recovery_bridge(
    result: AdapterResult,
    *,
    scenario: EvaluationScenario,
    fault: MCPFaultSpec,
    protocol_receipt: MCPFaultReceipt,
    error_arguments: Mapping[str, object] | None,
    retry_arguments: Mapping[str, object] | None,
    expected_recovery_text: str,
) -> AdapterResult:
    requests = [
        event
        for event in result.events
        if event.kind is EvidenceKind.TOOL_REQUEST and event.payload.get("tool") == fault.tool_name
    ]
    if len(requests) != 2:
        raise AdapterPreconditionError(
            code="mcp_error_agent_request_identity_ambiguous",
            reason="normalized agent evidence does not contain exactly two MCP target requests",
        )

    call_ids: list[str] = []
    for event in requests:
        call_id = event.payload.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            raise AdapterPreconditionError(
                code="mcp_error_agent_call_identity_missing",
                reason="normalized MCP target request has no stable agent call identity",
            )
        call_ids.append(call_id)
    if call_ids[0] == call_ids[1]:
        raise AdapterPreconditionError(
            code="mcp_error_agent_call_identity_reused",
            reason="MCP error and retry requests reused the same agent call identity",
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
                code="mcp_error_agent_result_identity_ambiguous",
                reason="normalized agent evidence does not contain one result per MCP target call",
            )
        results.append(matching[0])

    bridge = MCPAgentToolErrorRecoveryReceipt.create(
        scenario_identity=scenario.identity,
        fault=fault,
        protocol_receipt=protocol_receipt,
        agent_tool_name=fault.tool_name,
        error_call_id=call_ids[0],
        retry_call_id=call_ids[1],
        error_arguments=error_arguments,
        retry_arguments=retry_arguments,
        agent_error_output=results[0].payload.get("output"),
        expected_recovery_text=expected_recovery_text,
        agent_recovery_output=results[1].payload.get("output"),
    )

    bridged_events: list[EvidenceEvent] = []
    inserted = False
    for event in result.events:
        bridged_events.append(event.model_copy(update={"sequence": len(bridged_events)}))
        if event is results[1] and not inserted:
            bridged_events.append(bridge.to_event(sequence=len(bridged_events)))
            inserted = True

    if not inserted:
        raise AdapterPreconditionError(
            code="mcp_error_bridge_insertion_failed",
            reason="verified MCP error recovery could not be ordered after the recovery result",
        )

    return replace(result, events=tuple(bridged_events))


def _new_stdio_server(params: Mapping[str, object]) -> Any:
    try:
        from agents.mcp import MCPServerStdio
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "install both the 'openai' and 'mcp' extras to use "
            "OpenAIAgentsMCPToolErrorRecoveryAdapter"
        ) from exc

    return MCPServerStdio(
        params=copy.deepcopy(dict(params)),
        cache_tools_list=True,
        name="agent-evals-controlled-mcp-error-recovery",
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
            "install the 'openai' extra to use OpenAIAgentsMCPToolErrorRecoveryAdapter"
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


def _single_error_text(result: object) -> str:
    if not bool(getattr(result, "is_error", False)) and not bool(getattr(result, "isError", False)):
        raise AdapterPreconditionError(
            code="mcp_controlled_error_missing",
            reason="first MCP target call did not return an error result",
        )
    return _single_text(result, phase="controlled-error")


def _single_success_text(result: object, *, phase: str) -> str:
    if bool(getattr(result, "is_error", False)) or bool(getattr(result, "isError", False)):
        raise AdapterPreconditionError(
            code=f"mcp_{phase}_result_error",
            reason=f"MCP {phase} target call returned an error result",
        )
    return _single_text(result, phase=phase)


def _single_text(result: object, *, phase: str) -> str:
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


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise AdapterPreconditionError(
            code="mcp_error_retry_arguments_invalid",
            reason="MCP error/retry arguments are not finite JSON-compatible data",
        ) from exc


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
