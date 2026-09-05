"""Official-MCP stdio fixture for host-refreshed tool-identity adaptation tests.

The evaluator-only control tool atomically removes the original live tool and registers the
replacement identity between model selection and MCP call-time lookup. The OpenAI adapter filters
this control tool from model-visible discovery and invokes it directly through the connected session.
"""

from __future__ import annotations

import argparse
import asyncio

from mcp.server import CacheHint, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

_CONTROL_TOOL = "__agent_evals_identity_swap__"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", required=True)
    parser.add_argument("--replacement-tool", required=True)
    parser.add_argument("--ttl-ms", required=True, type=int)
    return parser.parse_args()


async def _run() -> None:
    config = _arguments()
    if config.ttl_ms <= 0:
        raise ValueError("ttl-ms must be positive")
    if config.tool == config.replacement_tool:
        raise ValueError("replacement tool identity must differ from original tool")
    if _CONTROL_TOOL in {config.tool, config.replacement_tool}:
        raise ValueError("controlled tool identity must not collide with evaluator control tool")

    server = MCPServer(
        "agent-evals-controlled-identity-drift",
        cache_hints={"tools/list": CacheHint(ttl_ms=config.ttl_ms, scope="private")},
    )
    swapped = False

    def initial_tool(query: str) -> str:
        return f"initial:{query}"

    def replacement_tool(query: str) -> str:
        return f"replacement:{query}"

    def swap_identity() -> str:
        nonlocal swapped
        if swapped:
            raise ToolError("identity swap already completed")
        server.remove_tool(config.tool)
        server.add_tool(
            replacement_tool,
            name=config.replacement_tool,
            description="Return one deterministic record under the replacement tool identity.",
            structured_output=False,
        )
        swapped = True
        return "identity-swapped"

    server.add_tool(
        initial_tool,
        name=config.tool,
        description="Return one deterministic record under the original tool identity.",
        structured_output=False,
    )
    server.add_tool(
        swap_identity,
        name=_CONTROL_TOOL,
        description="Evaluator-only tool identity replacement control.",
        structured_output=False,
    )
    await server.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(_run())
