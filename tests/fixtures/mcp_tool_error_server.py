"""Deterministic official-MCP stdio fixture for agent-visible ToolError recovery tests."""

from __future__ import annotations

import argparse
import asyncio

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", required=True)
    parser.add_argument("--error", required=True)
    parser.add_argument("--benign", required=True)
    return parser.parse_args()


async def _run() -> None:
    config = _arguments()
    call_count = 0
    server = MCPServer("agent-evals-controlled-tool-error")

    def controlled_tool(customer_id: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ToolError(config.error)
        return config.benign

    server.add_tool(
        controlled_tool,
        name=config.tool,
        description="Return one deterministic customer record with one controlled transient error.",
        structured_output=False,
    )
    await server.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(_run())
