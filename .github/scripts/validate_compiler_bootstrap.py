"""Fail closed on unverified maintenance compiler artifacts or workflow drift."""

from __future__ import annotations

import argparse
import re
import shutil
import tempfile
from pathlib import Path

from generate_ci_lock import GENERATOR_ENV
from validate_ci_locks import LockPolicyError, parse_lock

ROOT = Path(__file__).resolve().parents[2]
PYTHONS = {"311": "3.11", "312": "3.12", "313": "3.13", "314": "3.14"}
CLOSURE = {
    "build": "1.6.1",
    "click": "8.5.0",
    "packaging": "26.3",
    "pip": "25.3",
    "pip-tools": "7.5.2",
    "pyproject-hooks": "1.3.3",
    "setuptools": "84.0.0",
    "wheel": "0.48.0",
}
HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})(?:\s|$)")


class CompilerBootstrapError(ValueError):
    """The compiler cannot be installed from reviewed, complete SHA-256 locks."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CompilerBootstrapError(message)


def validate(root: Path = ROOT) -> None:
    compiler_dir = root / "requirements" / "compiler"
    workflow = root / ".github" / "workflows" / "dependency-locks.yml"
    expected = {"bootstrap.in", *(f"bootstrap-py{py}.txt" for py in PYTHONS)}
    actual = {path.name for path in compiler_dir.iterdir() if path.is_file()}
    _require(actual == expected, f"compiler bootstrap file inventory drift: {sorted(actual ^ expected)}")
    source = (compiler_dir / "bootstrap.in").read_text(encoding="utf-8")
    direct = [line.strip() for line in source.splitlines() if line.strip() and not line.startswith("#")]
    _require(
        direct == [f"pip=={GENERATOR_ENV['pip']}", f"pip-tools=={GENERATOR_ENV['pip-tools']}"],
        "maintenance compiler direct requirements drift",
    )
    _require(
        {name: CLOSURE[name] for name in GENERATOR_ENV} == GENERATOR_ENV,
        "generator/compiler version mismatch",
    )

    for suffix, version in PYTHONS.items():
        file = compiler_dir / f"bootstrap-py{suffix}.txt"
        data = file.read_text(encoding="utf-8")
        _require(
            f"# Python: {version}\n" in data.split("# Input:", 1)[0],
            f"{file.name}: incorrect Python binding",
        )
        _require(
            "# Input: requirements/compiler/bootstrap.in\n" in data,
            f"{file.name}: input identity missing",
        )
        try:
            pins = parse_lock(file, version)
        except LockPolicyError as exc:
            raise CompilerBootstrapError(str(exc)) from exc
        _require(pins == CLOSURE, f"{file.name}: incomplete or drifted compiler transitive pins")

        blocks = re.split(r"(?m)^(?=[a-z][a-z0-9-]*==)", data)
        entries = [block for block in blocks if re.match(r"^[a-z][a-z0-9-]*==", block)]
        _require(len(entries) == len(CLOSURE), f"{file.name}: unexpected requirement blocks")
        for entry in entries:
            name = entry.split("==", 1)[0]
            hashes = HASH.findall(entry)
            _require(
                len(hashes) >= 2 and len(hashes) == len(set(hashes)),
                f"{file.name}: {name} lacks distinct reviewed wheel/sdist hashes",
            )
            _require(
                entry.count("--hash=") == len(hashes),
                f"{file.name}: {name} contains malformed or unsupported hash",
            )
        for forbidden in ("--extra-index-url", "--trusted-host", "--no-deps", "\n-e ", " @ file:"):
            _require(forbidden not in data, f"{file.name}: forbidden dependency source {forbidden!r}")

    text = workflow.read_text(encoding="utf-8")
    _require(
        text.count("python -m pip install") == 1,
        "dependency-locks must have exactly one compiler install operation",
    )
    _require(
        "--require-hashes \\\n            -r \"requirements/compiler/bootstrap-py${short}.txt\"" in text,
        "dependency-locks must install exact target-Python compiler hash lock",
    )
    _require(
        "short=\"${TARGET_PYTHON//./}\"" in text
        and "TARGET_PYTHON: ${{ matrix.python }}" in text,
        "dependency-locks compiler lock must bind to matrix interpreter",
    )
    _require(
        "version(\"pip\") == \"25.3\"" in text
        and "version(\"pip-tools\") == \"7.5.2\"" in text,
        "dependency-locks must verify both compiler runtime identities",
    )
    for forbidden in ("pip==25.3 pip-tools==7.5.2", "--no-deps", "--trusted-host"):
        _require(forbidden not in text, f"dependency-locks has unsafe fallback: {forbidden}")


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="compiler-bootstrap-contract-") as tmp:
        root = Path(tmp)
        (root / "requirements" / "compiler").mkdir(parents=True)
        (root / ".github" / "workflows").mkdir(parents=True)
        for file in (ROOT / "requirements" / "compiler").iterdir():
            shutil.copyfile(file, root / "requirements" / "compiler" / file.name)
        workflow = root / ".github" / "workflows" / "dependency-locks.yml"
        shutil.copyfile(ROOT / ".github" / "workflows" / "dependency-locks.yml", workflow)
        validate(root)
        target = root / "requirements" / "compiler" / "bootstrap-py311.txt"
        original = target.read_text(encoding="utf-8")
        example = HASH.search(original)
        assert example is not None
        for mutation_index, corrupt in enumerate((
            original.replace(example.group(0), "", 1),
            original.replace("pip-tools==7.5.2", "pip-tools==7.5.1", 1),
            original.replace("# Python: 3.11", "# Python: 3.14", 1),
            original.replace("wheel==0.48.0", "wheel==0.48.1", 1),
            original + "\n--extra-index-url https://unsafe.example\n",
        )):
            target.write_text(corrupt, encoding="utf-8")
            try:
                validate(root)
            except CompilerBootstrapError:
                pass
            else:
                raise AssertionError(f"compiler bootstrap accepted corrupted locked evidence mutation={mutation_index}")
        target.write_text(original, encoding="utf-8")
        workflow_text = workflow.read_text(encoding="utf-8")
        for corrupt in (
            workflow_text.replace("--require-hashes", "--no-deps", 1),
            workflow_text.replace("TARGET_PYTHON: ${{ matrix.python }}", "TARGET_PYTHON: '3.11'", 1),
            workflow_text + "\npython -m pip install pip-tools==7.5.2\n",
        ):
            workflow.write_text(corrupt, encoding="utf-8")
            try:
                validate(root)
            except CompilerBootstrapError:
                pass
            else:
                raise AssertionError("compiler bootstrap accepted unsafe workflow fallback")
    print("compiler bootstrap hash and interpreter-policy self-test: ok")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        validate()
        print("compiler bootstrap SHA-256 integrity policy: ok")
