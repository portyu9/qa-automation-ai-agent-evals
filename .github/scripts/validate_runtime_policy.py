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
)


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


pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
project = pyproject["project"]

if project.get("requires-python") != REQUIRES_PYTHON:
    fail(f"project.requires-python must be exactly {REQUIRES_PYTHON!r}")

classifiers = set(project.get("classifiers", []))
expected_classifiers = {f"Programming Language :: Python :: {version}" for version in SUPPORTED_PYTHONS}
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
qualified = tuple(re.findall(r"\"(3\.\d+)\"", matrix_match.group(1)))
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
    ("package", "ci-gate"),
):
    block = job_block(workflow, job, next_job)
    if not re.search(r"^\s+needs:\s*policy\s*$", block, flags=re.MULTILINE):
        fail(f"{job} must depend on the repository policy job")

ci_gate = job_block(workflow, "ci-gate", None)
if not re.search(r"^\s+if:\s*always\(\)\s*$", ci_gate, flags=re.MULTILINE):
    fail("ci-gate must run with if: always()")
for job in REQUIRED_JOBS:
    if f"      - {job}\n" not in ci_gate:
        fail(f"ci-gate needs list must include {job}")
    if not any(reference in ci_gate for reference in needs_result_reference(job)):
        fail(f"ci-gate must evaluate {job} result")

setup_python_uses = re.findall(r"uses:\s*actions/setup-python@([^\s#]+)", workflow)
if not setup_python_uses:
    fail("ci.yml must use actions/setup-python")
if any(re.fullmatch(r"[0-9a-f]{40}", ref) is None for ref in setup_python_uses):
    fail("every actions/setup-python use must be pinned to a full commit SHA")

checkout_uses = re.findall(r"uses:\s*actions/checkout@([^\s#]+)", workflow)
if not checkout_uses:
    fail("ci.yml must use actions/checkout")
if any(re.fullmatch(r"[0-9a-f]{40}", ref) is None for ref in checkout_uses):
    fail("every actions/checkout use must be pinned to a full commit SHA")

print(
    "runtime policy validated: "
    f"python={','.join(SUPPORTED_PYTHONS)}; requires-python={REQUIRES_PYTHON}; "
    f"runner={RUNNER}; gate=ci-gate"
)
sys.exit(0)
