"""Pre-merge, fail-closed classification of executable pip install commands in workflows.

Reviewed local-package smoke tests are not downloads of third-party dependencies.
This guard complements (rather than replaces) hash-lock and release provenance policy.
"""

from __future__ import annotations

import argparse
import re
import shlex
import shutil
import tempfile
from collections import Counter
from pathlib import Path

from validate_workflow_graph import _load_workflow

ROOT = Path(__file__).resolve().parents[2]
PIP = re.compile(r"(?<![\w-])(?:(?:python(?:3(?:\.\d+)?)?\s+-m\s+)|(?:uv\s+))?pip(?:3)?\s+install\b")
CANONICAL = re.compile(r"^python -m pip install\s+")
APPROVED_FLAGS = {"--disable-pip-version-check", "--no-input"}
LOCAL_TARGETS = {".", "dist/*.whl", "dist/*.tar.gz", "retained-dist/*.whl", "retained-dist/*.tar.gz"}

# Validator-owned exact inventory: new local package installation paths require policy
# review, rather than declaring themselves trusted within a workflow.
EXPECTED_LOCAL = {
    "ci.yml": {".": 7, "dist/*.whl": 1, "dist/*.tar.gz": 1,
               "retained-dist/*.whl": 4, "retained-dist/*.tar.gz": 1},
    "deep-fuzz.yml": {".": 1},
    "deep-mutation.yml": {".": 1},
    "deep-property-stress.yml": {".": 1},
    "deterministic-performance.yml": {".": 1},
    "free-threaded-probe.yml": {".": 1},
    "live-provider-canary.yml": {".": 1},
    "platform-smoke.yml": {".": 1},
    "publish-pypi.yml": {"retained-dist/*.whl": 1},
    "publish-release.yml": {"retained-dist/*.whl": 1, "retained-dist/*.tar.gz": 1},
    "security.yml": {".": 1},
}


class PipInstallPolicyError(ValueError):
    """A workflow attempted an unreviewed executable package installation."""


def classify(command: str, workflow: str) -> str:
    if not CANONICAL.match(command):
        raise PipInstallPolicyError(f"{workflow}: non-canonical pip install invocation")
    if ";" in command or "&&" in command or "||" in command or "`" in command:
        raise PipInstallPolicyError(f"{workflow}: chained or substituted installer command")
    try:
        args = shlex.split(command)[4:]
    except ValueError as exc:
        raise PipInstallPolicyError(f"{workflow}: invalid pip install quoting") from exc
    if not args:
        raise PipInstallPolicyError(f"{workflow}: empty pip install")
    options = [value for value in args if value.startswith("-")]
    for unsafe in ("--extra-index-url", "--index-url", "--trusted-host", "--find-links",
                   "--editable", "--pre", "--no-index", "--no-build-isolation="):
        if any(option == unsafe or option.startswith(unsafe + "=") for option in options):
            raise PipInstallPolicyError(f"{workflow}: unsupported package acquisition flag {unsafe}")
    if "--require-hashes" in args:
        if "--no-deps" in args or "--no-build-isolation" in args:
            raise PipInstallPolicyError(f"{workflow}: mixed hashed dependency and local install")
        if args.count("-r") != 1:
            raise PipInstallPolicyError(f"{workflow}: hashed install must use one reviewed -r input")
        pos = args.index("-r")
        if pos + 1 >= len(args):
            raise PipInstallPolicyError(f"{workflow}: missing reviewed requirement path")
        requirement = args[pos + 1]
        allowed = (
            re.fullmatch(r"requirements/locks/[A-Za-z0-9_-]+\.txt", requirement)
            or re.fullmatch(r"requirements/compatibility/[A-Za-z0-9_-]+\.txt", requirement)
            or requirement == "requirements/locks/core-py${lock_suffix}.txt"
            or re.fullmatch(r"requirements/compiler/bootstrap-py3(?:11|12|13|14)\.txt", requirement)
            or requirement == 'requirements/compiler/bootstrap-py${short}.txt'
            or (
                workflow == "platform-smoke.yml"
                and requirement == "requirements/platform/windows-core-py314-supplement.txt"
            )
            or (workflow == "ci.yml" and requirement == "${{ matrix.lock }}")
        )
        if not allowed:
            raise PipInstallPolicyError(f"{workflow}: unreviewed hash-input source {requirement}")
        if set(args) - APPROVED_FLAGS - {"--require-hashes", "-r", requirement}:
            raise PipInstallPolicyError(f"{workflow}: unexpected hash-install arguments")
        return "hashed-closure"
    if "--no-deps" not in args or "--require-hashes" in args:
        raise PipInstallPolicyError(f"{workflow}: third-party install lacks SHA-256 requirements")
    targets = [a for a in args if not a.startswith("-")]
    if len(targets) != 1 or targets[0] not in LOCAL_TARGETS:
        raise PipInstallPolicyError(f"{workflow}: --no-deps is only for reviewed local artifact tests")
    target = targets[0]
    if set(args) - APPROVED_FLAGS - {"--no-deps", "--no-build-isolation", target}:
        raise PipInstallPolicyError(f"{workflow}: unsupported local installer arguments")
    if target == "." and "--no-build-isolation" not in args:
        raise PipInstallPolicyError(f"{workflow}: local source install requires --no-build-isolation")
    if target.endswith(".tar.gz") and "--no-build-isolation" not in args:
        raise PipInstallPolicyError(f"{workflow}: retained sdist install needs --no-build-isolation")
    return target


