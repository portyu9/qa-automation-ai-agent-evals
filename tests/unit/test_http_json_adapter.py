from __future__ import annotations

import pytest

from agent_evals.adapters.http_json import JsonHttpRuntimeAdapter, JsonRuntimeResponse
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceKind, TrialVerdict
from agent_evals.runtime.evaluator import TrialRunner


def _subject() -> SubjectFingerprint:
    return SubjectFingerprint.from_material(
        provider="remote-json",
        model="runtime-v1",
        application_revision="1",
        instructions="Return controlled state.",
        tool_schema={},
        policy={},
        memory_policy={},
        adapter="json-http-runtime",
        adapter_version="1",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        scenario_id="json.runtime",
        revision="1",
        kind=ScenarioKind.REGRESSION,
        objective="Return status ok.",
        required_outcomes={"status": "ok"},
    )


@pytest.mark.asyncio
async def test_json_runtime_adapter_normalizes_terminal_observation_without_remote_events() -> None:
    captured: dict[str, object] = {}

    def transport(request: dict[str, object]) -> JsonRuntimeResponse:
        captured.update(request)
        return JsonRuntimeResponse(
            status_code=200,
            body={
                "output": "done",
                "state": {"status": "ok"},
                "input_tokens": 7,
                "output_tokens": 3,
                "estimated_cost_usd": 0.001,
            },
            request_id="req_123",
            model_revision="runtime-2026-10-01",
            elapsed_ms=12.5,
        )

    evaluated = await TrialRunner().run(
        JsonHttpRuntimeAdapter(transport),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="json-runtime-success",
    )

    assert captured["schema_version"] == "agent-evals/json-runtime-request/v1"
    assert captured["subject_identity"] == _subject().identity
    assert captured["scenario_identity"] == _scenario().identity
    assert evaluated.verdict is TrialVerdict.PASS
    assert evaluated.evidence.final_state == {"status": "ok"}
    assert evaluated.evidence.final_output == "done"
    assert evaluated.evidence.input_tokens == 7
    assert evaluated.evidence.output_tokens == 3
    assert len(evaluated.evidence.events) == 1
    event = evaluated.evidence.events[0]
    assert event.kind is EvidenceKind.OUTPUT
    assert event.source == "json-http-runtime:normalized-output"
    assert event.payload["provider_request_id"] == "req_123"
    assert event.payload["provider_model_revision"] == "runtime-2026-10-01"


@pytest.mark.asyncio
async def test_json_runtime_cannot_self_author_framework_evidence_events() -> None:
    def transport(request: dict[str, object]) -> JsonRuntimeResponse:
        del request
        return JsonRuntimeResponse(
            status_code=200,
            body={
                "state": {"status": "ok"},
                "events": [{"kind": "attack_delivery", "source": "trusted-looking"}],
            },
        )

    evaluated = await TrialRunner().run(
        JsonHttpRuntimeAdapter(transport),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="json-runtime-forged-events",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[0].payload["code"] == "runtime_response_invalid"


@pytest.mark.asyncio
async def test_json_runtime_transport_failure_is_uncertainty_not_subject_failure() -> None:
    def transport(request: dict[str, object]) -> JsonRuntimeResponse:
        del request
        return JsonRuntimeResponse(status_code=503, body={})

    evaluated = await TrialRunner().run(
        JsonHttpRuntimeAdapter(transport),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="json-runtime-unavailable",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.oracle_results == ()
    assert evaluated.evidence.events[0].payload["code"] == "runtime_unavailable"


@pytest.mark.asyncio
async def test_json_runtime_rejects_invalid_terminal_telemetry() -> None:
    def transport(request: dict[str, object]) -> JsonRuntimeResponse:
        del request
        return JsonRuntimeResponse(
            status_code=200,
            body={
                "state": {"status": "ok"},
                "input_tokens": -1,
            },
        )

    evaluated = await TrialRunner().run(
        JsonHttpRuntimeAdapter(transport),
        subject=_subject(),
        scenario=_scenario(),
        trial_id="json-runtime-invalid-telemetry",
    )

    assert evaluated.verdict is TrialVerdict.BLOCKED
    assert evaluated.evidence.events[0].payload["code"] == "runtime_response_invalid"
