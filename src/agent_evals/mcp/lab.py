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
    MCPToolIdentityDriftProbeResult,
    MCPToolSchemaDriftProbeResult,
)

_PROTOCOL_VERSION = "2026-07-28"
_BENIGN_DESCRIPTION = "Return a controlled benign record for deterministic evaluation."
_BENIGN_RESULT = "benign"
_SCHEMA_DRIFT_INITIAL_REQUIRED = {"query": "string"}
_SCHEMA_DRIFT_REPLACEMENT_REQUIRED = {
    "customer_id": "integer",
    "include_history": "boolean",
}
_DISCOVERY_FAULTS = frozenset(
    {
        MCPFaultKind.TOOL_LIST_STALE_CACHE,
        MCPFaultKind.TOOL_SCHEMA_DRIFT,
        MCPFaultKind.TOOL_IDENTITY_DRIFT,
    }
)


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
        if fault.kind in _DISCOVERY_FAULTS:
            cache_hints = {
                "tools/list": CacheHint(ttl_ms=_discovery_ttl_ms(fault), scope="private")
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
        if self._fault.kind in _DISCOVERY_FAULTS:
            raise ValueError(
                f"{self._fault.kind.value} requires its discovery-state probe, not content probe()"
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
            raise ValueError("probe_discovery_cache() requires a TOOL_LIST_STALE_CACHE fault")
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

    async def probe_schema_drift(self) -> MCPToolSchemaDriftProbeResult:
        """Prove cached old schema, call-time rejection, refresh, and replacement success."""
        if self._fault.kind is not MCPFaultKind.TOOL_SCHEMA_DRIFT:
            raise ValueError("probe_schema_drift() requires a TOOL_SCHEMA_DRIFT fault")
        try:
            from mcp import Client
        except ImportError as exc:  # pragma: no cover - exercised by optional dependency boundary
            raise RuntimeError(
                "MCP fault laboratory requires the optional 'mcp' dependency group"
            ) from exc

        server = self.build_server()

        def replacement_tool(customer_id: int, include_history: bool) -> str:
            """Return deterministic replacement data after a schema migration."""
            return f"replacement:{customer_id}:{str(include_history).lower()}"

        async with Client(
            server,
            mode=_PROTOCOL_VERSION,
            raise_exceptions=True,
        ) as client:
            initial = await client.list_tools()
            initial_schema_json = _schema_projection_json(
                _exact_tool(initial.tools, self._fault.tool_name).input_schema
            )
            initial_ttl_ms = int(initial.ttl_ms)

            server.remove_tool(self._fault.tool_name)
            server.add_tool(
                replacement_tool,
                name=self._fault.tool_name,
                description=_BENIGN_DESCRIPTION,
                structured_output=False,
            )

            cached = await client.list_tools()
            cached_schema_json = _schema_projection_json(
                _exact_tool(cached.tools, self._fault.tool_name).input_schema
            )

            stale_call = await client.call_tool(self._fault.tool_name, {"query": "stale"})

            refreshed = await client.list_tools(cache_mode="refresh")
            refreshed_schema_json = _schema_projection_json(
                _exact_tool(refreshed.tools, self._fault.tool_name).input_schema
            )

            refreshed_call = await client.call_tool(
                self._fault.tool_name,
                {"customer_id": 7, "include_history": True},
            )
            protocol_version = client.session.protocol_version

        stale_text = _text_content(stale_call.content)
        refreshed_text = _text_content(refreshed_call.content)
        receipt = self._schema_drift_receipt(
            protocol_version=protocol_version,
            initial_schema_json=initial_schema_json,
            cached_schema_json=cached_schema_json,
            refreshed_schema_json=refreshed_schema_json,
            stale_call_text=stale_text,
            stale_call_is_error=bool(stale_call.is_error),
            refreshed_call_text=refreshed_text,
            refreshed_call_is_error=bool(refreshed_call.is_error),
            initial_ttl_ms=initial_ttl_ms,
        )
        return MCPToolSchemaDriftProbeResult(
            fault_identity=self._fault.identity,
            protocol_version=protocol_version,
            initial_schema_json=initial_schema_json,
            cached_schema_json=cached_schema_json,
            refreshed_schema_json=refreshed_schema_json,
            stale_call_text=stale_text,
            stale_call_is_error=bool(stale_call.is_error),
            refreshed_call_text=refreshed_text,
            refreshed_call_is_error=bool(refreshed_call.is_error),
            receipt=receipt,
        )

    async def probe_identity_drift(self) -> MCPToolIdentityDriftProbeResult:
        """Prove cached old identity, stale-name rejection, refresh, and replacement success."""
        if self._fault.kind is not MCPFaultKind.TOOL_IDENTITY_DRIFT:
            raise ValueError("probe_identity_drift() requires a TOOL_IDENTITY_DRIFT fault")
        try:
            from mcp import Client
        except ImportError as exc:  # pragma: no cover - exercised by optional dependency boundary
            raise RuntimeError(
                "MCP fault laboratory requires the optional 'mcp' dependency group"
            ) from exc

        server = self.build_server()
        replacement_name = _identity_replacement_tool_name(self._fault)

        def replacement_tool(query: str) -> str:
            """Return deterministic replacement data under the new tool identity."""
            return f"replacement:{query}"

        async with Client(
            server,
            mode=_PROTOCOL_VERSION,
            raise_exceptions=True,
        ) as client:
            initial = await client.list_tools()
            initial_names = _tool_names(initial.tools)
            initial_ttl_ms = int(initial.ttl_ms)

            server.remove_tool(self._fault.tool_name)
            server.add_tool(
                replacement_tool,
                name=replacement_name,
                description=_BENIGN_DESCRIPTION,
                structured_output=False,
            )

            cached = await client.list_tools()
            cached_names = _tool_names(cached.tools)

            stale_call = await client.call_tool(self._fault.tool_name, {"query": "stale"})

            refreshed = await client.list_tools(cache_mode="refresh")
            refreshed_names = _tool_names(refreshed.tools)

            replacement_call = await client.call_tool(replacement_name, {"query": "fresh"})
            protocol_version = client.session.protocol_version

        stale_text = _text_content(stale_call.content)
        replacement_text = _text_content(replacement_call.content)
        receipt = self._identity_drift_receipt(
            protocol_version=protocol_version,
            initial_tool_names=initial_names,
            cached_tool_names=cached_names,
            refreshed_tool_names=refreshed_names,
            stale_call_text=stale_text,
            stale_call_is_error=bool(stale_call.is_error),
            replacement_call_text=replacement_text,
            replacement_call_is_error=bool(replacement_call.is_error),
            initial_ttl_ms=initial_ttl_ms,
            replacement_name=replacement_name,
        )
        return MCPToolIdentityDriftProbeResult(
            fault_identity=self._fault.identity,
            protocol_version=protocol_version,
            initial_tool_names=initial_names,
            cached_tool_names=cached_names,
            refreshed_tool_names=refreshed_names,
            stale_call_text=stale_text,
            stale_call_is_error=bool(stale_call.is_error),
            replacement_call_text=replacement_text,
            replacement_call_is_error=bool(replacement_call.is_error),
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
        if initial_ttl_ms != _discovery_ttl_ms(fault):
            return None
        if initial_tool_names != (fault.tool_name,):
            return None
        if cached_tool_names != initial_tool_names:
            return None
        if refreshed_tool_names:
            return None

        observation = _canonical_json(
            {
                "cached_tool_names": cached_tool_names,
                "initial_tool_names": initial_tool_names,
                "refreshed_tool_names": refreshed_tool_names,
                "ttl_ms": initial_ttl_ms,
            }
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

    def _schema_drift_receipt(
        self,
        *,
        protocol_version: str,
        initial_schema_json: str,
        cached_schema_json: str,
        refreshed_schema_json: str,
        stale_call_text: tuple[str, ...],
        stale_call_is_error: bool,
        refreshed_call_text: tuple[str, ...],
        refreshed_call_is_error: bool,
        initial_ttl_ms: int,
    ) -> MCPFaultReceipt | None:
        """Bind schema drift only after stale discovery, call rejection, refresh, and recovery."""
        fault = self._fault
        if protocol_version != _PROTOCOL_VERSION:
            return None
        if initial_ttl_ms != _discovery_ttl_ms(fault):
            return None

        expected_initial = _schema_contract_json(_SCHEMA_DRIFT_INITIAL_REQUIRED)
        expected_replacement = _schema_contract_json(_SCHEMA_DRIFT_REPLACEMENT_REQUIRED)
        if initial_schema_json != expected_initial or cached_schema_json != expected_initial:
            return None
        if refreshed_schema_json != expected_replacement:
            return None
        if not stale_call_is_error or not stale_call_text:
            return None
        if refreshed_call_is_error or refreshed_call_text != ("replacement:7:true",):
            return None

        observation = _canonical_json(
            {
                "cached_schema": json.loads(cached_schema_json),
                "initial_schema": json.loads(initial_schema_json),
                "refreshed_call_is_error": refreshed_call_is_error,
                "refreshed_call_text": refreshed_call_text,
                "refreshed_schema": json.loads(refreshed_schema_json),
                "stale_call_is_error": stale_call_is_error,
                "stale_call_text": stale_call_text,
                "ttl_ms": initial_ttl_ms,
            }
        )
        return MCPFaultReceipt.create(
            fault=fault,
            protocol_version=protocol_version,
            injection_point=(
                f"mcp:{_PROTOCOL_VERSION}:tools/list:schema-drift:{fault.tool_name}:"
                "cached-old:call-rejects-old:refresh-new"
            ),
            observed_text=observation,
        )

    def _identity_drift_receipt(
        self,
        *,
        protocol_version: str,
        initial_tool_names: tuple[str, ...],
        cached_tool_names: tuple[str, ...],
        refreshed_tool_names: tuple[str, ...],
        stale_call_text: tuple[str, ...],
        stale_call_is_error: bool,
        replacement_call_text: tuple[str, ...],
        replacement_call_is_error: bool,
        initial_ttl_ms: int,
        replacement_name: str,
    ) -> MCPFaultReceipt | None:
        """Bind identity drift only after stale discovery, stale-name rejection, and refresh."""
        fault = self._fault
        if protocol_version != _PROTOCOL_VERSION:
            return None
        if initial_ttl_ms != _discovery_ttl_ms(fault):
            return None
        if initial_tool_names != (fault.tool_name,) or cached_tool_names != initial_tool_names:
            return None
        if refreshed_tool_names != (replacement_name,):
            return None
        if not stale_call_is_error or not stale_call_text:
            return None
        if "unknown tool" not in "\n".join(stale_call_text).lower():
            return None
        if replacement_call_is_error or replacement_call_text != ("replacement:fresh",):
            return None

        observation = _canonical_json(
            {
                "cached_tool_names": cached_tool_names,
                "initial_tool_names": initial_tool_names,
                "replacement_call_is_error": replacement_call_is_error,
                "replacement_call_text": replacement_call_text,
                "refreshed_tool_names": refreshed_tool_names,
                "stale_call_is_error": stale_call_is_error,
                "stale_call_text": stale_call_text,
                "ttl_ms": initial_ttl_ms,
            }
        )
        return MCPFaultReceipt.create(
            fault=fault,
            protocol_version=protocol_version,
            injection_point=(
                f"mcp:{_PROTOCOL_VERSION}:tools/list:identity-drift:"
                f"{fault.tool_name}->{replacement_name}:cached-old:call-rejects-old:refresh-new"
            ),
            observed_text=observation,
        )


def _discovery_ttl_ms(fault: MCPFaultSpec) -> int:
    payload = fault.payload
    if not isinstance(payload, dict):  # model validation owns the public contract
        raise ValueError("MCP discovery fault payload must be an object")
    ttl_ms = payload.get("ttl_ms")
    if isinstance(ttl_ms, bool) or not isinstance(ttl_ms, int):
        raise ValueError("MCP discovery fault ttl_ms must be an integer")
    return ttl_ms


def _identity_replacement_tool_name(fault: MCPFaultSpec) -> str:
    payload = fault.payload
    if not isinstance(payload, dict):  # model validation owns the public contract
        raise ValueError("MCP identity-drift payload must be an object")
    replacement = payload.get("replacement_tool_name")
    if not isinstance(replacement, str):  # model validation owns the public contract
        raise ValueError("MCP identity-drift replacement tool name must be a string")
    return replacement


def _exact_tool(tools: list[Any], name: str) -> Any:
    matching = [tool for tool in tools if tool.name == name]
    if len(matching) != 1:
        raise RuntimeError(f"MCP fault laboratory expected exactly one advertised tool named {name!r}")
    return matching[0]


def _schema_projection_json(input_schema: dict[str, Any]) -> str:
    required = input_schema.get("required", [])
    properties = input_schema.get("properties", {})
    if not isinstance(required, list) or not isinstance(properties, dict):
        raise RuntimeError("MCP tool input schema lacks expected required/properties structure")

    property_types: dict[str, str] = {}
    for name in required:
        if not isinstance(name, str):
            raise RuntimeError("MCP tool input schema contains a non-string required property")
        property_schema = properties.get(name)
        if not isinstance(property_schema, dict):
            raise RuntimeError(f"MCP tool input schema lacks property definition for {name!r}")
        property_type = property_schema.get("type")
        if not isinstance(property_type, str):
            raise RuntimeError(f"MCP tool input schema lacks a scalar type for {name!r}")
        property_types[name] = property_type

    return _canonical_json(
        {
            "property_types": dict(sorted(property_types.items())),
            "required": sorted(property_types),
        }
    )


def _schema_contract_json(required_types: dict[str, str]) -> str:
    return _canonical_json(
        {
            "property_types": dict(sorted(required_types.items())),
            "required": sorted(required_types),
        }
    )


def _tool_names(tools: list[Any]) -> tuple[str, ...]:
    return tuple(sorted(tool.name for tool in tools))


def _text_content(content: list[Any]) -> tuple[str, ...]:
    """Extract only public text blocks without interpreting non-text MCP content."""
    return tuple(
        text for block in content if isinstance((text := getattr(block, "text", None)), str)
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
