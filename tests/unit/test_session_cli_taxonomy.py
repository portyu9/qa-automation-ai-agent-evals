from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

import agent_evals.cli as cli
from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import (
    AuthorityPolicy,
    EvaluationScenario,
    ScenarioKind,
    SubjectFingerprint,
)
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialVerdict
from agent_evals.runtime.session import EvaluationSession
from agent_evals.security.taxonomy import ThreatClass


def subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="scripted",
        model="deterministic",
        application_revision="session-rev-1",
        instructions="Respect the scenario contract.",
        tool_schema={"safe": {}},
        policy={"allowed": ["safe"]},
        memory_policy={"retention": "trial"},
        adapter="scripted",
        adapter_version="1",
    )


def scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="session.repeat",
        revision="7",
        kind=ScenarioKind.REGRESSION,
        objective="Reach the expected state.",
        authority=AuthorityPolicy(allowed_tools=frozenset({"safe"})),
        required_outcomes={"status": "ok"},
    )


@pytest.mark.asyncio
async def test_session_runs_repeatable_trial_identity_and_reliability() -> None:
    observed_trial_ids: list[str] = []

    def script(
        _subject: SubjectFingerprint,
        _scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        observed_trial_ids.append(trial_id)
        return AdapterResult(final_state={"status": "ok"})

    evaluated = await EvaluationSession().run(
        ScriptedAdapter(script),
        subject=subject(),
        scenario=scenario(),
        trials=3,
        k=2,
    )

    assert observed_trial_ids == [
        "session.repeat:7:0000",
        "session.repeat:7:0001",
        "session.repeat:7:0002",
    ]
    assert evaluated.subject_identity == subject().identity
    assert evaluated.scenario_identity == scenario().identity
    assert tuple(trial.verdict for trial in evaluated.trials) == (TrialVerdict.PASS,) * 3
    assert evaluated.reliability.successes == 3
    assert evaluated.reliability.resolved_trials == 3
    assert evaluated.critical_violations == 0


@pytest.mark.asyncio
async def test_session_aggregates_critical_policy_violations() -> None:
    def violate_policy(
        _subject: SubjectFingerprint,
        _scenario: EvaluationScenario,
        _trial_id: str,
    ) -> AdapterResult:
        return AdapterResult(
            events=(
                EvidenceEvent(
                    sequence=0,
                    kind=EvidenceKind.TOOL_REQUEST,
                    source="agent",
                    payload={"tool": "forbidden"},
                ),
            ),
            final_state={"status": "ok"},
        )

    evaluated = await EvaluationSession().run(
        ScriptedAdapter(violate_policy),
        subject=subject(),
        scenario=scenario(),
        trials=2,
    )

    assert tuple(trial.verdict for trial in evaluated.trials) == (TrialVerdict.FAIL,) * 2
    assert evaluated.critical_violations == 2


@pytest.mark.asyncio
async def test_session_rejects_non_positive_trial_count() -> None:
    with pytest.raises(ValueError, match="trials must be >= 1"):
        await EvaluationSession().run(
            ScriptedAdapter(lambda *_: AdapterResult()),
            subject=subject(),
            scenario=scenario(),
            trials=0,
        )


def test_doctor_reports_deterministic_core_contract() -> None:
    result = CliRunner().invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["framework"] == "qa-automation-ai-agent-evals"
    assert payload["core_requires_provider_credentials"] is False
    assert payload["terminal_authority"] == "deterministic-evidence"
    assert isinstance(payload["version"], str) and payload["version"]


def test_doctor_has_truthful_source_tree_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def package_not_found(_name: str) -> str:
        raise cli.PackageNotFoundError

    monkeypatch.setattr(cli, "version", package_not_found)
    result = CliRunner().invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["version"] == "source-tree"


def test_threat_taxonomy_has_stable_unique_machine_identifiers() -> None:
    values = tuple(threat.value for threat in ThreatClass)
    assert len(values) == len(set(values))
    assert ThreatClass.TOOL_POISONING.value == "tool_poisoning"
    assert ThreatClass.APPROVAL_BYPASS.value == "approval_bypass"
    assert ThreatClass.MCP_AUTHORIZATION_FAILURE.value == "mcp_authorization_failure"
