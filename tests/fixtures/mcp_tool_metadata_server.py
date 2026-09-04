"""Deterministic official-MCP stdio fixture for model-visible metadata delivery tests."""

from __future__ import annotations

import argparse
import asyncio

from mcp.server import MCPServer


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", required=True)
    parser.add_argument("--description", required=True)
    return parser.parse_args()


async def _run() -> None:
    config = _arguments()
    server = MCPServer("agent-evals-controlled-tool-metadata")

    def controlled_tool(customer_id: str) -> str:
        return f"customer:{customer_id}"

    server.add_tool(
        controlled_tool,
        name=config.tool,
        description=config.description,
        structured_output=False,
    )
    await server.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(_run())
