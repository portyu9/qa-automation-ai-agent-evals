"""Scenario-aware OpenAI execution for specialized evaluator-owned bridges.

Specialized adapters may instrument retrieval, side effects, or protocol/MCP boundaries before
subject execution. They must not independently choose a weaker OpenAI normalization path when the
same scenario also enables delegated handoff authority. This module is the single composition
point: ordinary scenarios use the base adapter; handoff-authority scenarios use the stronger SDK
run-item attribution adapter.

Direct users of :class:`OpenAIAgentsAdapter` retain its existing contract. Only specialized bridges
that explicitly delegate through :func:`execute_composed_openai` opt into this stronger composition
rule.
"""

from __future__ import annotations

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.openai_agents import OpenAIAgentsAdapter, ResourceResolver, StateReader
from agent_evals.adapters.openai_handoff_authority import OpenAIAgentsHandoffAuthorityAdapter
from agent_evals.contracts.models import EvaluationScenario, SubjectFingerprint


async def execute_composed_openai(
    agent: object,
    *,
    state_reader: StateReader,
    subject: SubjectFingerprint,
    scenario: EvaluationScenario,
    trial_id: str,
    resource_resolver: ResourceResolver | None = None,
    run_context: object | None = None,
    tracing_disabled: bool = True,
) -> AdapterResult:
    """Execute one specialized OpenAI bridge with the provenance strength its scenario requires."""
    adapter_type = (
        OpenAIAgentsHandoffAuthorityAdapter
        if scenario.authority.has_handoff_authority
        else OpenAIAgentsAdapter
    )
    return await adapter_type(
        agent,
        state_reader=state_reader,
        resource_resolver=resource_resolver,
        run_context=run_context,
        tracing_disabled=tracing_disabled,
    ).execute(
        subject=subject,
        scenario=scenario,
        trial_id=trial_id,
    )
