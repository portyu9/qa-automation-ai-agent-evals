"""Semantic verification for scenario-owned retrieval-delivery evidence."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from agent_evals.contracts.models import EvaluationScenario
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence
from agent_evals.retrieval.receipt import (
    RetrievalDeliveryReceipt,
    RetrievalReceiptError,
    expected_event_source,
)


class RetrievalDeliveryError(ValueError):
    """Persisted retrieval evidence does not close the configured retrieval relation."""


def verify_retrieval_delivery(
    scenario: EvaluationScenario,
    evidence: TrialEvidence,
) -> RetrievalDeliveryReceipt | None:
    """Recompute one configured retrieval relation from scenario-owned source material."""
    deliveries = [
        event for event in evidence.events if event.kind is EvidenceKind.RETRIEVAL_DELIVERY
    ]
    contract = scenario.retrieval
    if contract is None:
        if deliveries:
            raise RetrievalDeliveryError(
                "retrieval delivery evidence is invalid when the scenario has no retrieval contract"
            )
        return None

    if len(deliveries) != 1:
        raise RetrievalDeliveryError(
            "scenario retrieval contract requires exactly one delivery receipt"
        )
    delivery = deliveries[0]
    if delivery.critical:
        raise RetrievalDeliveryError("retrieval delivery evidence must remain non-critical")
    if delivery.source != expected_event_source():
        raise RetrievalDeliveryError("retrieval delivery evidence source is not recognized")

    try:
        receipt = RetrievalDeliveryReceipt.model_validate(delivery.payload)
    except ValidationError as exc:
        raise RetrievalDeliveryError("retrieval delivery receipt failed schema validation") from exc

    if evidence.scenario_identity != scenario.identity:
        raise RetrievalDeliveryError("retrieval evidence scenario identity does not match scenario")
    if receipt.scenario_identity != scenario.identity:
        raise RetrievalDeliveryError("retrieval receipt scenario identity does not match scenario")
    if receipt.contract_identity != contract.identity:
        raise RetrievalDeliveryError("retrieval receipt contract identity does not match scenario")
    if receipt.tool_name != contract.tool_name:
        raise RetrievalDeliveryError("retrieval receipt tool identity does not match scenario")

    target_requests = [
        event
        for event in evidence.events
        if event.kind is EvidenceKind.TOOL_REQUEST
        and event.payload.get("tool") == contract.tool_name
    ]
    if len(target_requests) != 1:
        raise RetrievalDeliveryError("retrieval contract requires exactly one target tool request")
    request = target_requests[0]
    if request.payload.get("call_id") != receipt.call_id:
        raise RetrievalDeliveryError("retrieval request call identity does not match receipt")
    _verify_request_arguments(request, expected_query=contract.query.query)

    matching_results = [
        event
        for event in evidence.events
        if event.kind is EvidenceKind.TOOL_RESULT
        and event.payload.get("call_id") == receipt.call_id
    ]
    if len(matching_results) != 1:
        raise RetrievalDeliveryError("retrieval receipt requires exactly one matching tool result")
    result = matching_results[0]
    output = result.payload.get("output")
    if not isinstance(output, str):
        raise RetrievalDeliveryError("retrieval tool result must expose one canonical JSON string")

    if not request.sequence < delivery.sequence < result.sequence:
        raise RetrievalDeliveryError(
            "retrieval chronology must order request before delivery before tool result"
        )

    try:
        expected = RetrievalDeliveryReceipt.create(
            scenario_identity=scenario.identity,
            contract=contract,
            call_id=receipt.call_id,
            model_visible_result=output,
        )
    except RetrievalReceiptError as exc:
        raise RetrievalDeliveryError(
            "retrieval relation cannot be reconstructed from scenario"
        ) from exc
    if receipt != expected:
        raise RetrievalDeliveryError("retrieval receipt does not match rederived scenario relation")
    return receipt


def _verify_request_arguments(event: EvidenceEvent, *, expected_query: str) -> None:
    arguments = event.payload.get("arguments")
    if not isinstance(arguments, str):
        raise RetrievalDeliveryError("retrieval tool request arguments must be canonical JSON text")
    try:
        decoded = json.loads(arguments, object_pairs_hook=_reject_duplicate_keys)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RetrievalDeliveryError("retrieval tool request arguments are invalid JSON") from exc
    if not isinstance(decoded, dict) or decoded != {"query": expected_query}:
        raise RetrievalDeliveryError(
            "retrieval tool request must contain only the exact bound query"
        )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object member")
        result[key] = value
    return result
