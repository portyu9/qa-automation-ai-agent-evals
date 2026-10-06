from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import tempfile
import tomllib
from importlib import metadata
from pathlib import Path

PROFILES = {
    "core": ("dev",),
    "mcp": ("dev", "mcp"),
    "openai-mcp": ("dev", "openai", "mcp"),
}
RUNTIME_EXTRAS = {
    "core": (),
    "mcp": ("mcp",),
    "openai-mcp": ("openai", "mcp"),
}
COMPATIBILITY_LOCK_CONTRACT = "agent-evals/dependency-compatibility-lock/v1"

GENERATOR_ENV = {
    "pip": "25.3",
    "pip-tools": "7.5.2",
}

_REQ_NAME_RE = re.compile(r"^([A-Za-z0-9_.-]+)")
_SPEC_RE = re.compile(r"(===|==|~=|>=|<=|!=|>|<)\s*([^,;\s]+)")


def _require_generator_environment() -> None:
    for distribution, expected in GENERATOR_ENV.items():
        try:
            actual = metadata.version(distribution)
        except metadata.PackageNotFoundError as exc:
            raise SystemExit(f"lock generator requires {distribution}=={expected}") from exc
        if actual != expected:
            raise SystemExit(f"lock generator requires {distribution}=={expected}; found {actual}")


def _canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def _requirement_name(requirement: str) -> str:
    match = _REQ_NAME_RE.match(requirement.strip())
    if match is None:
        raise SystemExit(f"cannot parse direct requirement: {requirement!r}")
    return _canonical_name(match.group(1))


def _requirement_specifiers(requirement: str) -> list[tuple[str, str]]:
    before_marker = requirement.split(";", 1)[0].strip()
    return _SPEC_RE.findall(before_marker)


def _exact_pin(requirement: str) -> str | None:
    specifiers = _requirement_specifiers(requirement)
    if len(specifiers) != 1 or specifiers[0][0] not in {"==", "==="}:
        return None
    return specifiers[0][1]


def _minimum_runtime_requirement(requirement: str) -> str:
    exact = _exact_pin(requirement)
    if exact is not None:
        return requirement

    if "[" in requirement.split(";", 1)[0]:
        raise SystemExit(
            "compatibility lock generation does not silently rewrite direct requirements with extras: "
            f"{requirement!r}"
        )
    specifiers = _requirement_specifiers(requirement)
    lowers = [version for operator, version in specifiers if operator == ">="]
    if len(lowers) != 1:
        raise SystemExit(
            "minimum compatibility generation requires exactly one inclusive >= lower bound "
            f"for ranged runtime dependency {requirement!r}"
        )
    unsupported = sorted({operator for operator, _ in specifiers if operator in {"~=", ">"}})
    if unsupported:
        raise SystemExit(
            "minimum compatibility generation does not infer an exact floor from "
            f"{unsupported}: {requirement!r}"
        )
    marker = ""
    if ";" in requirement:
        marker = ";" + requirement.split(";", 1)[1]
    return f"{_requirement_name(requirement)}=={lowers[0]}{marker}"


