from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

SUPPORTED_PYTHONS = ("3.11", "3.12", "3.13", "3.14")
REQUIRES_PYTHON = ">=3.11,<3.15"
RUNNER = "ubuntu-24.04"
REQUIRED_JOBS = (
    "policy",
    "quality",
    "openai-adapter",
    "mcp-lab",
    "mcp-remote-auth",
    "mcp-oauth-flow",
    "package",
    "package-reverify",
)
_WORKFLOW_USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)", flags=re.MULTILINE)


def fail(message: str) -> None:
    raise SystemExit(f"runtime policy contract failed: {message}")


def job_block(workflow: str, name: str, next_name: str | None) -> str:
    start_token = f"  {name}:\n"
    start = workflow.find(start_token)
    if start < 0:
        fail(f"ci.yml is missing job {name!r}")
    if next_name is None:
        return workflow[start:]
    end_token = f"  {next_name}:\n"
    end = workflow.find(end_token, start + len(start_token))
    if end < 0:
        fail(f"ci.yml is missing job {next_name!r} after {name!r}")
    return workflow[start:end]


def needs_result_reference(job: str) -> tuple[str, str]:
    return (f"needs.{job}.result", f"needs['{job}'].result")


def workflow_sources() -> dict[Path, str]:
    workflow_dir = Path(".github/workflows")
    paths = sorted({*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")})
    if not paths:
        fail("repository must contain at least one GitHub Actions workflow")
    sources: dict[Path, str] = {}
    for path in paths:
        try:
            sources[path] = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            fail(f"cannot read workflow {path.as_posix()!r}: {type(exc).__name__}")
    return sources


def validate_action_pins(sources: dict[Path, str]) -> None:
    found_action = False
    for path, source in sources.items():
        for action in _WORKFLOW_USES_RE.findall(source):
            found_action = True
            if re.fullmatch(r"[^@\s]+@[0-9a-f]{40}", action) is None:
                fail(
                    "every workflow action use must be pinned to a full commit SHA: "
                    f"{path.as_posix()}: {action!r}"
                )
    if not found_action:
        fail("GitHub Actions workflows contain no action uses declarations")


pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
workflows = workflow_sources()
ci_path = Path(".github/workflows/ci.yml")
workflow = workflows.get(ci_path)
if workflow is None:
    fail("repository must contain .github/workflows/ci.yml")
validate_action_pins(workflows)
project = pyproject["project"]

if project.get("requires-python") != REQUIRES_PYTHON:
    fail(f"project.requires-python must be exactly {REQUIRES_PYTHON!r}")

classifiers = set(project.get("classifiers", []))
expected_classifiers = {
    f"Programming Language :: Python :: {version}" for version in SUPPORTED_PYTHONS
}
missing = sorted(expected_classifiers - classifiers)
if missing:
    fail(f"pyproject.toml is missing supported-interpreter classifiers: {missing}")

unexpected_minor_classifiers = sorted(
    classifier
    for classifier in classifiers
    if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", classifier)
    and classifier not in expected_classifiers
)
if unexpected_minor_classifiers:
    fail(f"pyproject.toml advertises unqualified Python minors: {unexpected_minor_classifiers}")

pep561_marker = Path("src/agent_evals/py.typed")
advertises_inline_types = "Typing :: Typed" in classifiers
if advertises_inline_types and not pep561_marker.is_file():
    fail("Typing :: Typed requires the packaged src/agent_evals/py.typed marker")
if pep561_marker.exists() and not advertises_inline_types:
    fail("src/agent_evals/py.typed exists but pyproject.toml does not advertise Typing :: Typed")

if "ubuntu-latest" in workflow:
    fail("ci.yml must not use floating ubuntu-latest runners")
runner_values = re.findall(r"^\s+runs-on:\s*([^\s#]+)\s*$", workflow, flags=re.MULTILINE)
if not runner_values:
    fail("ci.yml contains no runs-on declarations")
if any(value != RUNNER for value in runner_values):
    fail(f"every CI job must use {RUNNER}; found {runner_values}")

quality = job_block(workflow, "quality", "openai-adapter")
matrix_match = re.search(r"python-version:\s*\[([^\]]+)\]", quality)
if matrix_match is None:
    fail("quality job must declare an explicit python-version matrix")
qualified = tuple(re.findall(r'"(3\.\d+)"', matrix_match.group(1)))
if qualified != SUPPORTED_PYTHONS:
    fail(f"quality matrix must qualify {SUPPORTED_PYTHONS}; found {qualified}")

policy = job_block(workflow, "policy", "quality")
if "python .github/scripts/validate_runtime_policy.py" not in policy:
    fail("policy job must execute validate_runtime_policy.py")

for job, next_job in (
    ("quality", "openai-adapter"),
    ("openai-adapter", "mcp-lab"),
    ("mcp-lab", "mcp-remote-auth"),
    ("mcp-remote-auth", "mcp-oauth-flow"),
    ("mcp-oauth-flow", "package"),
    ("package", "package-reverify"),
):
    block = job_block(workflow, job, next_job)
    if not re.search(r"^\s+needs:\s*policy\s*$", block, flags=re.MULTILINE):
        fail(f"{job} must depend on the repository policy job")

package = job_block(workflow, "package", "package-reverify")
if "package_artifact_manifest.py create" not in package:
    fail("package job must create the retained package artifact manifest")
if not any(
    action.startswith("actions/upload-artifact@") for action in _WORKFLOW_USES_RE.findall(package)
):
    fail("package job must upload the exact tested package artifact set")
if "package-artifacts-${{ github.run_id }}" not in package:
    fail("package artifact name must bind the workflow run ID")
if "overwrite: true" not in package:
    fail("package upload must explicitly replace a prior artifact on a rerun")
if "dist/artifact-manifest.json" not in package:
    fail("package upload must include artifact-manifest.json")

package_reverify = job_block(workflow, "package-reverify", "ci-gate")
if not re.search(r"^\s+needs:\s*package\s*$", package_reverify, flags=re.MULTILINE):
    fail("package-reverify must depend on the package job")
if not any(
    action.startswith("actions/download-artifact@")
    for action in _WORKFLOW_USES_RE.findall(package_reverify)
):
    fail("package-reverify must download the retained package artifact set")
if "package_artifact_manifest.py verify" not in package_reverify:
    fail("package-reverify must validate the retained artifact manifest")
if "package-artifacts-${{ github.run_id }}" not in package_reverify:
    fail("package-reverify must download the run-bound artifact")
if "python -m build" in package_reverify:
    fail("package-reverify must not rebuild package distributions")
if (
    "retained-dist/*.whl" not in package_reverify
    or "retained-dist/*.tar.gz" not in package_reverify
):
    fail("package-reverify must exercise the downloaded wheel and sdist")

ci_gate = job_block(workflow, "ci-gate", None)
if not re.search(r"^\s+if:\s*always\(\)\s*$", ci_gate, flags=re.MULTILINE):
    fail("ci-gate must run with if: always()")
for job in REQUIRED_JOBS:
    if f"      - {job}\n" not in ci_gate:
        fail(f"ci-gate needs list must include {job}")
    if not any(reference in ci_gate for reference in needs_result_reference(job)):
        fail(f"ci-gate must evaluate {job} result")

ci_action_uses = _WORKFLOW_USES_RE.findall(workflow)
if not any(action.startswith("actions/setup-python@") for action in ci_action_uses):
    fail("ci.yml must use actions/setup-python")
if not any(action.startswith("actions/checkout@") for action in ci_action_uses):
    fail("ci.yml must use actions/checkout")
if not any(action.startswith("actions/upload-artifact@") for action in ci_action_uses):
    fail("ci.yml must use actions/upload-artifact for retained package bytes")
if not any(action.startswith("actions/download-artifact@") for action in ci_action_uses):
    fail("ci.yml must use actions/download-artifact for package reverification")

print(
    "runtime policy validated: "
    f"python={','.join(SUPPORTED_PYTHONS)}; requires-python={REQUIRES_PYTHON}; "
    f"runner={RUNNER}; workflows={len(workflows)}; gate=ci-gate; "
    "package-artifacts=retained-and-reverified"
)
sys.exit(0)
