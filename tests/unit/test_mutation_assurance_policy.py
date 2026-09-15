from __future__ import annotations

import json
import re
import runpy
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_POLICY = json.loads((_ROOT / "mutation-policy.json").read_text(encoding="utf-8"))
_PYPROJECT = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
_MUTATION_WORKFLOW = (_ROOT / ".github/workflows/mutation-assurance.yml").read_text(
    encoding="utf-8"
)
_ORDINARY_CI = (_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
_GATE = runpy.run_path(str(_ROOT / ".github/scripts/mutation_gate.py"))
_EVALUATE_STATS = _GATE["evaluate_stats"]


def _stats(**overrides: int) -> dict[str, int]:
    values = {
        "killed": 80,
        "survived": 20,
        "no_tests": 0,
        "skipped": 0,
        "suspicious": 0,
        "timeout": 0,
        "check_was_interrupted_by_user": 0,
        "segfault": 0,
        "total": 100,
    }
    values.update(overrides)
    return values


def _evaluate(stats: dict[str, int]) -> dict[str, Any]:
    return _EVALUATE_STATS(stats, _POLICY)


def test_mutation_policy_cli_validates_checked_in_configuration() -> None:
    completed = subprocess.run(
        [sys.executable, ".github/scripts/mutation_gate.py", "validate"],
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "mutation policy valid" in completed.stdout


def test_mutmut_configuration_copies_package_but_mutates_only_manifest_targets() -> None:
    targets = [target["path"] for target in _POLICY["targets"]]
    config = _PYPROJECT["tool"]["mutmut"]

    assert config["source_paths"] == ["src/agent_evals"]
    assert config["only_mutate"] == targets
    assert config["pytest_add_cli_args_test_selection"] == ["tests/unit"]
    assert config["pytest_add_cli_args"] == ["--hypothesis-seed=20260915"]
    assert "type_check_command" not in config
    assert "do_not_mutate" not in config
    assert "do_not_mutate_patterns" not in config


def test_mutation_tool_is_exactly_pinned_and_isolated_from_dev_dependencies() -> None:
    requirement_lines = [
        line.strip()
        for line in (_ROOT / "requirements-mutation.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    dev_dependencies = _PYPROJECT["project"]["optional-dependencies"]["dev"]

    assert requirement_lines == ["mutmut==3.8.0"]
    assert _POLICY["tool"] == {"name": "mutmut", "version": "3.8.0"}
    assert all(not dependency.lower().startswith("mutmut") for dependency in dev_dependencies)


def test_mutation_workflow_is_separate_least_permission_and_commit_pinned() -> None:
    assert "workflow_dispatch:" in _MUTATION_WORKFLOW
    assert "schedule:" in _MUTATION_WORKFLOW
    assert "pull_request:" not in _MUTATION_WORKFLOW
    assert "\n  push:" not in _MUTATION_WORKFLOW
    assert "permissions:\n  contents: read" in _MUTATION_WORKFLOW
    assert "timeout-minutes: 120" in _MUTATION_WORKFLOW
    assert "retention-days: 30" in _MUTATION_WORKFLOW
    assert "mutmut run" in _MUTATION_WORKFLOW
    assert "mutation_gate.py evaluate" in _MUTATION_WORKFLOW

    action_refs = re.findall(r"uses:\s+[^@\s]+@([^\s]+)", _MUTATION_WORKFLOW)
    assert action_refs
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in action_refs)

    assert "mutmut" not in _ORDINARY_CI
    assert "mutation-assurance" not in _ORDINARY_CI


def test_mutation_score_accepts_exact_threshold_without_exclusions() -> None:
    result = _evaluate(_stats())

    assert result["passed"] is True
    assert result["score_percent"] == 80.0
    assert result["counts"]["unclassified"] == 0


def test_mutation_score_rejects_below_threshold() -> None:
    result = _evaluate(_stats(killed=79, survived=21))

    assert result["passed"] is False
    assert result["score_percent"] == 79.0
    assert any("below required" in error for error in result["errors"])


def test_no_tests_mutants_remain_in_score_denominator() -> None:
    result = _evaluate(_stats(killed=80, survived=0, no_tests=20))

    assert result["passed"] is True
    assert result["score_percent"] == 80.0
    assert result["counts"]["no_tests"] == 20


def test_timeout_is_fatal_even_when_score_threshold_is_met() -> None:
    result = _evaluate(_stats(killed=80, survived=19, timeout=1))

    assert result["passed"] is False
    assert result["score_percent"] == 80.0
    assert any("timeout" in error for error in result["errors"])


def test_unclassified_exported_mutant_status_fails_closed() -> None:
    result = _evaluate(_stats(killed=80, survived=19))

    assert result["passed"] is False
    assert result["counts"]["unclassified"] == 1
    assert any("unclassified" in error for error in result["errors"])


def test_mutation_gate_rejects_too_small_sample() -> None:
    result = _evaluate(_stats(killed=79, survived=20, total=99))

    assert result["passed"] is False
    assert any("at least 100" in error for error in result["errors"])


def test_mutation_assurance_nonclaims_remain_explicit() -> None:
    document = (_ROOT / "MUTATION_ASSURANCE.md").read_text(encoding="utf-8")

    assert "BLOCKED       != FAIL" in document
    assert "INCONCLUSIVE  != FAIL" in document
    assert "hash/root     != authentication" in document
    assert "mutation score != formal verification or security certification" in document
    assert "killed / total" in document
