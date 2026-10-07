"""Bind public governance prose to executable compatibility contracts."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
COMPATIBILITY = ROOT / "docs" / "COMPATIBILITY.md"
CHANGELOG = ROOT / "CHANGELOG.md"
DEPRECATION = ROOT / "docs" / "DEPRECATION_POLICY.md"

COMPATIBILITY_LOCKS = (
    "requirements/compatibility/core-minimum-py311.txt",
    "requirements/compatibility/core-latest-py314.txt",
    "requirements/compatibility/mcp-minimum-py311.txt",
    "requirements/compatibility/mcp-latest-py314.txt",
    "requirements/compatibility/openai-mcp-minimum-py311.txt",
    "requirements/compatibility/openai-mcp-latest-py314.txt",
)


class GovernanceDocsError(ValueError):
    """Public project-governance documentation drifted from executable truth."""


def exact_pin(dependencies: object, package: str) -> str:
    if not isinstance(dependencies, list):
        raise GovernanceDocsError(f"optional dependency set for {package} must be a list")
    prefix = package + "=="
    matches = [
        item[len(prefix) :]
        for item in dependencies
        if isinstance(item, str) and item.startswith(prefix)
    ]
    if len(matches) != 1 or not matches[0]:
        raise GovernanceDocsError(f"{package} must have exactly one exact optional-dependency pin")
    return matches[0]


def load_contract() -> dict[str, str]:
    try:
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise GovernanceDocsError(f"cannot load pyproject.toml: {type(exc).__name__}") from exc
    project = data.get("project")
    if not isinstance(project, dict):
        raise GovernanceDocsError("[project] table is missing")
    optional = project.get("optional-dependencies")
    if not isinstance(optional, dict):
        raise GovernanceDocsError("[project.optional-dependencies] table is missing")
    version = project.get("version")
    requires_python = project.get("requires-python")
    if not isinstance(version, str) or not version:
        raise GovernanceDocsError("project.version must be a non-empty string")
    if not isinstance(requires_python, str) or not requires_python:
        raise GovernanceDocsError("project.requires-python must be a non-empty string")
    return {
        "version": version,
        "requires_python": requires_python,
        "openai_agents": exact_pin(optional.get("openai"), "openai-agents"),
        "mcp": exact_pin(optional.get("mcp"), "mcp"),
    }


def require(text: str, token: str, *, label: str) -> None:
    if token not in text:
        raise GovernanceDocsError(f"{label} is missing executable binding {token!r}")


def validate() -> None:
    contract = load_contract()
    try:
        compatibility = COMPATIBILITY.read_text(encoding="utf-8")
        changelog = CHANGELOG.read_text(encoding="utf-8")
        deprecation = DEPRECATION.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise GovernanceDocsError(
            f"cannot load governance documentation: {type(exc).__name__}"
        ) from exc

    require(
        compatibility,
        f"| Framework package | {contract['version']} source/package metadata; pre-1.0 |",
        label="compatibility matrix",
    )
    require(
        compatibility,
        f"| Python | {contract['requires_python']} (3.11, 3.12, 3.13, 3.14) |",
        label="compatibility matrix",
    )
    require(
        compatibility,
        f"| OpenAI integration | openai-agents=={contract['openai_agents']} |",
        label="compatibility matrix",
    )
    require(
        compatibility,
        f"| MCP integration | mcp=={contract['mcp']} plus declared HTTP/ASGI ranges |",
        label="compatibility matrix",
    )

    for lock in COMPATIBILITY_LOCKS:
        if not (ROOT / lock).is_file():
            raise GovernanceDocsError(f"reviewed compatibility snapshot is missing: {lock}")
        require(compatibility, lock, label="compatibility matrix")

    require(
        changelog,
        f"## {contract['version']} — repository baseline (not yet published)",
        label="changelog",
    )
    require(
        changelog,
        "the repository has no GitHub\nRelease and no PyPI publication",
        label="changelog",
    )

    for token in (
        "It must never keep the same identity while silently changing what old bytes mean.",
        "Historical verification support is not current replay/gradeability.",
        "preserve BLOCKED versus FAIL semantics",
    ):
        require(deprecation, token, label="deprecation policy")

    print(
        "Project governance docs: compatibility, changelog, and deprecation "
        "claims match executable package/lock contracts."
    )


def self_test() -> None:
    assert exact_pin(["openai-agents==1.2.3"], "openai-agents") == "1.2.3"
    try:
        exact_pin(["openai-agents>=1"], "openai-agents")
    except GovernanceDocsError:
        pass
    else:
        raise GovernanceDocsError("self-test accepted a non-exact integration pin")

    try:
        exact_pin(["mcp==1", "mcp==2"], "mcp")
    except GovernanceDocsError:
        pass
    else:
        raise GovernanceDocsError("self-test accepted duplicate exact pins")

    print("Project governance docs self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        if args.self_test:
            self_test()
        else:
            validate()
        return 0
    except GovernanceDocsError as exc:
        raise SystemExit(f"project governance docs contract failed: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