def _project_inputs(root: Path) -> tuple[dict[str, object], list[str]]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    build_manifest_lines: list[str] = []
    for raw in (root / "requirements-dev-ci-build.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            build_manifest_lines.append(line)
    return pyproject, build_manifest_lines


def _dedupe_requirements(requirements: list[str]) -> list[str]:
    normalized: dict[str, str] = {}
    for requirement in requirements:
        name = _requirement_name(requirement)
        previous = normalized.get(name)
        if previous is not None and previous != requirement:
            raise SystemExit(
                f"conflicting direct requirements for {name}: {previous!r} != {requirement!r}"
            )
        normalized[name] = requirement
    return sorted(normalized.values(), key=str.lower)


def _snapshot_requirement_lines(root: Path, profile: str) -> list[str]:
    pyproject, build_manifest_lines = _project_inputs(root)
    project = pyproject["project"]
    build_system = pyproject["build-system"]
    optional = project.get("optional-dependencies", {})
    requirements = list(project["dependencies"])
    for extra in PROFILES[profile]:
        requirements.extend(optional[extra])
    requirements.extend(build_system["requires"])
    requirements.extend(build_manifest_lines)
    return _dedupe_requirements(requirements)


def _compatibility_requirement_lines(root: Path, profile: str, boundary: str) -> list[str]:
    pyproject, build_manifest_lines = _project_inputs(root)
    project = pyproject["project"]
    build_system = pyproject["build-system"]
    optional = project.get("optional-dependencies", {})

    runtime = list(project["dependencies"])
    for extra in RUNTIME_EXTRAS[profile]:
        runtime.extend(optional[extra])

    if boundary == "minimum":
        runtime = [_minimum_runtime_requirement(requirement) for requirement in runtime]
    elif boundary != "latest":
        raise SystemExit(f"unsupported compatibility boundary: {boundary}")

    tooling = list(optional["dev"])
    tooling.extend(build_system["requires"])
    tooling.extend(build_manifest_lines)
    return _dedupe_requirements([*runtime, *tooling])


def _input_digest(requirements: list[str]) -> str:
    payload = ("\n".join(requirements) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_header(
    path: Path,
    *,
    profile: str,
    boundary: str | None,
    input_digest: str | None,
) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    first_requirement = next(
        (index for index, line in enumerate(lines) if line and not line.startswith("#")),
        None,
    )
    if first_requirement is None:
        raise SystemExit("generated lock contains no requirements")

    if boundary is None:
        header = [
            "# Generated by .github/scripts/generate_ci_lock.py",
            f"# Profile: {profile}",
            f"# Python: {sys.version_info.major}.{sys.version_info.minor}",
            "# Compiler: pip==25.3; pip-tools==7.5.2",
            "# Regeneration contract: CI_DEPENDENCY_LOCKS.md",
            "",
        ]
    else:
        if input_digest is None:
            raise SystemExit("compatibility lock header requires an input digest")
        header = [
            "# Generated by .github/scripts/generate_ci_lock.py",
            f"# Lock-Contract: {COMPATIBILITY_LOCK_CONTRACT}",
            f"# Profile: {profile}",
            f"# Boundary: {boundary}",
            f"# Python: {sys.version_info.major}.{sys.version_info.minor}",
            f"# Input-SHA256: {input_digest}",
            "# Compiler: pip==25.3; pip-tools==7.5.2",
            "# Regeneration contract: CI_DEPENDENCY_LOCKS.md",
            "",
        ]
    path.write_text("\n".join([*header, *lines[first_requirement:]]) + "\n", encoding="utf-8")


def generate(root: Path, profile: str, output: Path, *, boundary: str | None = None) -> None:
    if profile not in PROFILES:
        raise SystemExit(f"unsupported lock profile: {profile}")
    _require_generator_environment()
    if boundary is None:
        lines = _snapshot_requirement_lines(root, profile)
        digest = None
    else:
        lines = _compatibility_requirement_lines(root, profile, boundary)
        digest = _input_digest(lines)

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agent-evals-lock-") as tmp:
        source = Path(tmp) / f"{profile}-{boundary or 'snapshot'}.in"
        source.write_text("\n".join(lines) + "\n", encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "piptools",
            "compile",
            "--generate-hashes",
            "--resolver=backtracking",
            "--strip-extras",
            "--allow-unsafe",
            "--no-emit-index-url",
            "--no-emit-trusted-host",
            "--output-file",
            str(output),
            str(source),
        ]
        subprocess.run(command, cwd=root, check=True)
    _normalize_header(output, profile=profile, boundary=boundary, input_digest=digest)
    text = output.read_text(encoding="utf-8")
    if "--hash=sha256:" not in text:
        raise SystemExit("generated lock does not contain SHA-256 hashes")
    for line in text.splitlines():
        requirement = line.strip()
        if requirement.startswith("-e ") or " @ file:" in requirement:
            raise SystemExit("generated lock unexpectedly contains local/editable material")
    label = f"{profile}/{boundary}" if boundary is not None else profile
    print(f"generated {output} for {label} under Python {sys.version.split()[0]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    parser.add_argument("--boundary", choices=("minimum", "latest"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    generate(root, args.profile, args.output, boundary=args.boundary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
