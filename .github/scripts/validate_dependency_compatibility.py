from __future__ import annotations

import hashlib
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK_DIR = ROOT / "requirements" / "compatibility"
CONTRACT = "agent-evals/dependency-compatibility-lock/v1"
EXPECTED = {
    "core-minimum-py311.txt": ("core", "minimum", "3.11", ()),
    "core-latest-py311.txt": ("core", "latest", "3.11", ()),
    "mcp-minimum-py311.txt": ("mcp", "minimum", "3.11", ("mcp",)),
    "mcp-latest-py311.txt": ("mcp", "latest", "3.11", ("mcp",)),
    "openai-mcp-minimum-py311.txt": (
        "openai-mcp",
        "minimum",
        "3.11",
        ("openai", "mcp"),
    ),
    "openai-mcp-latest-py311.txt": (
        "openai-mcp",
        "latest",
        "3.11",
        ("openai", "mcp"),
    ),
}
HASH_RE = re.compile(r"--hash=sha256:[0-9a-f]{64}(?:\s|$)")
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\;]+)(?:\s*;.*)?(?:\s*\\)?$")
REQ_NAME_RE = re.compile(r"^([A-Za-z0-9_.-]+)")
SPEC_RE = re.compile(r"(===|==|~=|>=|<=|!=|>|<)\s*([^,;\s]+)")


class CompatibilityPolicyError(ValueError):
    pass


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def requirement_name(requirement: str) -> str:
    match = REQ_NAME_RE.match(requirement.strip())
    if match is None:
        raise CompatibilityPolicyError(f"cannot parse direct requirement: {requirement!r}")
    return canonical_name(match.group(1))


def requirement_specifiers(requirement: str) -> list[tuple[str, str]]:
    return SPEC_RE.findall(requirement.split(";", 1)[0].strip())


def exact_pin(requirement: str) -> str | None:
    specifiers = requirement_specifiers(requirement)
    if len(specifiers) != 1 or specifiers[0][0] not in {"==", "==="}:
        return None
    return specifiers[0][1]


def minimum_requirement(requirement: str) -> str:
    exact = exact_pin(requirement)
    if exact is not None:
        return requirement
    specifiers = requirement_specifiers(requirement)
    lowers = [version for operator, version in specifiers if operator == ">="]
    if len(lowers) != 1:
        raise CompatibilityPolicyError(
            "minimum compatibility requires exactly one inclusive >= lower bound: "
            f"{requirement!r}"
        )
    unsupported = sorted({operator for operator, _ in specifiers if operator in {"~=", ">"}})
    if unsupported:
        raise CompatibilityPolicyError(
            f"minimum compatibility cannot infer a floor from {unsupported}: {requirement!r}"
        )
    marker = ""
    if ";" in requirement:
        marker = ";" + requirement.split(";", 1)[1]
    return f"{requirement_name(requirement)}=={lowers[0]}{marker}"


def dedupe(requirements: list[str]) -> list[str]:
    normalized: dict[str, str] = {}
    for requirement in requirements:
        name = requirement_name(requirement)
        previous = normalized.get(name)
        if previous is not None and previous != requirement:
            raise CompatibilityPolicyError(
                f"conflicting direct requirements for {name}: {previous!r} != {requirement!r}"
            )
        normalized[name] = requirement
    return sorted(normalized.values(), key=str.lower)


