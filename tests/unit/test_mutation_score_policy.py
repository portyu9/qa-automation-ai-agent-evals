from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_GATE = _PROJECT_ROOT / ".github/scripts/check_mutation_score.py"


def _stats(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "killed": 95,
        "survived": 5,
        "total": 100,
        "no_tests": 0,
        "skipped": 0,
        "suspicious": 0,
        "timeout": 0,
        "check_was_interrupted_by_user": 0,
        "segfault": 0,
    }
    payload.update(overrides)
    return payload


def _run_command(
    tmp_path: Path,
    stats_path: Path,
    *,
    mutation_exit: str | None = "0",
) -> subprocess.CompletedProcess[str]:
    exit_path = tmp_path / "mutation-run-exit-code.txt"
    if mutation_exit is not None:
        exit_path.write_text(mutation_exit, encoding="ascii")
    return subprocess.run(
        [
            sys.executable,
            str(_GATE),
            str(stats_path),
            "--run-exit-code-file",
            str(exit_path),
        ],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _run_gate(
    tmp_path: Path,
    payload: object,
    *,
    mutation_exit: str | None = "0",
) -> subprocess.CompletedProcess[str]:
    stats_path = tmp_path / "mutmut-cicd-stats.json"
    stats_path.write_text(json.dumps(payload), encoding="utf-8")
    return _run_command(tmp_path, stats_path, mutation_exit=mutation_exit)


def test_mutation_score_policy_accepts_exact_threshold(tmp_path: Path) -> None:
    result = _run_gate(tmp_path, _stats())

    assert result.returncode == 0, result.stderr
    assert "score=95.00% minimum=95.00%" in result.stdout


def test_mutation_score_policy_rejects_below_threshold(tmp_path: Path) -> None:
    result = _run_gate(tmp_path, _stats(killed=94, survived=6))

    assert result.returncode == 1
    assert "below required 95.00%" in result.stderr


def test_mutation_score_policy_rejects_zero_mutants(tmp_path: Path) -> None:
    result = _run_gate(
        tmp_path,
        _stats(killed=0, survived=0, total=0),
    )

    assert result.returncode == 1
    assert "zero mutants" in result.stderr


def test_mutation_score_policy_rejects_unresolved_status(tmp_path: Path) -> None:
    result = _run_gate(
        tmp_path,
        _stats(killed=95, survived=4, no_tests=1),
    )

    assert result.returncode == 1
    assert "unresolved statuses" in result.stderr
    assert "no_tests" in result.stderr


def test_mutation_score_policy_rejects_unreported_remainder(tmp_path: Path) -> None:
    result = _run_gate(tmp_path, _stats(total=101))

    assert result.returncode == 1
    assert "statistics are incomplete" in result.stderr
    assert "unreported=1" in result.stderr


def test_mutation_score_policy_rejects_bool_count(tmp_path: Path) -> None:
    result = _run_gate(tmp_path, _stats(killed=True))

    assert result.returncode == 1
    assert "non-negative exact integer" in result.stderr


def test_mutation_score_policy_rejects_schema_drift(tmp_path: Path) -> None:
    payload = _stats()
    del payload["timeout"]
    payload["new_status"] = 0

    result = _run_gate(tmp_path, payload)

    assert result.returncode == 1
    assert "schema mismatch" in result.stderr
    assert "timeout" in result.stderr
    assert "new_status" in result.stderr


def test_mutation_score_policy_rejects_nonzero_mutmut_exit_even_with_passing_stats(
    tmp_path: Path,
) -> None:
    result = _run_gate(tmp_path, _stats(), mutation_exit="1")

    assert result.returncode == 1
    assert "incomplete or failed with exit code 1" in result.stderr


def test_mutation_score_policy_rejects_missing_mutmut_exit_code(tmp_path: Path) -> None:
    result = _run_gate(tmp_path, _stats(), mutation_exit=None)

    assert result.returncode == 1
    assert "exit-code file is missing" in result.stderr


def test_mutation_score_policy_rejects_noncanonical_mutmut_exit_code(tmp_path: Path) -> None:
    result = _run_gate(tmp_path, _stats(), mutation_exit="00")

    assert result.returncode == 1
    assert "canonical integer text" in result.stderr


def test_mutation_score_policy_rejects_malformed_json(tmp_path: Path) -> None:
    stats_path = tmp_path / "mutmut-cicd-stats.json"
    stats_path.write_text("{not-json", encoding="utf-8")

    result = _run_command(tmp_path, stats_path)

    assert result.returncode == 1
    assert "cannot read valid mutation statistics" in result.stderr


def test_mutation_score_policy_rejects_missing_statistics_file(tmp_path: Path) -> None:
    result = _run_command(tmp_path, tmp_path / "missing.json")

    assert result.returncode == 1
    assert "statistics file is missing" in result.stderr
