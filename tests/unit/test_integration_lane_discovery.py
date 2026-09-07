from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INTEGRATION_DIR = _REPO_ROOT / "tests" / "integration"
_OPENAI_PREFIX = "test_openai_"
_MCP_PREFIX = "test_mcp_"
_OPTIONAL_MARKERS = frozenset({"openai", "mcp", "mcp_remote", "mcp_oauth"})
_MCP_MARKERS = frozenset({"mcp", "mcp_remote", "mcp_oauth"})


def _pytest_markers(path: Path) -> frozenset[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    markers: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        mark_namespace = node.value
        if not isinstance(mark_namespace, ast.Attribute) or mark_namespace.attr != "mark":
            continue
        pytest_name = mark_namespace.value
        if isinstance(pytest_name, ast.Name) and pytest_name.id == "pytest":
            markers.add(node.attr)

    return frozenset(markers)


def test_optional_integration_tests_follow_lane_discovery_contract() -> None:
    violations: list[str] = []

    for path in sorted(_INTEGRATION_DIR.glob("test_*.py")):
        markers = _pytest_markers(path)
        optional_markers = markers & _OPTIONAL_MARKERS
        name = path.name

        if name.startswith(_OPENAI_PREFIX) and "openai" not in markers:
            violations.append(f"{name}: OpenAI-discovered file is missing pytest.mark.openai")
        if name.startswith(_MCP_PREFIX) and not (markers & _MCP_MARKERS):
            violations.append(f"{name}: MCP-discovered file is missing an MCP lane marker")

        if not optional_markers:
            continue

        if "openai" in markers:
            if not name.startswith(_OPENAI_PREFIX):
                violations.append(
                    f"{name}: pytest.mark.openai requires the {_OPENAI_PREFIX!r} filename prefix"
                )
            continue

        if markers & _MCP_MARKERS and not name.startswith(_MCP_PREFIX):
            violations.append(
                f"{name}: MCP-only optional tests require the {_MCP_PREFIX!r} filename prefix"
            )

    assert not violations, (
        "optional integration tests can escape required CI discovery:\n" + "\n".join(violations)
    )
