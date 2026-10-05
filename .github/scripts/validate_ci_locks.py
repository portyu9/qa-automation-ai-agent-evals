from __future__ import annotations

import re
import tomllib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
LOCK_DIR = ROOT / "requirements" / "locks"
EXPECTED = {
    "core-py311.txt": ("3.11", ("dev",)),
    "core-py312.txt": ("3.12", ("dev",)),
    "core-py313.txt": ("3.13", ("dev",)),
    "core-py314.txt": ("3.14", ("dev",)),
    "mcp-py311.txt": ("3.11", ("dev", "mcp")),
    "openai-mcp-py311.txt": ("3.11", ("dev", "openai", "mcp")),
}
HASH_RE = re.compile(r"--hash=sha256:[0-9a-f]{64}(?:\s|$)")
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\;]+)(?:\s*;.*)?(?:\s*\\)?$")
REQ_NAME_RE = re.compile(r"^([A-Za-z0-9_.-]+)")


class LockPolicyError(ValueError):
    pass


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def source_requirements(profile_extras: tuple[str, ...]) -> list[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    requirements = list(project["dependencies"])
    optional = project.get("optional-dependencies", {})
    for extra in profile_extras:
        requirements.extend(optional[extra])
    requirements.extend(pyproject["build-system"]["requires"])
    for raw in (ROOT / "requirements-dev-ci-build.txt").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            requirements.append(line)
    return requirements


def requirement_name(requirement: str) -> str:
    match = REQ_NAME_RE.match(requirement.strip())
    if match is None:
        raise LockPolicyError(f"cannot parse direct requirement: {requirement!r}")
    return canonical_name(match.group(1))


def exact_pin(requirement: str) -> str | None:
    text = requirement.strip()
    name = requirement_name(text)
    match = re.match(r"^[A-Za-z0-9_.-]+==([^,;\s]+)(?:\s*;.*)?$", text)
    if match is None:
        return None
    return f"{name}=={match.group(1)}"


def parse_lock(path: Path, expected_python: str) -> dict[str, str]:
    raw = path.read_text(encoding="utf-8")
    if not any(f"Python {expected_python}" in line for line in raw.splitlines()[1:6]):
        raise LockPolicyError(f"{path.name} is not generated for Python {expected_python}")
    if "--hash=sha256:" not in raw:
        raise LockPolicyError(f"{path.name} contains no SHA-256 hashes")
    for forbidden in ("--index-url", "--extra-index-url", "--trusted-host", " @ file:", "\n-e "):
        if forbidden in raw:
            raise LockPolicyError(f"{path.name} contains forbidden requirement source: {forbidden!r}")

    lines = raw.splitlines()
    pins: dict[str, str] = {}
    starts: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        if line[:1].isspace() or not line or line.startswith("#"):
            continue
        match = PIN_RE.match(line)
        if match is None:
            raise LockPolicyError(f"{path.name} contains a non-exact requirement line: {line!r}")
        name = canonical_name(match.group(1))
        version = match.group(2)
        if name in pins:
            raise LockPolicyError(f"{path.name} contains duplicate package pin: {name}")
        pins[name] = version
        starts.append((index, name, version))

    if not pins:
        raise LockPolicyError(f"{path.name} has no package pins")
    for offset, (start, name, _version) in enumerate(starts):
        end = starts[offset + 1][0] if offset + 1 < len(starts) else len(lines)
        block = "\n".join(lines[start:end])
        if HASH_RE.search(block) is None:
            raise LockPolicyError(f"{path.name} package pin lacks a SHA-256 hash: {name}")
    return pins


def validate() -> None:
    actual = {path.name for path in LOCK_DIR.glob("*.txt") if path.is_file()}
    if actual != set(EXPECTED):
        raise LockPolicyError(
            f"lock profile set mismatch: missing={sorted(set(EXPECTED) - actual)}, "
            f"extra={sorted(actual - set(EXPECTED))}"
        )

    parsed: dict[str, dict[str, str]] = {}
    for filename, (python_version, extras) in EXPECTED.items():
        pins = parse_lock(LOCK_DIR / filename, python_version)
        parsed[filename] = pins
        direct = source_requirements(extras)
        for requirement in direct:
            name = requirement_name(requirement)
            if name not in pins:
                raise LockPolicyError(f"{filename} is missing direct requirement {name}")
            required_exact = exact_pin(requirement)
            if required_exact is not None:
                actual_exact = f"{name}=={pins[name]}"
                if actual_exact != required_exact:
                    raise LockPolicyError(
                        f"{filename} exact pin drift: {actual_exact} != {required_exact}"
                    )

    forbidden_optional = {"mcp", "httpx2", "openai", "openai-agents"}
    for filename in ("core-py311.txt", "core-py312.txt", "core-py313.txt", "core-py314.txt"):
        contaminated = sorted(forbidden_optional & set(parsed[filename]))
        if contaminated:
            raise LockPolicyError(f"{filename} contains optional integration packages: {contaminated}")
    if "openai-agents" in parsed["mcp-py311.txt"] or "openai" in parsed["mcp-py311.txt"]:
        raise LockPolicyError("MCP-only lock is contaminated by OpenAI integration packages")
    for required in ("mcp", "httpx2"):
        if required not in parsed["mcp-py311.txt"]:
            raise LockPolicyError(f"MCP lock is missing {required}")
    for required in ("mcp", "httpx2", "openai-agents"):
        if required not in parsed["openai-mcp-py311.txt"]:
            raise LockPolicyError(f"OpenAI+MCP lock is missing {required}")

    print(
        "CI lock policy validated: "
        "core=py311,py312,py313,py314; optional=mcp-py311,openai-mcp-py311; "
        "hashes=sha256; package-ranges=preserved-in-pyproject"
    )


def main() -> int:
    try:
        validate()
    except (LockPolicyError, OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"CI lock policy failed: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
