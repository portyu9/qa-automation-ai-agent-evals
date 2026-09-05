"""Pinned OpenAI Agents SDK bridge for run-local side-effect idempotency assurance."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from copy import copy
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from agent_evals.adapters.base import AdapterPreconditionError, AdapterResult
from agent_evals.adapters.openai_agents import OpenAIAgentsAdapter, ResourceResolver
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.side_effect.models import (
    SideEffectIdempotencySpec,
    canonical_json_sha256,
    canonicalize_json,
)
from agent_evals.side_effect.receipt import (
    SideEffectAttemptDigest,
    SideEffectIdempotencyReceipt,
    SideEffectReceiptError,
)

StateReader = Callable[[], Mapping[str, object] | Awaitable[Mapping[str, object]]]
EffectReader = Callable[[], object | Awaitable[object]]


@dataclass(slots=True)
class _ObservedAttempt:
    """Mutable execution-time observation kept outside durable evidence until relation closure."""

    call_id: str | None
    arguments: dict[str, Any] | None
    arguments_sha256: str | None
    key_sha256: str | None
    before_effect_sha256: str | None
    after_effect_sha256: str | None
    observation_error: str | None = None


class OpenAIAgentsSideEffectIdempotencyAdapter(OpenAIAgentsAdapter):
    """Observe an existing local FunctionTool without suppressing or repairing its side effects.

    The adapter wraps the subject-provided callback only to sample evaluator-owned effect state
    immediately before and after each target invocation. The callback still executes on every SDK
    call and its return value/exception is preserved. Observation uncertainty blocks evaluation;
    a verified second physical mutation is left intact for deterministic subject grading.
    """

    def __init__(
        self,
        agent: object,
        *,
        state_reader: StateReader,
        effect_reader: EffectReader,
        resource_resolver: ResourceResolver | None = None,
        run_context: object | None = None,
        tracing_disabled: bool = True,
    ) -> None:
        super().__init__(
            agent,
            state_reader=state_reader,
            resource_resolver=resource_resolver,
            run_context=run_context,
            tracing_disabled=tracing_disabled,
        )
        self._effect_reader = effect_reader

    @property
    def name(self) -> str:
        return "openai-agents-side-effect-idempotency"

    async def execute(
        self,
        *,
        subject: SubjectFingerprint,
        scenario: EvaluationScenario,
        trial_id: str,
    ) -> AdapterResult:
        contract = scenario.side_effect_idempotency
        if contract is None:
            raise AdapterPreconditionError(
                code="side_effect_contract_missing",
                reason="side-effect adapter requires a scenario-owned idempotency contract",
            )

        runner_agent, observed = self._prepare_observed_agent(contract)
        result = await OpenAIAgentsAdapter(
            runner_agent,
            state_reader=self._state_reader,
            resource_resolver=self._resource_resolver,
            run_context=self._run_context,
            tracing_disabled=self._tracing_disabled,
        ).execute(subject=subject, scenario=scenario, trial_id=trial_id)

        events = self._bind_observation(
            result.events,
            scenario=scenario,
            observed=observed,
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

    def _prepare_observed_agent(
        self,
        contract: SideEffectIdempotencySpec,
    ) -> tuple[object, list[_ObservedAttempt]]:
        agent, target = self._resolve_local_function_tool(
            tool_name=contract.tool,
            attack_label="side-effect idempotency",
        )
        wrapped_target = copy(target)
        original_invoke = wrapped_target.on_invoke_tool
        observed: list[_ObservedAttempt] = []

        async def observe_side_effects(context: object, arguments: str) -> object:
            call_id_raw = _raw_attr(context, "tool_call_id")
            call_id = (
                call_id_raw
                if isinstance(call_id_raw, str)
                and bool(call_id_raw)
                and call_id_raw == call_id_raw.strip()
                else None
            )
            decoded, arguments_error = _decode_arguments(arguments, contract=contract)
            arguments_sha256 = canonical_json_sha256(decoded) if decoded is not None else None
            key_sha256 = (
                canonical_json_sha256(decoded[contract.key_argument])
                if decoded is not None and contract.key_argument in decoded
                else None
            )
            before_digest, before_error = await self._observe_effect_digest()

            output: object
            try:
                output = await original_invoke(context, arguments)
            finally:
                after_digest, after_error = await self._observe_effect_digest()
                errors = [
                    error
                    for error in (
                        "call identity unavailable" if call_id is None else None,
                        arguments_error,
                        before_error,
                        after_error,
                    )
                    if error is not None
                ]
                observed.append(
                    _ObservedAttempt(
                        call_id=call_id,
                        arguments=decoded,
                        arguments_sha256=arguments_sha256,
                        key_sha256=key_sha256,
                        before_effect_sha256=before_digest,
                        after_effect_sha256=after_digest,
                        observation_error="; ".join(errors) if errors else None,
                    )
                )
            return output

        wrapped_target.on_invoke_tool = observe_side_effects
        tools = [wrapped_target if tool is target else tool for tool in agent.tools]
        return agent.clone(tools=tools), observed

    async def _observe_effect_digest(self) -> tuple[str | None, str | None]:
        try:
            value = self._effect_reader()
            if inspect.isawaitable(value):
                value = await value
            normalized = canonicalize_json(value)
            return canonical_json_sha256(normalized), None
        except Exception as exc:
            return None, f"effect reader failed: {type(exc).__name__}"

    @staticmethod
    def _bind_observation(
        events: tuple[EvidenceEvent, ...],
        *,
        scenario: EvaluationScenario,
        observed: list[_ObservedAttempt],
    ) -> tuple[EvidenceEvent, ...]:
        contract = scenario.side_effect_idempotency
        if contract is None:  # pragma: no cover - execute() establishes this precondition
            raise AdapterPreconditionError(
                code="side_effect_contract_missing",
                reason="side-effect contract disappeared during one isolated execution",
            )

        if len(observed) != contract.attempts:
            raise AdapterPreconditionError(
                code=("side_effect_call_missing" if not observed else "side_effect_call_ambiguous"),
                reason="side-effect assurance requires exactly two target callback invocations",
            )
        if any(item.observation_error is not None for item in observed):
            raise AdapterPreconditionError(
                code="side_effect_observation_unavailable",
                reason="side-effect callback/effect relation could not be observed unambiguously",
            )

        requests = [
            event
            for event in events
            if event.kind is EvidenceKind.TOOL_REQUEST
            and event.payload.get("tool") == contract.tool
        ]
        if len(requests) != contract.attempts:
            raise AdapterPreconditionError(
                code=("side_effect_call_missing" if not requests else "side_effect_call_ambiguous"),
                reason="side-effect assurance requires exactly two normalized target requests",
            )

        attempts: list[SideEffectAttemptDigest] = []
        results: list[EvidenceEvent] = []
        for ordinal, (request, observation) in enumerate(
            zip(requests, observed, strict=True),
            start=1,
        ):
            call_id = request.payload.get("call_id")
            if not isinstance(call_id, str) or not call_id or call_id != call_id.strip():
                raise AdapterPreconditionError(
                    code="side_effect_call_identity_unavailable",
                    reason="target request cannot be bound to a stable OpenAI call identity",
                )
            if observation.call_id != call_id:
                raise AdapterPreconditionError(
                    code="side_effect_call_identity_mismatch",
                    reason="callback call identity does not match normalized OpenAI request identity",
                )
            decoded = _require_exact_arguments(
                request.payload.get("arguments"),
                contract=contract,
            )
            if observation.arguments != decoded:
                raise AdapterPreconditionError(
                    code="side_effect_argument_observation_mismatch",
                    reason="callback arguments do not match normalized OpenAI request arguments",
                )
            if (
                observation.arguments_sha256 is None
                or observation.key_sha256 is None
                or observation.before_effect_sha256 is None
                or observation.after_effect_sha256 is None
            ):
                raise AdapterPreconditionError(
                    code="side_effect_observation_unavailable",
                    reason="side-effect observation is missing one or more required digests",
                )

            matching_results = [
                event
                for event in events
                if event.kind is EvidenceKind.TOOL_RESULT
                and event.payload.get("call_id") == call_id
            ]
            if len(matching_results) != 1:
                raise AdapterPreconditionError(
                    code="side_effect_result_ambiguous",
                    reason="each target request requires exactly one normalized OpenAI tool result",
                )
            results.append(matching_results[0])
            attempts.append(
                SideEffectAttemptDigest(
                    ordinal=ordinal,
                    call_id=call_id,
                    arguments_sha256=observation.arguments_sha256,
                    key_sha256=observation.key_sha256,
                    before_effect_sha256=observation.before_effect_sha256,
                    after_effect_sha256=observation.after_effect_sha256,
                    mutated=(observation.before_effect_sha256 != observation.after_effect_sha256),
                )
            )

        if attempts[0].call_id == attempts[1].call_id:
            raise AdapterPreconditionError(
                code="side_effect_call_identity_reused",
                reason="duplicate logical-operation attempts require distinct OpenAI call identities",
            )

        try:
            receipt = SideEffectIdempotencyReceipt.create(
                scenario_identity=scenario.identity,
                contract=contract,
                attempts=(attempts[0], attempts[1]),
            )
        except (SideEffectReceiptError, ValidationError, ValueError) as exc:
            raise AdapterPreconditionError(
                code="side_effect_relation_unverified",
                reason="observed callback/effect chronology cannot close the idempotency relation",
            ) from exc

        second_result = results[1]
        rebound: list[EvidenceEvent] = []
        inserted = False
        for event in events:
            rebound.append(event.model_copy(update={"sequence": len(rebound)}))
            if event is second_result:
                rebound.append(receipt.to_event(sequence=len(rebound)))
                inserted = True
        if not inserted:  # pragma: no cover - result selection above guarantees insertion
            raise AdapterPreconditionError(
                code="side_effect_result_unavailable",
                reason="side-effect receipt could not be placed into normalized chronology",
            )
        return tuple(rebound)


def _decode_arguments(
    arguments: str,
    *,
    contract: SideEffectIdempotencySpec,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        decoded = json.loads(arguments, object_pairs_hook=_reject_duplicate_keys)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, "target arguments are not strict JSON"
    if not isinstance(decoded, dict):
        return None, "target arguments are not a JSON object"
    if decoded != contract.expected_arguments:
        return decoded, "target arguments do not equal the scenario-bound logical operation"
    return decoded, None


def _require_exact_arguments(
    arguments: object,
    *,
    contract: SideEffectIdempotencySpec,
) -> dict[str, Any]:
    if not isinstance(arguments, str):
        raise AdapterPreconditionError(
            code="side_effect_arguments_unverified",
            reason="target request arguments are not JSON text",
        )
    decoded, error = _decode_arguments(arguments, contract=contract)
    if error is not None or decoded is None:
        raise AdapterPreconditionError(
            code="side_effect_arguments_mismatch",
            reason="duplicate target requests do not equal the scenario-bound logical operation",
        )
    return decoded


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object member")
        result[key] = value
    return result


def _raw_attr(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)
