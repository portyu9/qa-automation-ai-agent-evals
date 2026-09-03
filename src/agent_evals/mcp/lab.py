"""Real-protocol deterministic MCP fault laboratory using the official Python SDK."""

from __future__ import annotations

import json
from typing import Any

from agent_evals.mcp.models import (
    MCPDiscoveryProbeResult,
    MCPFaultKind,
    MCPFaultReceipt,
    MCPFaultSpec,
    MCPProbeResult,
)

_PROTOCOL_VERSION = "2026-07-28"
_BENIGN_DESCRIPTION = "Return a controlled benign record for deterministic evaluation."
_BENIGN_RESULT = "benign"


class MCPFaultLab:
    """Construct and probe one deterministic in-process MCP fault server.

    The lab uses the official MCP Python SDK's modern in-process server/client path. It does not
    simulate MCP by renaming a local function-tool abstraction. Receipts are produced only from
    exact public client observations at the boundary defined by each fault kind.
    """

    def __init__(self, fault: MCPFaultSpec) -> None:
        self._fault = fault

    @property
    def fault(self) -> MCPFaultSpec:
        return self._fault

    def build_server(self) -> Any:
        """Build a fresh MCPServer whose state cannot leak across probes."""
        try:
            from mcp.server import CacheHint, MCPServer
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
        cache_hints = None
        if fault.kind is MCPFaultKind.TOOL_LIST_STALE_CACHE:
            cache_hints = {
                "tools/list": CacheHint(ttl_ms=_stale_cache_ttl_ms(fault), scope="private")
            }
        server = MCPServer(
            f"agent-evals-mcp-lab:{fault.fault_id}",
            cache_hints=cache_hints,
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

        server.add_tool(
            controlled_tool,
            name=fault.tool_name,
            description=description,
            structured_output=False,
        )
        return server

    async def probe(self) -> MCPProbeResult:
        """Observe one MCP content fault through the official client."""
        if self._fault.kind is MCPFaultKind.TOOL_LIST_STALE_CACHE:
            raise ValueError(
                "TOOL_LIST_STALE_CACHE requires probe_discovery_cache(), not content probe()"
            )
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

    async def probe_discovery_cache(self) -> MCPDiscoveryProbeResult:
        """Prove stale cached discovery after server-side tool removal, then refresh to truth."""
        if self._fault.kind is not MCPFaultKind.TOOL_LIST_STALE_CACHE:
            raise ValueError(
                "probe_discovery_cache() requires a TOOL_LIST_STALE_CACHE fault"
            )
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
            initial = await client.list_tools()
            initial_names = _tool_names(initial.tools)
            initial_ttl_ms = int(initial.ttl_ms)

            server.remove_tool(self._fault.tool_name)

            cached = await client.list_tools()
            cached_names = _tool_names(cached.tools)
            refreshed = await client.list_tools(cache_mode="refresh")
            refreshed_names = _tool_names(refreshed.tools)
            protocol_version = client.session.protocol_version

        receipt = self._discovery_cache_receipt(
            protocol_version=protocol_version,
            initial_tool_names=initial_names,
            cached_tool_names=cached_names,
            refreshed_tool_names=refreshed_names,
            initial_ttl_ms=initial_ttl_ms,
        )
        return MCPDiscoveryProbeResult(
            fault_identity=self._fault.identity,
            protocol_version=protocol_version,
            initial_tool_names=initial_names,
            cached_tool_names=cached_names,
            refreshed_tool_names=refreshed_names,
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
        """Create delivery evidence only after the official client observes exact content."""
        fault = self._fault
        if protocol_version != _PROTOCOL_VERSION:
            return None

        if fault.kind is MCPFaultKind.TOOL_METADATA_POISON:
            if advertised_description != fault.payload_json:
                return None
            observed_text = advertised_description
            point = f"mcp:{_PROTOCOL_VERSION}:tools/list:{fault.tool_name}:description"
        elif fault.kind is MCPFaultKind.TOOL_RESULT_POISON:
            if first_call_is_error or first_call_text != (fault.payload_json,):
                return None
            observed_text = first_call_text[0]
            point = f"mcp:{_PROTOCOL_VERSION}:tools/call:{fault.tool_name}:result.content[0].text"
        elif fault.kind is MCPFaultKind.TOOL_ERROR:
            expected = f"Error executing tool {fault.tool_name}: {fault.payload_json}"
            if not first_call_is_error or first_call_text != (expected,):
                return None
            observed_text = first_call_text[0]
            point = (
                f"mcp:{_PROTOCOL_VERSION}:tools/call:{fault.tool_name}:"
                "error.content[0].text:message-suffix"
            )
        else:  # pragma: no cover - content-fault enum exhaustiveness guard
            return None

        return MCPFaultReceipt.create(
            fault=fault,
            protocol_version=protocol_version,
            injection_point=point,
            observed_text=observed_text,
        )

    def _discovery_cache_receipt(
        self,
        *,
        protocol_version: str,
        initial_tool_names: tuple[str, ...],
        cached_tool_names: tuple[str, ...],
        refreshed_tool_names: tuple[str, ...],
        initial_ttl_ms: int,
    ) -> MCPFaultReceipt | None:
        """Bind the stale-cache observation only when refresh proves server truth changed."""
        fault = self._fault
        if protocol_version != _PROTOCOL_VERSION:
            return None
        if initial_ttl_ms != _stale_cache_ttl_ms(fault):
            return None
        if initial_tool_names != (fault.tool_name,):
            return None
        if cached_tool_names != initial_tool_names:
            return None
        if refreshed_tool_names:
            return None

        observation = json.dumps(
            {
                "cached_tool_names": cached_tool_names,
                "initial_tool_names": initial_tool_names,
                "refreshed_tool_names": refreshed_tool_names,
                "ttl_ms": initial_ttl_ms,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return MCPFaultReceipt.create(
            fault=fault,
            protocol_version=protocol_version,
            injection_point=(
                f"mcp:{_PROTOCOL_VERSION}:tools/list:cache-use-stale-after-remove:"
                f"{fault.tool_name}:refresh-proves-absent"
            ),
            observed_text=observation,
        )


def _stale_cache_ttl_ms(fault: MCPFaultSpec) -> int:
    payload = fault.payload
    if not isinstance(payload, dict):  # model validation owns the public contract
        raise ValueError("MCP stale-cache payload must be an object")
    ttl_ms = payload.get("ttl_ms")
    if isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int):
        raise ValueError("MCP stale-cache ttl_ms must be an integer")
    return ttl_ms


def _tool_names(tools: list[Any]) -> tuple[str, ...]:
    return tuple(sorted(tool.name for tool in tools))


def _text_content(content: list[Any]) -> tuple[str, ...]:
    """Extract only public text blocks without interpreting non-text MCP content."""
    return tuple(
        text for block in content if isinstance((text := getattr(block, "text", None)), str)
    )
