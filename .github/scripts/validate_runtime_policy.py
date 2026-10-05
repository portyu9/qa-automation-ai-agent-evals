from __future__ import annotations

import json
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
    "mutation",
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
publish_release_path = Path(".github/workflows/publish-release.yml")
publish_release = workflows.get(publish_release_path)
if publish_release is None:
    fail("repository must contain .github/workflows/publish-release.yml")
validate_action_pins(workflows)
project = pyproject["project"]
pytest_options = pyproject.get("tool", {}).get("pytest", {}).get("ini_options", {})
pytest_addopts = pytest_options.get("addopts")
if not isinstance(pytest_addopts, str) or "not fuzz" not in pytest_addopts:
    fail("ordinary pytest addopts must exclude the deep fuzz marker")
pytest_markers = pytest_options.get("markers")
if not isinstance(pytest_markers, list) or not any(
    isinstance(marker, str) and marker.startswith("fuzz:") for marker in pytest_markers
):
    fail("pyproject.toml must register the fuzz marker")

deep_fuzz_path = Path(".github/workflows/deep-fuzz.yml")
deep_fuzz = workflows.get(deep_fuzz_path)
if deep_fuzz is None:
    fail("repository must contain .github/workflows/deep-fuzz.yml")
for required in (
    "name: Deep fuzz assurance",
    "workflow_dispatch:",
    "schedule:",
    "pull_request:",
    "runs-on: ubuntu-24.04",
    "timeout-minutes: 90",
    "EXACT_COMMIT: ${{ github.event.pull_request.head.sha || github.sha }}",
    "FUZZ_SEED: ${{ github.run_id }}",
    "persist-credentials: false",
    ".[dev,mcp]",
    "-m fuzz",
    "tests/fuzz",
    '--hypothesis-seed="$FUZZ_SEED"',
    "if: always()",
    "retention-days: 21",
):
    if required not in deep_fuzz:
        fail(f"deep-fuzz workflow is missing required contract text: {required}")
if "\npush:" in deep_fuzz or "\n  push:" in deep_fuzz:
    fail("deep-fuzz workflow must not run on every push")

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
for required in (
    "--cov-branch",
    "--cov-report=json:coverage-core.json",
    "check_coverage_policy.py",
    "--coverage coverage-core.json",
    "--profile core-trust",
):
    if required not in quality:
        fail(f"quality job is missing trust-class coverage contract text: {required}")
matrix_match = re.search(r"python-version:\s*\[([^\]]+)\]", quality)
if matrix_match is None:
    fail("quality job must declare an explicit python-version matrix")
qualified = tuple(re.findall(r'"(3\.\d+)"', matrix_match.group(1)))
if qualified != SUPPORTED_PYTHONS:
    fail(f"quality matrix must qualify {SUPPORTED_PYTHONS}; found {qualified}")

policy = job_block(workflow, "policy", "quality")
if "python .github/scripts/validate_runtime_policy.py" not in policy:
    fail("policy job must execute validate_runtime_policy.py")
if "python .github/scripts/release_candidate.py self-test" not in policy:
    fail("policy job must self-test retained release candidate validation")
if "python .github/scripts/check_coverage_policy.py --self-test" not in policy:
    fail("policy job must self-test the module-specific coverage policy")

