"""Official-MCP stdio fixture for host-refreshed stale-tool removal tests.

The evaluator-only control removes the live target between model selection and MCP call-time
lookup. The OpenAI adapter filters this control from model-visible discovery and invokes it directly
through the connected session. A positive tools/list TTL preserves the stale target in host cache
until the evaluator explicitly invalidates that cache after the real unknown-tool rejection.
"""

from __future__ import annotations

import argparse
import asyncio

from mcp.server import CacheHint, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

_CONTROL_TOOL = "__agent_evals_remove_target__"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", required=True)
    parser.add_argument("--ttl-ms", required=True, type=int)
    return parser.parse_args()


async def _run() -> None:
    config = _arguments()
    if config.ttl_ms <= 0:
        raise ValueError("ttl-ms must be positive")
    if config.tool == _CONTROL_TOOL:
        raise ValueError("controlled tool identity must not collide with evaluator control tool")

    server = MCPServer(
        "agent-evals-controlled-stale-cache",
        cache_hints={"tools/list": CacheHint(ttl_ms=config.ttl_ms, scope="private")},
    )
    removed = False

    def target(query: str) -> str:
        return f"initial:{query}"

    def remove_target() -> str:
        nonlocal removed
        if removed:
            raise ToolError("target removal already completed")
        server.remove_tool(config.tool)
        removed = True
        return "target-removed"

    server.add_tool(
        target,
        name=config.tool,
        description="Return one deterministic record before controlled target removal.",
        structured_output=False,
    )
    server.add_tool(
        remove_target,
        name=_CONTROL_TOOL,
        description="Evaluator-only live target-removal control.",
        structured_output=False,
    )
    await server.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(_run())