def project_inputs(
    profile_extras: tuple[str, ...],
    boundary: str,
) -> tuple[list[str], list[str]]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    optional = project.get("optional-dependencies", {})
    runtime = list(project["dependencies"])
    for extra in profile_extras:
        runtime.extend(optional[extra])

    if boundary == "minimum":
        transformed_runtime = [minimum_requirement(requirement) for requirement in runtime]
    elif boundary == "latest":
        transformed_runtime = runtime
    else:
        raise CompatibilityPolicyError(f"unsupported boundary: {boundary}")

    tooling = list(optional["dev"])
    tooling.extend(pyproject["build-system"]["requires"])
    for raw in (ROOT / "requirements-dev-ci-build.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            tooling.append(line)

    return dedupe(transformed_runtime), dedupe([*transformed_runtime, *tooling])


def input_digest(requirements: list[str]) -> str:
    return hashlib.sha256(("\n".join(requirements) + "\n").encode("utf-8")).hexdigest()


def parse_header(raw: str, *, filename: str) -> dict[str, str]:
    header: dict[str, str] = {}
    for line in raw.splitlines()[:10]:
        if not line.startswith("# "):
            continue
        body = line[2:]
        if ": " not in body:
            continue
        key, value = body.split(": ", 1)
        if key in header:
            raise CompatibilityPolicyError(f"{filename} duplicates header field {key}")
        header[key] = value
    required = {
        "Lock-Contract",
        "Profile",
        "Boundary",
        "Python",
        "Input-SHA256",
        "Compiler",
        "Regeneration contract",
    }
    missing = sorted(required - set(header))
    if missing:
        raise CompatibilityPolicyError(f"{filename} missing header fields: {missing}")
    return header


def parse_lock(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    raw = path.read_text(encoding="utf-8")
    if "--hash=sha256:" not in raw:
        raise CompatibilityPolicyError(f"{path.name} contains no SHA-256 hashes")
    for forbidden in (
        "--index-url",
        "--extra-index-url",
        "--trusted-host",
        " @ file:",
        "\n-e ",
    ):
        if forbidden in raw:
            raise CompatibilityPolicyError(
                f"{path.name} contains forbidden requirement source: {forbidden!r}"
            )

    pins: dict[str, str] = {}
    starts: list[tuple[int, str]] = []
    lines = raw.splitlines()
    for index, line in enumerate(lines):
        if line[:1].isspace() or not line or line.startswith("#"):
            continue
        match = PIN_RE.match(line)
        if match is None:
            raise CompatibilityPolicyError(
                f"{path.name} contains a non-exact requirement line: {line!r}"
            )
        name = canonical_name(match.group(1))
        if name in pins:
            raise CompatibilityPolicyError(f"{path.name} contains duplicate pin: {name}")
        pins[name] = match.group(2)
        starts.append((index, name))
    if not pins:
        raise CompatibilityPolicyError(f"{path.name} has no package pins")

    for offset, (start, name) in enumerate(starts):
        end = starts[offset + 1][0] if offset + 1 < len(starts) else len(lines)
        if HASH_RE.search("\n".join(lines[start:end])) is None:
            raise CompatibilityPolicyError(
                f"{path.name} package pin lacks a SHA-256 hash: {name}"
            )
    return parse_header(raw, filename=path.name), pins


def numeric_version(value: str) -> tuple[int, ...]:
    if re.fullmatch(r"\d+(?:\.\d+)*", value) is None:
        raise CompatibilityPolicyError(
            f"direct compatibility version is outside the supported numeric policy subset: {value!r}"
        )
    return tuple(int(piece) for piece in value.split("."))


def compare_versions(left: str, right: str) -> int:
    a = numeric_version(left)
    b = numeric_version(right)
    width = max(len(a), len(b))
    aa = a + (0,) * (width - len(a))
    bb = b + (0,) * (width - len(b))
    return (aa > bb) - (aa < bb)


def satisfies(version: str, requirement: str) -> bool:
    specifiers = requirement_specifiers(requirement)
    if not specifiers:
        raise CompatibilityPolicyError(f"requirement has no supported specifier: {requirement!r}")
    for operator, expected in specifiers:
        comparison = compare_versions(version, expected)
        if operator in {"==", "==="} and comparison != 0:
            return False
        if operator == ">=" and comparison < 0:
            return False
        if operator == "<=" and comparison > 0:
            return False
        if operator == ">" and comparison <= 0:
            return False
        if operator == "<" and comparison >= 0:
            return False
        if operator == "!=" and comparison == 0:
            return False
        if operator == "~=":
            raise CompatibilityPolicyError(
                f"compatible-release specifier is not accepted in compatibility policy: {requirement!r}"
            )
    return True


def validate_profile(
    filename: str,
    *,
    profile: str,
    boundary: str,
    python_version: str,
    extras: tuple[str, ...],
) -> dict[str, str]:
    path = LOCK_DIR / filename
    header, pins = parse_lock(path)
    expected_header = {
        "Lock-Contract": CONTRACT,
        "Profile": profile,
        "Boundary": boundary,
        "Python": python_version,
        "Compiler": "pip==25.3; pip-tools==7.5.2",
        "Regeneration contract": "CI_DEPENDENCY_LOCKS.md",
    }
    for key, expected in expected_header.items():
        if header.get(key) != expected:
            raise CompatibilityPolicyError(
                f"{filename} header {key!r} mismatch: {header.get(key)!r} != {expected!r}"
            )
    if re.fullmatch(r"[0-9a-f]{64}", header["Input-SHA256"]) is None:
        raise CompatibilityPolicyError(f"{filename} Input-SHA256 is not canonical SHA-256")

    runtime, generator_inputs = project_inputs(extras, boundary)
    expected_digest = input_digest(generator_inputs)
    if header["Input-SHA256"] != expected_digest:
        raise CompatibilityPolicyError(
            f"{filename} source-input digest drift: "
            f"{header['Input-SHA256']} != {expected_digest}"
        )

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    optional = project.get("optional-dependencies", {})
    declared_runtime = list(project["dependencies"])
    for extra in extras:
        declared_runtime.extend(optional[extra])

    expected_direct_names = {requirement_name(item) for item in declared_runtime}
    missing = sorted(expected_direct_names - set(pins))
    if missing:
        raise CompatibilityPolicyError(f"{filename} is missing direct runtime pins: {missing}")

    transformed_by_name = {requirement_name(item): item for item in runtime}
    declared_by_name = {requirement_name(item): item for item in declared_runtime}
    for name in sorted(expected_direct_names):
        declared = declared_by_name[name]
        exact = exact_pin(declared)
        if exact is not None:
            if pins[name] != exact:
                raise CompatibilityPolicyError(
                    f"{filename} exact direct pin drift for {name}: {pins[name]} != {exact}"
                )
            continue
        if boundary == "minimum":
            minimum = exact_pin(transformed_by_name[name])
            if minimum is None or pins[name] != minimum:
                raise CompatibilityPolicyError(
                    f"{filename} minimum direct pin drift for {name}: "
                    f"{pins[name]} != {minimum}"
                )
        elif not satisfies(pins[name], declared):
            raise CompatibilityPolicyError(
                f"{filename} latest direct pin violates declared range for {name}: "
                f"{pins[name]} not in {declared!r}"
            )

    return pins


def validate() -> None:
    actual = {path.name for path in LOCK_DIR.glob("*.txt") if path.is_file()}
    if actual != set(EXPECTED):
        raise CompatibilityPolicyError(
            f"compatibility profile set mismatch: "
            f"missing={sorted(set(EXPECTED) - actual)}, extra={sorted(actual - set(EXPECTED))}"
        )

    parsed: dict[str, dict[str, str]] = {}
    for filename, (profile, boundary, python_version, extras) in EXPECTED.items():
        parsed[filename] = validate_profile(
            filename,
            profile=profile,
            boundary=boundary,
            python_version=python_version,
            extras=extras,
        )

    forbidden_core = {"mcp", "httpx2", "openai", "openai-agents", "starlette", "uvicorn"}
    for boundary in ("minimum", "latest"):
        core = parsed[f"core-{boundary}-py311.txt"]
        contaminated = sorted(forbidden_core & set(core))
        if contaminated:
            raise CompatibilityPolicyError(
                f"core {boundary} compatibility lock contains optional packages: {contaminated}"
            )

        mcp = parsed[f"mcp-{boundary}-py311.txt"]
        if {"openai", "openai-agents"} & set(mcp):
            raise CompatibilityPolicyError(
                f"MCP {boundary} compatibility lock is contaminated by OpenAI packages"
            )
        for required in ("mcp", "httpx2", "starlette", "uvicorn"):
            if required not in mcp:
                raise CompatibilityPolicyError(
                    f"MCP {boundary} compatibility lock is missing {required}"
                )

        combined = parsed[f"openai-mcp-{boundary}-py311.txt"]
        for required in ("mcp", "httpx2", "starlette", "uvicorn", "openai-agents"):
            if required not in combined:
                raise CompatibilityPolicyError(
                    f"OpenAI+MCP {boundary} compatibility lock is missing {required}"
                )

    print(
        "dependency compatibility policy validated: "
        "profiles=core,mcp,openai-mcp; boundaries=minimum,latest; python=3.11; "
        "execution=committed-sha256-locks"
    )


def self_test() -> None:
    assert compare_versions("2.12.0", "2.12") == 0
    assert satisfies("2.12.0", "pydantic>=2.12.0,<3")
    assert not satisfies("3.0", "pydantic>=2.12.0,<3")
    assert exact_pin("mcp==2.2.0") == "2.2.0"
    assert minimum_requirement("pydantic>=2.12.0,<3") == "pydantic==2.12.0"
    try:
        minimum_requirement("example>1,<2")
    except CompatibilityPolicyError:
        pass
    else:
        raise AssertionError("exclusive lower bounds must fail closed")
    print("dependency compatibility policy self-test passed")


def main() -> int:
    try:
        if "--self-test" in sys.argv[1:]:
            self_test()
        else:
            validate()
    except (
        CompatibilityPolicyError,
        OSError,
        KeyError,
        TypeError,
        tomllib.TOMLDecodeError,
    ) as exc:
        raise SystemExit(f"dependency compatibility policy failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
