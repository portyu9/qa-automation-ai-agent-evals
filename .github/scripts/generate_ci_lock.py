from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

PROFILES = {
    "core": ("dev",),
    "mcp": ("dev", "mcp"),
    "openai-mcp": ("dev", "openai", "mcp"),
}


def _requirement_lines(root: Path, profile: str) -> list[str]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    build_system = pyproject["build-system"]
    optional = project.get("optional-dependencies", {})
    requirements = list(project["dependencies"])
    for extra in PROFILES[profile]:
        requirements.extend(optional[extra])
    requirements.extend(build_system["requires"])

    build_manifest = root / "requirements-dev-ci-build.txt"
    for raw in build_manifest.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            requirements.append(line)

    normalized: dict[str, str] = {}
    for requirement in requirements:
        key = requirement.split(";", 1)[0].strip().lower()
        normalized.setdefault(key, requirement)
    return sorted(normalized.values(), key=str.lower)


def generate(root: Path, profile: str, output: Path) -> None:
    if profile not in PROFILES:
        raise SystemExit(f"unsupported lock profile: {profile}")
    lines = _requirement_lines(root, profile)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="agent-evals-lock-") as tmp:
        source = Path(tmp) / f"{profile}.in"
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
    text = output.read_text(encoding="utf-8")
    if "--hash=sha256:" not in text:
        raise SystemExit("generated lock does not contain SHA-256 hashes")
    if "-e " in text or "file:" in text:
        raise SystemExit("generated lock unexpectedly contains local/editable material")
    print(f"generated {output} for {profile} under Python {sys.version.split()[0]}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    generate(root, args.profile, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
