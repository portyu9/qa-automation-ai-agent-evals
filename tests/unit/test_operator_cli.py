from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agent_evals import cli, operator
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence

runner = CliRunner()


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="operator.smoke",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Reach the expected state.",
        authority=AuthorityPolicy(),
        required_outcomes={"status": "ok"},
    )


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="local",
        model="fixture",
        application_revision="1",
        instructions="fixture",
        tool_schema={},
        policy={},
        memory_policy={},
        adapter="operator-scripted",
        adapter_version="1",
    )


def _write(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_help_exposes_operator_surface_and_completion() -> None:
    result = runner.invoke(cli.app, ["--help"], color=False)
    assert result.exit_code == 0
    help_text = result.stdout
    for command in (
        "scenario",
        "run",
        "session",
        "replay",
        "regrade",
        "evidence",
        "store",
        "report",
        "compare",
        "minimize",
        "calibration",
        "ci",
    ):
        assert command in help_text
    completion = runner.invoke(cli.app, ["--show-completion", "bash"])
    assert completion.exit_code == 0
    assert completion.stdout.strip()


def test_scenario_validate_and_jsonl_explain(tmp_path: Path) -> None:
    path = _write(tmp_path / "scenario.json", _scenario().model_dump(mode="json"))
    result = runner.invoke(
        cli.app,
        ["--format", "jsonl", "--explain", "scenario", "validate", str(path)],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "valid"
    assert payload["scenario_identity"] == _scenario().identity
    assert len(payload["proof_chain"]) == 3
    assert "\n" not in result.stdout.rstrip("\n")


def test_run_and_session_run_use_only_operator_scripted_identity(tmp_path: Path) -> None:
    request = {
        "schema_version": "agent-evals/operator-run-request/v1",
        "subject": _subject().model_dump(mode="json"),
        "scenario": _scenario().model_dump(mode="json"),
        "observations": [
            {"final_state": {"status": "ok"}},
            {"final_state": {"status": "ok"}},
        ],
        "campaign_id": "operator-test",
        "k": 1,
    }
    path = _write(tmp_path / "run.json", request)

    single = runner.invoke(cli.app, ["run", str(path)])
    assert single.exit_code == cli.EXIT_VALIDATION

    session = runner.invoke(cli.app, ["session", "run", str(path)])
    assert session.exit_code == 0
    payload = json.loads(session.stdout)
    assert payload["execution_boundary"] == "normalized-operator-scripted"
    assert [trial["verdict"] for trial in payload["trials"]] == ["pass", "pass"]

    bad = dict(request)
    bad_subject = _subject().model_copy(update={"adapter": "openai-agents"})
    bad["subject"] = bad_subject.model_dump(mode="json")
    bad_path = _write(tmp_path / "bad.json", bad)
    rejected = runner.invoke(cli.app, ["session", "run", str(bad_path)])
    assert rejected.exit_code == cli.EXIT_VALIDATION
    assert "cannot be impersonated" in rejected.stderr


def test_replay_regrade_evidence_verify_inspect_and_minimize(tmp_path: Path) -> None:
    scenario = _scenario()
    subject = _subject()
    scenario_path = _write(tmp_path / "scenario.json", scenario.model_dump(mode="json"))
    subject_path = _write(tmp_path / "subject.json", subject.model_dump(mode="json"))
    event = EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.STATE,
        source="fixture",
        payload={"note": "diagnostic"},
    )
    failing = TrialEvidence(
        trial_id="operator-failing-trial",
        subject_identity=subject.identity,
        scenario_identity=scenario.identity,
        events=(event,),
        final_state={"status": "bad"},
    )
    evidence_path = _write(tmp_path / "evidence.json", failing.model_dump(mode="json"))

    verified = runner.invoke(cli.app, ["evidence", "verify", str(evidence_path)])
    assert verified.exit_code == 0
    assert json.loads(verified.stdout)["evidence_root"] == failing.evidence_root

    inspected = runner.invoke(cli.app, ["evidence", "inspect", str(evidence_path)])
    assert inspected.exit_code == 0
    assert "payload" not in json.loads(inspected.stdout)["events"][0]

    exposed = runner.invoke(
        cli.app,
        ["evidence", "inspect", str(evidence_path), "--include-payloads"],
    )
    assert json.loads(exposed.stdout)["events"][0]["payload"] == {"note": "diagnostic"}

    for command in ("replay", "regrade"):
        result = runner.invoke(
            cli.app,
            [command, str(evidence_path), str(scenario_path), str(subject_path)],
        )
        assert result.exit_code == 0
        assert json.loads(result.stdout)["verdict"] == "fail"

    minimized = runner.invoke(
        cli.app,
        ["minimize", str(evidence_path), str(scenario_path), str(subject_path)],
    )
    assert minimized.exit_code == 0
    minimized_payload = json.loads(minimized.stdout)
    assert minimized_payload["target_verdict"] == "fail"
    assert minimized_payload["minimized_events"] <= 1


def test_compare_rejects_blocked_and_compares_resolved_pairs(tmp_path: Path) -> None:
    baseline = _write(tmp_path / "baseline.json", ["pass", "fail", "fail"])
    candidate = _write(tmp_path / "candidate.json", ["pass", "pass", "fail"])
    result = runner.invoke(cli.app, ["compare", str(baseline), str(candidate)])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["pairs"] == 3
    assert payload["candidate_only_pass"] == 1

    blocked = _write(tmp_path / "blocked.json", ["pass", "blocked", "fail"])
    rejected = runner.invoke(cli.app, ["compare", str(baseline), str(blocked)])
    assert rejected.exit_code == cli.EXIT_VALIDATION
    assert "BLOCKED or INCONCLUSIVE" in rejected.stderr


def test_store_verify_all_accepts_empty_store_and_flags_lock(tmp_path: Path) -> None:
    root = tmp_path / "store"
    clean = runner.invoke(cli.app, ["store", "verify-all", str(root)])
    assert clean.exit_code == 0
    assert json.loads(clean.stdout)["records_verified"] == 0

    bucket = root / "records" / "aa"
    bucket.mkdir()
    (bucket / ("a" * 64 + ".lock")).write_text("", encoding="utf-8")
    dirty = runner.invoke(cli.app, ["store", "verify-all", str(root)])
    assert dirty.exit_code == cli.EXIT_INTEGRITY
    assert "operator review" in dirty.stdout


def test_store_lock_inspect_requires_exact_confirmation_before_quarantine(
    tmp_path: Path,
) -> None:
    root = tmp_path / "store"
    store = LocalEvidenceStore(root)
    item = TrialEvidence(
        trial_id="operator-lock",
        subject_identity="a" * 64,
        scenario_identity="b" * 64,
        final_state={"status": "ok"},
    )
    key = evidence_record_key(item)
    paths = store._paths(key, create_bucket=True)
    fd = store._acquire_lock(paths.lock)
    import os

    os.close(fd)

    inspected = runner.invoke(cli.app, ["store", "lock-inspect", str(root), key])
    assert inspected.exit_code == 0
    observation = json.loads(inspected.stdout)
    assert observation["status"] == "observed"
    assert observation["record_key"] == key
    assert observation["stale"] is None

    rejected = runner.invoke(
        cli.app,
        [
            "store",
            "lock-quarantine",
            str(root),
            key,
            "--confirm-observation-root",
            "0" * 64,
        ],
    )
    assert rejected.exit_code == cli.EXIT_VALIDATION
    assert paths.lock.exists()

    quarantined = runner.invoke(
        cli.app,
        [
            "store",
            "lock-quarantine",
            str(root),
            key,
            "--confirm-observation-root",
            observation["observation_root"],
        ],
    )
    assert quarantined.exit_code == 0
    payload = json.loads(quarantined.stdout)
    assert payload["status"] == "quarantined"
    assert payload["observation_root"] == observation["observation_root"]
    assert not paths.lock.exists()
    assert (root / "quarantine" / "locks" / payload["quarantine_name"]).is_file()


def test_versioned_config_and_deep_doctor(tmp_path: Path) -> None:
    config = _write(
        tmp_path / "config.json",
        {
            "schema_version": "agent-evals/operator-config/v1",
            "output_format": "jsonl",
            "explain": True,
            "store_root": str(tmp_path / "configured-store"),
        },
    )
    result = runner.invoke(cli.app, ["--config", str(config), "doctor", "--deep"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "pass"
    assert "proof_chain" in payload
    assert payload["checks"]["evidence_store"]["usable"] is True


def test_invalid_config_schema_fails_as_usage_error(tmp_path: Path) -> None:
    config = _write(tmp_path / "config.json", {"schema_version": "wrong"})
    result = runner.invoke(cli.app, ["--config", str(config), "doctor"])
    assert result.exit_code == cli.EXIT_USAGE
    assert "operator config schema_version" in result.stderr


def test_config_environment_and_validation_branches(tmp_path: Path) -> None:
    valid = _write(
        tmp_path / "valid-config.json",
        {"schema_version": "agent-evals/operator-config/v1", "output_format": "json"},
    )
    env_result = runner.invoke(
        cli.app,
        ["doctor"],
        env={"AGENT_EVALS_CONFIG": str(valid)},
    )
    assert env_result.exit_code == 0

    not_object = _write(tmp_path / "list-config.json", ["not", "an", "object"])
    rejected_object = runner.invoke(cli.app, ["--config", str(not_object), "doctor"])
    assert rejected_object.exit_code == cli.EXIT_USAGE
    assert "operator config JSON root must be an object" in rejected_object.stderr

    unknown = _write(
        tmp_path / "unknown-config.json",
        {"schema_version": "agent-evals/operator-config/v1", "unexpected": True},
    )
    rejected_unknown = runner.invoke(cli.app, ["--config", str(unknown), "doctor"])
    assert rejected_unknown.exit_code == cli.EXIT_USAGE
    assert "unknown keys" in rejected_unknown.stderr

    rejected_format = runner.invoke(cli.app, ["--format", "xml", "doctor"], color=False)
    assert rejected_format.exit_code == cli.EXIT_USAGE
    stderr_text = re.sub(r"\x1b\[[0-9;]*m", "", rejected_format.stderr)
    assert "--format must be json or jsonl" in stderr_text


def test_explain_errors_include_non_authoritative_proof_chain(tmp_path: Path) -> None:
    baseline = _write(tmp_path / "baseline.json", ["pass", "fail"])
    invalid = _write(tmp_path / "invalid.json", ["pass", "not-a-verdict"])

    result = runner.invoke(
        cli.app,
        ["--explain", "compare", str(baseline), str(invalid)],
    )

    assert result.exit_code == cli.EXIT_VALIDATION
    payload = json.loads(result.stderr)
    assert payload["status"] == "error"
    assert payload["proof_chain"] == [
        "the requested operation failed before an authoritative result"
    ]


def test_repository_policy_operator_pass_fail_and_missing(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    scripts = (
        ".github/scripts/validate_runtime_policy.py",
        ".github/scripts/validate_security_stack.py",
        ".github/scripts/validate_workflow_graph.py",
    )
    for relative in scripts:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("print('ok')\n", encoding="utf-8")

    passed = operator.check_repository_policy(root)
    assert passed["status"] == "pass"
    assert [item["status"] for item in passed["checks"]] == ["pass", "pass", "pass"]

    failing_script = root / scripts[0]
    failing_script.write_text(
        "import sys\nprint('policy failed', file=sys.stderr)\nraise SystemExit(7)\n",
        encoding="utf-8",
    )
    failed = operator.check_repository_policy(root)
    assert failed["status"] == "fail"
    assert failed["_exit_code"] == cli.EXIT_POLICY
    assert failed["checks"][0]["returncode"] == 7
    assert "policy failed" in failed["checks"][0]["stderr_tail"]

    (root / scripts[1]).unlink()
    missing = operator.check_repository_policy(root)
    assert missing["status"] == "fail"
    assert missing["checks"][1] == {
        "script": scripts[1],
        "status": "missing",
    }

    cli_result = runner.invoke(cli.app, ["ci", "check-policy", "--root", str(root)])
    assert cli_result.exit_code == cli.EXIT_POLICY
    assert json.loads(cli_result.stdout)["status"] == "fail"


def test_operator_rejects_unsupported_report_and_verdict_shapes(tmp_path: Path) -> None:
    unsupported = _write(
        tmp_path / "unsupported-report.json",
        {"schema_version": "agent-evals/assurance-report/v999"},
    )
    report = runner.invoke(cli.app, ["report", "verify", str(unsupported)])
    assert report.exit_code == cli.EXIT_VALIDATION
    assert "unsupported assurance report schema" in report.stderr

    object_vector = _write(tmp_path / "object-vector.json", {"verdicts": ["pass", "fail"]})
    assert tuple(
        verdict.value
        for verdict in operator._load_verdict_vector(object_vector, label="object vector")
    ) == ("pass", "fail")

    invalid_shape = _write(tmp_path / "invalid-shape.json", {"values": ["pass"]})
    with pytest.raises(ValueError, match="must be a JSON verdict array"):
        operator._load_verdict_vector(invalid_shape, label="invalid shape")

    invalid_value = _write(tmp_path / "invalid-value.json", ["pass", "bogus"])
    with pytest.raises(ValueError, match="contains an invalid trial verdict"):
        operator._load_verdict_vector(invalid_value, label="invalid value")


def test_deep_doctor_reports_unusable_configured_store(tmp_path: Path) -> None:
    occupied = tmp_path / "not-a-directory"
    occupied.write_text("occupied", encoding="utf-8")

    payload = operator.deep_doctor(configured_store_root=occupied)

    assert payload["status"] == "pass"
    assert payload["checks"]["evidence_store"]["usable"] is False
    assert "reason" in payload["checks"]["evidence_store"]


def test_minimize_rejects_pass_and_replay_rejects_identity_drift(tmp_path: Path) -> None:
    scenario = _scenario()
    subject = _subject()
    scenario_path = _write(tmp_path / "scenario.json", scenario.model_dump(mode="json"))
    subject_path = _write(tmp_path / "subject.json", subject.model_dump(mode="json"))
    passing = TrialEvidence(
        trial_id="operator-passing-trial",
        subject_identity=subject.identity,
        scenario_identity=scenario.identity,
        final_state={"status": "ok"},
    )
    evidence_path = _write(tmp_path / "passing.json", passing.model_dump(mode="json"))

    minimized = runner.invoke(
        cli.app,
        ["minimize", str(evidence_path), str(scenario_path), str(subject_path)],
    )
    assert minimized.exit_code == cli.EXIT_VALIDATION
    assert "minimize requires a non-PASS source trial" in minimized.stderr

    other_subject = SubjectFingerprint.from_material(
        provider="local",
        model="fixture",
        application_revision="different",
        instructions="fixture",
        tool_schema={},
        policy={},
        memory_policy={},
        adapter="operator-scripted",
        adapter_version="1",
    )
    other_subject_path = _write(
        tmp_path / "other-subject.json",
        other_subject.model_dump(mode="json"),
    )
    subject_mismatch = runner.invoke(
        cli.app,
        ["replay", str(evidence_path), str(scenario_path), str(other_subject_path)],
    )
    assert subject_mismatch.exit_code == cli.EXIT_VALIDATION
    assert "subject identity does not match" in subject_mismatch.stderr

    other_scenario = EvaluationScenario(
        scenario_id="operator.smoke",
        revision="2",
        kind=ScenarioKind.REGRESSION,
        objective="Reach the expected state.",
        authority=AuthorityPolicy(),
        required_outcomes={"status": "ok"},
    )
    other_scenario_path = _write(
        tmp_path / "other-scenario.json",
        other_scenario.model_dump(mode="json"),
    )
    scenario_mismatch = runner.invoke(
        cli.app,
        ["replay", str(evidence_path), str(other_scenario_path), str(subject_path)],
    )
    assert scenario_mismatch.exit_code == cli.EXIT_VALIDATION
    assert "scenario identity does not match" in scenario_mismatch.stderr
