"""Non-native oracle checks and trusted workflow contracts for real Atheris fuzzing.

The native coverage engine is still required to execute in the dedicated Python
3.14 Linux Actions job; these unit tests are not substituted for it.
"""

from __future__ import annotations

import contextlib
import runpy
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "tests/fuzz/atheris_strict_json.py"
CORPUS = ROOT / "tests/fuzz/corpus/strict-json"
WORKFLOW = ROOT / ".github/workflows/deep-fuzz.yml"
LOCK = ROOT / "requirements/locks/atheris-py314.txt"
WHEEL_SHA256 = "315a0b5c819852b1ffe1ca72efc389c7724881f2c33e4aacb8c6bcec49bd5011"


def test_native_harness_oracle_on_committed_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    # Run the actual target function without loading native libFuzzer into unit CI.
    # This deliberately does not claim a coverage-guided fuzz campaign ran.
    stub = types.ModuleType("atheris")
    stub.instrument_imports = contextlib.nullcontext  # type: ignore[attr-defined]
    stub.instrument_func = lambda func: func  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "atheris", stub)
    funcs = runpy.run_path(str(HARNESS), run_name="atheris_under_test")
    exercise = funcs["test_one_input"]

    corpus_paths = sorted(CORPUS.glob("*.json"))
    assert len(corpus_paths) >= 5
    for corpus in corpus_paths:
        exercise(corpus.read_bytes())
    for payload in (
        b"",
        b"null",
        b"{}",
        b"[]",
        b"true",
        b"123",
        b"-1e309",
        b"\xff\xfe",
        b'{"duplicate":1,"duplicate":2}',
        b'{"long":' + b"[" * 70 + b"0" + b"]" * 70 + b"}",
        b'{"broken":',
        b" " * 4097,
    ):
        exercise(payload)


def test_native_atheris_job_preserves_exact_subject_and_evidence() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    harness = HARNESS.read_text(encoding="utf-8")
    lock = LOCK.read_text(encoding="utf-8")
    for needle in (
        "  atheris-strict-json:",
        "name: Native Atheris / strict JSON / Python 3.14",
        "runs-on: ubuntu-24.04",
        'python-version: "3.14"',
        "ref: ${{ env.EXACT_COMMIT }}",
        "persist-credentials: false",
        "requirements/locks/core-py314.txt",
        "requirements/locks/atheris-py314.txt",
        "--require-hashes",
        "PYTHONPATH: src",
        "python -m pip check",
        'test "$(git rev-parse HEAD)" = "$EXACT_COMMIT"',
        "-atheris_runs=5000",
        "-max_len=4096",
        "timeout --signal=TERM --kill-after=10s 180s",
        "atheris-evidence/run.log",
        "atheris-evidence/crashes/",
        "if: always()",
        "if-no-files-found: error",
        "retention-days: 21",
    ):
        assert needle in workflow, f"native fuzz security contract missing: {needle}"
    assert workflow.count("  atheris-strict-json:") == 1
    assert "import atheris" in harness
    assert "atheris.Setup(sys.argv, test_one_input)" in harness
    assert "atheris.Fuzz()" in harness
    assert "@atheris.instrument_func" in harness
    assert "with atheris.instrument_imports():" in harness
    assert "except Exception" not in harness
    assert "except BaseException" not in harness
    assert "atheris==3.1.0" in lock
    assert f"--hash=sha256:{WHEEL_SHA256}" in lock
    assert lock.count("--hash=sha256:") == 1
    assert "--index-url" not in lock
    assert "--extra-index-url" not in lock
