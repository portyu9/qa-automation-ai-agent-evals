"""Pinned OpenAI Agents SDK bridge for deterministic retrieval-delivery assurance."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult
from agent_evals.adapters.openai_agents import OpenAIAgentsAdapter, ResourceResolver
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.retrieval.models import RetrievalContractSpec, RetrievalCorpusSpec
from agent_evals.retrieval.ranker import rank_corpus
from agent_evals.retrieval.receipt import RetrievalDeliveryReceipt, RetrievalReceiptError

StateReader = Callable[[], Mapping[str, object] | Awaitable[Mapping[str, object]]]
_WRONG_QUERY_RESULT = '{"error":"retrieval query does not match bound scenario"}'


class OpenAIAgentsRetrievalAdapter:
    """Expose one evaluator-owned deterministic retrieval tool to a pinned SDK Agent."""

    def __init__(
        self,
        agent: object,
        *,
        state_reader: StateReader,
        resource_resolver: ResourceResolver | None = None,
        run_context: object | None = None,
        tracing_disabled: bool = True,
    ) -> None:
        self._agent = agent
        self._state_reader = state_reader
        self._resource_resolver = resource_resolver
        self._run_context = run_context
        self._tracing_disabled = tracing_disabled

    @property
    def name(self) -> str:
        return "openai-agents-retrieval"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        contract = scenario.retrieval
        if contract is None:
            raise AdapterPreconditionError(
                code="retrieval_contract_missing",
                reason="OpenAI retrieval adapter requires a scenario-owned retrieval contract",
            )

        try:
            from agents import Agent, function_tool
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("install the 'openai' extra to use retrieval integration") from exc

        if not isinstance(self._agent, Agent):
            raise AdapterPreconditionError(
                code="unsupported_agent_type",
                reason="retrieval integration requires an OpenAI Agents SDK Agent instance",
            )
        collisions = [
            tool for tool in self._agent.tools if getattr(tool, "name", None) == contract.tool_name
        ]
        if collisions:
            raise AdapterPreconditionError(
                code="retrieval_tool_collision",
                reason="scenario retrieval tool name collides with a preconfigured agent tool",
            )

        active_corpus = self._active_corpus(contract, scenario=scenario)
        active_result = rank_corpus(active_corpus, contract.query)
        model_visible_result = active_result.canonical_json

        async def retrieve_context(query: str) -> str:
            """Return ranked context only for the exact scenario-bound query."""
            if query != contract.query.query:
                return _WRONG_QUERY_RESULT
            return model_visible_result

        retrieval_tool = function_tool(
            retrieve_context,
            name_override=contract.tool_name,
            description_override=(
                "Retrieve the evaluator-bound context for the exact query supplied by this scenario."
            ),
        )
        runner_agent = self._agent.clone(tools=[*self._agent.tools, retrieval_tool])
        result = await OpenAIAgentsAdapter(
            runner_agent,
            state_reader=self._state_reader,
            resource_resolver=self._resource_resolver,
            run_context=self._run_context,
            tracing_disabled=self._tracing_disabled,
        ).execute(subject=subject, scenario=scenario, trial_id=trial_id)

        events = self._bind_delivery(
            result.events,
            scenario=scenario,
            model_visible_result=model_visible_result,
        )
        return AdapterResult(
            events=events,
            final_state=result.final_state,
            final_output=result.final_output,
            elapsed_ms=result.elapsed_ms,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            estimated_cost_usd=result.estimated_cost_usd,
        )

    @staticmethod
    def _active_corpus(
        contract: RetrievalContractSpec,
        *,
        scenario: EvaluationScenario,
    ) -> RetrievalCorpusSpec:
        poison = contract.poison
        if poison is None:
            return contract.corpus
        try:
            return poison.apply(contract.corpus)
        except ValueError as exc:
            raise AdapterPreconditionError(
                code="retrieval_poison_invalid",
                reason=(
                    "scenario retrieval poison could not be applied to its exact base corpus "
                    f"for {scenario.scenario_id!r}"
                ),
            ) from exc

    @staticmethod
    def _bind_delivery(
        events: tuple[EvidenceEvent, ...],
        *,
        scenario: EvaluationScenario,
        model_visible_result: str,
    ) -> tuple[EvidenceEvent, ...]:
        contract = scenario.retrieval
        if contract is None:  # pragma: no cover - execute() establishes this precondition
            raise AdapterPreconditionError(
                code="retrieval_contract_missing",
                reason="retrieval contract disappeared during one isolated execution",
            )

        requests = [
            event
            for event in events
            if event.kind is EvidenceKind.TOOL_REQUEST
            and event.payload.get("tool") == contract.tool_name
        ]
        if len(requests) != 1:
            raise AdapterPreconditionError(
                code=("retrieval_call_missing" if not requests else "retrieval_call_ambiguous"),
                reason="retrieval integration requires exactly one model-selected target call",
            )
        request = requests[0]
        call_id = request.payload.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            raise AdapterPreconditionError(
                code="retrieval_call_identity_unavailable",
                reason="retrieval call cannot be bound to a stable OpenAI call identity",
            )
        _require_exact_query(request.payload.get("arguments"), expected=contract.query.query)

        results = [
            event
            for event in events
            if event.kind is EvidenceKind.TOOL_RESULT and event.payload.get("call_id") == call_id
        ]
        if len(results) != 1:
            raise AdapterPreconditionError(
                code="retrieval_result_ambiguous",
                reason="retrieval call requires exactly one matching model-visible result",
            )
        result = results[0]
        if result.payload.get("output") != model_visible_result:
            raise AdapterPreconditionError(
                code="retrieval_result_mismatch",
                reason="normalized OpenAI retrieval result differs from evaluator-ranked context",
            )

        try:
            receipt = RetrievalDeliveryReceipt.create(
                scenario_identity=scenario.identity,
                contract=contract,
                call_id=call_id,
                model_visible_result=model_visible_result,
            )
        except RetrievalReceiptError as exc:
            raise AdapterPreconditionError(
                code="retrieval_relation_unverified",
                reason="configured retrieval ranking or poisoning relation did not close",
            ) from exc

        rebound: list[EvidenceEvent] = []
        inserted = False
        for event in events:
            if event is result:
                rebound.append(receipt.to_event(sequence=len(rebound)))
                inserted = True
            rebound.append(event.model_copy(update={"sequence": len(rebound)}))
        if not inserted:  # pragma: no cover - result selection above guarantees insertion
            raise AdapterPreconditionError(
                code="retrieval_result_unavailable",
                reason="retrieval result could not be placed into normalized chronology",
            )
        return tuple(rebound)


def _require_exact_query(arguments: object, *, expected: str) -> None:
    if not isinstance(arguments, str):
        raise AdapterPreconditionError(
            code="retrieval_query_unverified",
            reason="retrieval target arguments are not JSON text",
        )
    try:
        decoded = json.loads(arguments, object_pairs_hook=_reject_duplicate_keys)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AdapterPreconditionError(
            code="retrieval_query_unverified",
            reason="retrieval target arguments are not strict JSON",
        ) from exc
    if decoded != {"query": expected}:
        raise AdapterPreconditionError(
            code="retrieval_query_mismatch",
            reason="model-selected retrieval query does not equal the scenario-bound query",
        )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object member")
        result[key] = value
    return result
