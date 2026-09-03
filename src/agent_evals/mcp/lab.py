"""Real-protocol deterministic MCP fault laboratory using the official Python SDK."""

from __future__ import annotations

from typing import Any

from agent_evals.mcp.models import MCPFaultKind, MCPFaultReceipt, MCPFaultSpec, MCPProbeResult

_PROTOCOL_VERSION = "2026-07-28"
_BENIGN_DESCRIPTION = "Return a controlled benign record for deterministic evaluation."
_BENIGN_RESULT = "benign"


class MCPFaultLab:
    """Construct and probe one deterministic in-process MCP fault server.

    The lab uses the official MCP Python SDK's modern in-process server/client path. It does not
    simulate MCP by renaming a local function-tool abstraction. Each probe performs ``tools/list``
    and two ``tools/call`` requests against protocol revision 2026-07-28 and emits a receipt only
    when the official client observation contains the exact controlled fault bytes at the expected
    MCP boundary.
    """

    def __init__(self, fault: MCPFaultSpec) -> None:
        self._fault = fault

    @property
    def fault(self) -> MCPFaultSpec:
        return self._fault

    def build_server(self) -> Any:
        """Build a fresh MCPServer whose state cannot leak across probes."""
        try:
            from mcp.server import MCPServer
            from mcp.server.mcpserver.exceptions import ToolError
        except ImportError as exc:  # pragma: no cover - exercised by optional dependency boundary
            raise RuntimeError(
                "MCP fault laboratory requires the optional 'mcp' dependency group"
            ) from exc

        fault = self._fault
        description = (
            fault.payload_json
            if fault.kind is MCPFaultKind.TOOL_METADATA_POISON
            else _BENIGN_DESCRIPTION
        )
        call_count = 0
        server = MCPServer(f"agent-evals-mcp-lab:{fault.fault_id}")

        @server.tool(
            name=fault.tool_name,
            description=description,
            structured_output=False,
        )
        def controlled_tool(query: str) -> str:
            """Return deterministic data while the lab controls the first-call fault boundary."""
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                if fault.kind is MCPFaultKind.TOOL_RESULT_POISON:
                    return fault.payload_json
                if fault.kind is MCPFaultKind.TOOL_ERROR:
                    raise ToolError(fault.payload_json)
            return f"{_BENIGN_RESULT}:{query}"

        return server

    async def probe(self) -> MCPProbeResult:
        """Observe the fault through the official MCP client and bind verified delivery."""
        try:
            from mcp import Client
        except ImportError as exc:  # pragma: no cover - exercised by optional dependency boundary
            raise RuntimeError(
                "MCP fault laboratory requires the optional 'mcp' dependency group"
            ) from exc

        server = self.build_server()
        async with Client(
            server,
            mode=_PROTOCOL_VERSION,
            raise_exceptions=True,
        ) as client:
            listed = await client.list_tools()
            matching = [tool for tool in listed.tools if tool.name == self._fault.tool_name]
            if len(matching) != 1:
                raise RuntimeError(
                    "MCP fault laboratory expected exactly one advertised target tool"
                )

            advertised_description = matching[0].description or ""
            first = await client.call_tool(self._fault.tool_name, {"query": "first"})
            second = await client.call_tool(self._fault.tool_name, {"query": "second"})
            protocol_version = client.session.protocol_version

        first_text = _text_content(first.content)
        second_text = _text_content(second.content)
        receipt = self._receipt_for_observation(
            protocol_version=protocol_version,
            advertised_description=advertised_description,
            first_call_text=first_text,
            first_call_is_error=bool(first.is_error),
        )

        return MCPProbeResult(
            fault_identity=self._fault.identity,
            protocol_version=protocol_version,
            advertised_description=advertised_description,
            first_call_text=first_text,
            first_call_is_error=bool(first.is_error),
            second_call_text=second_text,
            second_call_is_error=bool(second.is_error),
            receipt=receipt,
        )

    def _receipt_for_observation(
        self,
        *,
        protocol_version: str,
        advertised_description: str,
        first_call_text: tuple[str, ...],
        first_call_is_error: bool,
    ) -> MCPFaultReceipt | None:
        """Create delivery evidence only after the official client observes exact bytes."""
        fault = self._fault
        if protocol_version != _PROTOCOL_VERSION:
            return None

        if fault.kind is MCPFaultKind.TOOL_METADATA_POISON:
            if advertised_description != fault.payload_json:
                return None
            point = f"mcp:{_PROTOCOL_VERSION}:tools/list:{fault.tool_name}:description"
        elif fault.kind is MCPFaultKind.TOOL_RESULT_POISON:
            if first_call_is_error or first_call_text != (fault.payload_json,):
                return None
            point = f"mcp:{_PROTOCOL_VERSION}:tools/call:{fault.tool_name}:result.content[0].text"
        elif fault.kind is MCPFaultKind.TOOL_ERROR:
            if not first_call_is_error or first_call_text != (fault.payload_json,):
                return None
            point = f"mcp:{_PROTOCOL_VERSION}:tools/call:{fault.tool_name}:error.content[0].text"
        else:  # pragma: no cover - enum exhaustiveness guard
            return None

        return MCPFaultReceipt.create(
            fault=fault,
            protocol_version=protocol_version,
            injection_point=point,
        )


def _text_content(content: list[Any]) -> tuple[str, ...]:
    """Extract only public text blocks without interpreting non-text MCP content."""
    return tuple(
        text
        for block in content
        if isinstance((text := getattr(block, "text", None)), str)
    )
