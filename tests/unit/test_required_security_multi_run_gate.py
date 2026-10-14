"""Exact-subject Security/CodeQL multi-run evidence and API completeness regression."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

VERIFIER = Path(__file__).resolve().parents[2] / ".github/scripts/verify_required_codeql.py"
SPEC = importlib.util.spec_from_file_location("required_security_evidence", VERIFIER)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

SHA = "a" * 40


def _run(run_id: int = 1, *, status: str = "completed", conclusion: str | None = "success"):
    return {
        "id": run_id,
        "name": "CodeQL",
        "path": ".github/workflows/codeql.yml",
        "head_sha": SHA,
        "head_branch": "main",
        "event": "push",
        "run_attempt": 1,
        "status": status,
        "conclusion": conclusion,
    }


def _select(rows):
    return module.select_codeql_runs(
        rows, subject_sha=SHA, branch="main", trigger_event="push"
    )


def test_qualifies_all_distinct_same_subject_successes_in_canonical_order():
    one, two = _run(1), _run(2)
    assert _select([two, one]) == [one, two]


@pytest.mark.parametrize(
    "second",
    [
        _run(1),
        _run(2, conclusion="failure"),
        _run(2, conclusion="cancelled"),
        _run(2, conclusion="skipped"),
        _run(2, status="in_progress", conclusion="success"),
        {**_run(2), "run_attempt": False},
        {**_run(2), "id": 0},
    ],
)
def test_single_good_run_cannot_override_unqualified_second_run(second):
    with pytest.raises(module.GateError):
        _select([_run(1), second])


def test_pending_peer_does_not_qualify_until_every_peer_succeeds():
    pending = _run(2, status="queued", conclusion=None)
    with (
        patch.object(
            module, "fetch_runs", side_effect=[[_run(1), pending], [_run(1), _run(2)]]
        ),
        patch.object(module.time, "sleep") as sleeper,
    ):
        receipts = module.wait_for_success(
            repository="owner/repo",
            subject_sha=SHA,
            branch="main",
            trigger_event="push",
            token="fake",
            attempts=2,
            delay_seconds=0,
        )
    assert [run["id"] for run in receipts] == [1, 2]
    assert sleeper.call_count == 1


@pytest.mark.parametrize("count", [None, -1, True, 0, 2, 101])
def test_actions_api_rejects_missing_invalid_or_truncated_run_sets(count):
    payload = {"total_count": count, "workflow_runs": [_run(1)]}
    with (
        patch.object(
            module.urllib.request,
            "urlopen",
            return_value=io.BytesIO(json.dumps(payload).encode("utf-8")),
        ),
        pytest.raises(module.GateError, match="truncated or invalid"),
    ):
        module.fetch_runs("owner/repo", SHA, "fake-token")


def test_actions_api_accepts_complete_run_snapshot():
    runs = [_run(1), _run(2)]
    payload = {"total_count": 2, "workflow_runs": runs}
    with patch.object(
        module.urllib.request,
        "urlopen",
        return_value=io.BytesIO(json.dumps(payload).encode("utf-8")),
    ):
        assert module.fetch_runs("owner/repo", SHA, "fake-token") == runs


def test_security_checks_all_matching_runs_including_second_failed_job():
    runs = [_run(1), _run(2)]
    canonical = [
        {"name": name, "status": "completed", "conclusion": "success"}
        for name in sorted(module.SECURITY_REQUIRED_JOBS)
    ]

    def fake_jobs(_repository, _token, *, run_id, attempt):
        result = [dict(row, run_id=run_id, run_attempt=attempt) for row in canonical]
        if run_id == 2:
            result[1]["conclusion"] = "failure"
        return result

    with patch.object(module, "fetch_security_jobs", side_effect=fake_jobs) as fetched:
        with pytest.raises(module.GateError, match="did not succeed"):
            module.require_all_security_jobs("owner/repo", "fake-token", runs)
        assert fetched.call_count == 2