def validate(root: Path = ROOT) -> tuple[int, int]:
    folder = root / ".github" / "workflows"
    paths = sorted(folder.glob("*.y*ml"))
    if not paths:
        raise PipInstallPolicyError("no workflow files to inspect")
    found = Counter()
    count = 0
    hashed = 0
    for path in paths:
        wf = _load_workflow(path)
        jobs = wf.get("jobs")
        if not isinstance(jobs, dict):
            raise PipInstallPolicyError(f"{path.name}: jobs must be a mapping")
        for job in jobs.values():
            if not isinstance(job, dict):
                raise PipInstallPolicyError(f"{path.name}: unexpected job structure")
            for step in job.get("steps", []):
                if not isinstance(step, dict):
                    raise PipInstallPolicyError(f"{path.name}: unexpected step structure")
                run = step.get("run", "")
                if not isinstance(run, str):
                    raise PipInstallPolicyError(f"{path.name}: non-text run step")
                normalized = re.sub(r"\\\s*\n\s*", " ", run)
                for line in normalized.splitlines():
                    for match in PIP.finditer(line):
                        cmd = line[match.start():].strip()
                        kind = classify(cmd, path.name)
                        count += 1
                        if kind == "hashed-closure":
                            hashed += 1
                        else:
                            found[(path.name, kind)] += 1
    expected = Counter({
        (path, target): amount
        for path, items in EXPECTED_LOCAL.items()
        for target, amount in items.items()
    })
    if found != expected:
        delta = sorted((found - expected).items())
        missing = sorted((expected - found).items())
        raise PipInstallPolicyError(
            f"local artifact install identity/count drift: extra={delta}, missing={missing}"
        )
    if hashed == 0:
        raise PipInstallPolicyError("no SHA-256-verified third-party dependency closure found")
    return count, hashed


def self_test() -> None:
    validate()
    bad = (
        "python -m pip install pip-tools==7.5.2",
        "python -m pip install --no-deps flask==3.0.0",
        "python -m pip install --no-deps https://example.org/pkg.whl",
        "python -m pip install --require-hashes -r https://example.org/unsafe.txt",
        "python -m pip install --require-hashes -r requirements/platform/unknown.txt",
        "python -m pip install --require-hashes -r requirements/locks/../../../evil.txt",
        "python -m pip install --require-hashes -r requirements/locks/core-py311.txt --no-deps",
        "python -m pip install --trusted-host attacker.example -r requirements/locks/core-py311.txt",
        "pip install --require-hashes -r requirements/locks/core-py311.txt",
    )
    for value in bad:
        try:
            classify(value, "security.yml")
        except PipInstallPolicyError:
            continue
        raise AssertionError(f"unsafe pip install accepted: {value}")
    assert classify(
        "python -m pip install --require-hashes -r requirements/locks/core-py311.txt",
        "security.yml",
    ) == "hashed-closure"
    assert classify(
        "python -m pip install --no-deps --no-build-isolation .", "security.yml"
    ) == "."

    with tempfile.TemporaryDirectory(prefix="pip-workflow-policy-") as tmp:
        base = Path(tmp)
        target = base / ".github" / "workflows"
        shutil.copytree(ROOT / ".github" / "workflows", target)
        original = (target / "security.yml").read_text(encoding="utf-8")
        good = "python -m pip install --disable-pip-version-check --no-deps --no-build-isolation ."
        if original.count(good) != 1:
            raise AssertionError("security workflow test fixture changed")
        for replacement in (
            "python -m pip install flask==3.0.0",
            "python -m pip install --no-deps flask==3.0.0",
            "python -m pip install --require-hashes -r https://example.org/evil",
            "python -m pip install --require-hashes -r requirements/locks/core-py311.txt",
        ):
            (target / "security.yml").write_text(original.replace(good, replacement), encoding="utf-8")
            try:
                validate(base)
            except PipInstallPolicyError:
                pass
            else:
                raise AssertionError("mutated GitHub Actions workflow bypassed pip policy")
    print("workflow pip install integrity policy negative tests: ok")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        total, hashed = validate()
        print(f"workflow pip install integrity policy: {total} installs, {hashed} hashed closures")
