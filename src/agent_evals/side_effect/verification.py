"""Semantic verification for scenario-owned side-effect idempotency observations."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from agent_evals.contracts.models import EvaluationScenario
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.side_effect.models import SideEffectIdempotencySpec, canonical_json_sha256
from agent_evals.side_effect.receipt import (
    SideEffectIdempotencyReceipt,
    SideEffectReceiptError,
    expected_event_source,
)


class SideEffectObservationError(ValueError):
    """Persisted side-effect evidence cannot close the configured observation relation."""


def verify_side_effect_observation(
    scenario: EvaluationScenario,
    evidence: TrialEvidence,
) -> SideEffectIdempotencyReceipt | None:
    """Revalidate one exact duplicate-attempt observation without rerunning side effects."""
    observations = [
        event for event in evidence.events if event.kind is EvidenceKind.SIDE_EFFECT_OBSERVATION
    ]
    contract = scenario.side_effect_idempotency
    if contract is None:
        if observations:
            raise SideEffectObservationError(
                "side-effect observation is invalid when the scenario has no idempotency contract"
            )
        return None

    if len(observations) != 1:
        raise SideEffectObservationError(
            "scenario idempotency contract requires exactly one side-effect observation receipt"
        )
    observation = observations[0]
    if observation.critical:
        raise SideEffectObservationError(
            "side-effect observation evidence must remain non-critical"
        )
    if observation.source != expected_event_source():
        raise SideEffectObservationError(
            "side-effect observation evidence source is not recognized"
        )

    try:
        receipt = SideEffectIdempotencyReceipt.model_validate(observation.payload)
    except ValidationError as exc:
        raise SideEffectObservationError(
            "side-effect observation receipt failed schema validation"
        ) from exc

    if evidence.scenario_identity != scenario.identity:
        raise SideEffectObservationError(
            "side-effect evidence scenario identity does not match scenario"
        )
    if receipt.scenario_identity != scenario.identity:
        raise SideEffectObservationError(
            "side-effect receipt scenario identity does not match scenario"
        )
    if receipt.contract_identity != contract.identity:
        raise SideEffectObservationError(
            "side-effect receipt contract identity does not match scenario"
        )
    if receipt.tool != contract.tool:
        raise SideEffectObservationError(
            "side-effect receipt tool identity does not match scenario"
        )
    if receipt.logical_operation_identity != contract.logical_operation_identity:
        raise SideEffectObservationError(
            "side-effect receipt logical-operation identity does not match scenario"
        )

    requests = [
        event
        for event in evidence.events
        if event.kind is EvidenceKind.TOOL_REQUEST and event.payload.get("tool") == contract.tool
    ]
    if len(requests) != contract.attempts:
        raise SideEffectObservationError(
            "idempotency contract requires exactly two target tool requests"
        )

    results: list[EvidenceEvent] = []
    for index, (request, attempt) in enumerate(
        zip(requests, receipt.attempts, strict=True), start=1
    ):
        call_id = request.payload.get("call_id")
        if call_id != attempt.call_id:
            raise SideEffectObservationError(
                f"side-effect request {index} call identity does not match receipt"
            )
        arguments = _parse_exact_arguments(request, contract=contract)
        if canonical_json_sha256(arguments) != attempt.arguments_sha256:
            raise SideEffectObservationError(
                f"side-effect request {index} argument digest does not match receipt"
            )
        key = arguments[contract.key_argument]
        if canonical_json_sha256(key) != attempt.key_sha256:
            raise SideEffectObservationError(
                f"side-effect request {index} logical-operation key does not match receipt"
            )
        matching = [
            event
            for event in evidence.events
            if event.kind is EvidenceKind.TOOL_RESULT
            and event.payload.get("call_id") == attempt.call_id
        ]
        if len(matching) != 1:
            raise SideEffectObservationError(
                f"side-effect request {index} requires exactly one matching tool result"
            )
        results.append(matching[0])

    first_request, second_request = requests
    first_result, second_result = results
    if not (
        first_request.sequence
        < first_result.sequence
        < second_request.sequence
        < second_result.sequence
        < observation.sequence
    ):
        raise SideEffectObservationError(
            "side-effect chronology must serialize request/result pairs before observation"
        )

    try:
        expected = SideEffectIdempotencyReceipt.create(
            scenario_identity=scenario.identity,
            contract=contract,
            attempts=(receipt.attempts[0], receipt.attempts[1]),
        )
    except SideEffectReceiptError as exc:
        raise SideEffectObservationError(
            "side-effect relation cannot be reconstructed from scenario"
        ) from exc
    if receipt != expected:
        raise SideEffectObservationError(
            "side-effect receipt does not match rederived scenario relation"
        )
    return receipt


def _parse_exact_arguments(
    event: EvidenceEvent,
    *,
    contract: SideEffectIdempotencySpec,
) -> dict[str, Any]:
    arguments = event.payload.get("arguments")
    if not isinstance(arguments, str):
        raise SideEffectObservationError("side-effect tool arguments must be JSON text")
    try:
        decoded = json.loads(arguments, object_pairs_hook=_reject_duplicate_keys)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SideEffectObservationError("side-effect tool arguments are not strict JSON") from exc
    if not isinstance(decoded, dict) or decoded != contract.expected_arguments:
        raise SideEffectObservationError(
            "duplicate side-effect attempts must equal the scenario-bound canonical operation"
        )
    return decoded


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object member")
        result[key] = value
    return result