coverage_manifest_path = Path(".github/coverage/thresholds.json")
try:
    coverage_manifest = json.loads(coverage_manifest_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    fail(f"cannot read coverage threshold manifest: {type(exc).__name__}")
if not isinstance(coverage_manifest, dict) or coverage_manifest.get("schema_version") != 1:
    fail("coverage threshold manifest must use schema_version 1")
coverage_profiles = coverage_manifest.get("profiles")
if not isinstance(coverage_profiles, dict):
    fail("coverage threshold manifest must contain profiles")
expected_coverage_profiles = {
    "core-trust",
    "openai",
    "mcp-lab",
    "mcp-remote-auth",
    "mcp-oauth",
}
if set(coverage_profiles) != expected_coverage_profiles:
    fail(
        "coverage profile set mismatch: "
        f"expected={sorted(expected_coverage_profiles)}, found={sorted(coverage_profiles)}"
    )
optional_profile_files: set[str] = set()
for profile_id, profile_payload in coverage_profiles.items():
    if not isinstance(profile_payload, dict) or not isinstance(profile_payload.get("files"), dict):
        fail(f"coverage profile {profile_id!r} must declare files")
    if profile_id != "core-trust":
        optional_profile_files.update(profile_payload["files"])
coverage_run = pyproject.get("tool", {}).get("coverage", {}).get("run", {})
omitted_core_files = set(coverage_run.get("omit", []))
if optional_profile_files != omitted_core_files:
    fail(
        "optional coverage profiles must exactly cover the core-coverage omit set: "
        f"missing={sorted(omitted_core_files - optional_profile_files)}, "
        f"unexpected={sorted(optional_profile_files - omitted_core_files)}"
    )

if "name: Publish retained release" not in publish_release:
    fail("publish-release workflow must use the canonical workflow name")
if (
    "repository_dispatch:" not in publish_release
    or "types: [release-request]" not in publish_release
):
    fail("publish-release must use the default-branch-bound release-request repository_dispatch")
if "workflow_dispatch:" in publish_release or "workflow_run:" in publish_release:
    fail("publish-release must not expose selectable-ref or upstream-workflow execution surfaces")
if "permissions:\n  actions: read\n  contents: write" not in publish_release:
    fail("publish-release must grant only actions-read/contents-write authority")
if (
    "group: retained-release-publication" not in publish_release
    or "cancel-in-progress: false" not in publish_release
):
    fail("publish-release must serialize release publication attempts without cancellation")
if "if: github.ref == 'refs/heads/main'" not in publish_release:
    fail("publish-release job must fail closed unless the dispatch ref is main")
if not any(
    action.startswith("actions/checkout@") for action in _WORKFLOW_USES_RE.findall(publish_release)
):
    fail("publish-release must checkout exact dispatch-time default-branch release logic")
if "ref: ${{ github.sha }}" not in publish_release:
    fail("publish-release checkout must bind to the repository_dispatch default-branch SHA")
if "persist-credentials: false" not in publish_release:
    fail("publish-release checkout must not persist repository credentials")
if "github.event.client_payload" in publish_release:
    fail(
        "publish-release must parse client payload as event-file data, not interpolate it into shell"
    )
for required in (
    "release_candidate.py self-test",
    "release_candidate.py validate",
    '--workflow-ref "$GITHUB_REF"',
    '--workflow-sha "$GITHUB_SHA"',
    "package-artifacts-${{ steps.candidate.outputs.ci_run_id }}",
    "run-id: ${{ steps.candidate.outputs.ci_run_id }}",
    "github-token: ${{ secrets.GITHUB_TOKEN }}",
    "package_artifact_manifest.py verify",
    '--workflow "CI"',
    "retained-dist/*.whl",
    "retained-dist/*.tar.gz",
    "retained-dist/artifact-manifest.json",
    "gh release create",
    "--verify-tag",
):
    if required not in publish_release:
        fail(f"publish-release workflow is missing required contract text: {required}")
if publish_release.count("release_candidate.py validate") < 2:
    fail("publish-release must revalidate tag/release state immediately before publication")
for forbidden in ("python -m build", "twine upload", "uv publish", "pypi.org"):
    if forbidden in publish_release.lower():
        fail(f"publish-release workflow contains forbidden release behavior: {forbidden}")

for job, next_job, coverage_profile, coverage_report in (
    ("quality", "openai-adapter", None, None),
    ("openai-adapter", "mcp-lab", "openai", "coverage-openai.json"),
    ("mcp-lab", "mcp-remote-auth", "mcp-lab", "coverage-mcp-lab.json"),
    (
        "mcp-remote-auth",
        "mcp-oauth-flow",
        "mcp-remote-auth",
        "coverage-mcp-remote-auth.json",
    ),
    ("mcp-oauth-flow", "package", "mcp-oauth", "coverage-mcp-oauth.json"),
    ("package", "package-reverify", None, None),
):
    block = job_block(workflow, job, next_job)
    if not re.search(r"^\s+needs:\s*policy\s*$", block, flags=re.MULTILINE):
        fail(f"{job} must depend on the repository policy job")
    if coverage_profile is not None and coverage_report is not None:
        for required in (
            "--cov-branch",
            "--cov-config=.github/coverage/optional.coveragerc",
            f"--cov-report=json:{coverage_report}",
            "check_coverage_policy.py",
            f"--coverage {coverage_report}",
            f"--profile {coverage_profile}",
        ):
            if required not in block:
                fail(f"{job} is missing optional-module coverage contract text: {required}")

package = job_block(workflow, "package", "package-reverify")
if "name: Package build and inspection" not in package:
    fail("package job must use the non-protected Package build and inspection check name")
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

ci_gate = job_block(workflow, "ci-gate", "protected-gate")
if not re.search(r"^\s+if:\s*always\(\)\s*$", ci_gate, flags=re.MULTILINE):
    fail("ci-gate must run with if: always()")
for job in REQUIRED_JOBS:
    if f"      - {job}\n" not in ci_gate:
        fail(f"ci-gate needs list must include {job}")
    if not any(reference in ci_gate for reference in needs_result_reference(job)):
        fail(f"ci-gate must evaluate {job} result")

protected_gate = job_block(workflow, "protected-gate", None)
if "name: Package integrity" not in protected_gate:
    fail("protected-gate must retain the ruleset-bound Package integrity check name")
if not re.search(r"^\s+if:\s*always\(\)\s*$", protected_gate, flags=re.MULTILINE):
    fail("protected-gate must run with if: always()")
if "      - ci-gate\n" not in protected_gate:
    fail("protected-gate must depend on ci-gate")
if not any(reference in protected_gate for reference in needs_result_reference("ci-gate")):
    fail("protected-gate must explicitly evaluate the ci-gate result")
if "actions: read" not in protected_gate:
    fail("protected-gate must have Actions read permission for exact-subject evidence")
if not any(
    action.startswith("actions/checkout@") for action in _WORKFLOW_USES_RE.findall(protected_gate)
):
    fail("protected-gate must checkout its exact workflow subject without floating action refs")
if "persist-credentials: false" not in protected_gate:
    fail("protected-gate checkout must not persist repository credentials")
if "verify_required_codeql.py --self-test" not in protected_gate:
    fail("protected-gate must self-test the exact-subject CodeQL bridge")
if "python .github/scripts/verify_required_codeql.py" not in protected_gate:
    fail("protected-gate must enforce exact-subject CodeQL success")
for expression in (
    "github.event.pull_request.head.sha || github.sha",
    "github.event.pull_request.head.ref || github.ref_name",
    "github.event_name",
):
    if expression not in protected_gate:
        fail(f"protected-gate is missing exact-subject binding expression: {expression}")

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
    f"runner={RUNNER}; workflows={len(workflows)}; gate=ci-gate+protected-codeql; "
    "package-artifacts=retained-reverified-and-default-branch-published"
)
sys.exit(0)
