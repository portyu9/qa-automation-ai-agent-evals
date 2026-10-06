from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from agent_evals import cli
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
    assert "--install-completion" in help_text


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
