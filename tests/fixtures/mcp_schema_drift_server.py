"""Official-MCP stdio fixture for host-refreshed schema-drift adaptation tests.

The control tool exists only so the evaluator can atomically replace the live target contract
between model selection and MCP validation. The OpenAI adapter filters this control tool out of
the model-visible tool list and invokes it directly through the connected MCP session.
"""

from __future__ import annotations

import argparse
import asyncio

from mcp.server import CacheHint, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

_CONTROL_TOOL = "__agent_evals_schema_swap__"


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
        raise ValueError("target tool must not collide with evaluator control tool")

    server = MCPServer(
        "agent-evals-controlled-schema-drift",
        cache_hints={"tools/list": CacheHint(ttl_ms=config.ttl_ms, scope="private")},
    )
    swapped = False

    def initial_tool(query: str) -> str:
        return f"initial:{query}"

    def replacement_tool(customer_id: int, include_history: bool) -> str:
        return f"replacement:{customer_id}:{str(include_history).lower()}"

    def swap_schema() -> str:
        nonlocal swapped
        if swapped:
            raise ToolError("schema swap already completed")
        server.remove_tool(config.tool)
        server.add_tool(
            replacement_tool,
            name=config.tool,
            description="Return one deterministic replacement customer record.",
            structured_output=False,
        )
        swapped = True
        return "schema-swapped"

    server.add_tool(
        initial_tool,
        name=config.tool,
        description="Return one deterministic record using the original query contract.",
        structured_output=False,
    )
    server.add_tool(
        swap_schema,
        name=_CONTROL_TOOL,
        description="Evaluator-only schema replacement control.",
        structured_output=False,
    )
    await server.run_stdio_async()


if __name__ == "__main__":
    asyncio.run(_run())
