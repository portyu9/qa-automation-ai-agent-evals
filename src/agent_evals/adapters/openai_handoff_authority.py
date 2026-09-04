"""OpenAI Agents SDK adapter with evidence-bound native handoff authority attribution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from agent_evals.adapters.base import AdapterPreconditionError
from agent_evals.adapters.openai_agents import OpenAIAgentsAdapter
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind


class OpenAIAgentsHandoffAuthorityAdapter(OpenAIAgentsAdapter):
    """Normalize public SDK run-item agent identity for delegated-authority grading.

    The base adapter owns SDK execution and event normalization. This stronger adapter adds one
    provenance requirement: every normalized tool request/result/approval request is bound to the
    public ``RunItemBase.agent.name`` that generated the corresponding SDK item. Native handoff
    items are also checked so the generating agent agrees with the SDK's explicit source agent.

    Authority itself remains framework-owned by ``AuthorityPolicy`` and ``PolicyOracle``. SDK agent
    names are scoped run-local evidence identities, not cryptographic or globally unique principals.
    """

    @property
    def name(self) -> str:
        return "openai-agents-handoff-authority"

    def _normalize_items(
        self,
        items: Sequence[object],
        *,
        start_sequence: int = 0,
        tool_result_recorder: Any | None = None,
        environment_recorder: Any | None = None,
        handoff_recorder: Any | None = None,
    ) -> list[EvidenceEvent]:
        from agents.items import (
            HandoffOutputItem,
            ToolApprovalItem,
            ToolCallItem,
            ToolCallOutputItem,
        )

        request_agents: dict[str, str] = {}
        result_agents: dict[str, str] = {}
        approval_agents: dict[str, str] = {}

        for item in items:
            if isinstance(item, ToolCallItem):
                call_id = _tool_call_item_id(item)
                request_agents[call_id] = _record_unique_agent(
                    request_agents,
                    call_id=call_id,
                    item=item,
                    phase="tool request",
                )
            elif isinstance(item, ToolCallOutputItem):
                call_id = _required_call_id(item.call_id, phase="tool result")
                result_agents[call_id] = _record_unique_agent(
                    result_agents,
                    call_id=call_id,
                    item=item,
                    phase="tool result",
                )
            elif isinstance(item, ToolApprovalItem):
                call_id = _required_call_id(item.call_id, phase="approval request")
                approval_agents[call_id] = _record_unique_agent(
                    approval_agents,
                    call_id=call_id,
                    item=item,
                    phase="approval request",
                )
            elif isinstance(item, HandoffOutputItem):
                generating_agent = _required_agent_name(item, phase="handoff")
                source_agent = _required_identity(item.source_agent.name, phase="handoff source")
                _required_identity(item.target_agent.name, phase="handoff target")
                if generating_agent != source_agent:
                    raise AdapterPreconditionError(
                        code="handoff_source_identity_mismatch",
                        reason=(
                            "OpenAI handoff run-item generating agent does not match the SDK handoff "
                            "source agent"
                        ),
                    )

        normalized = super()._normalize_items(
            items,
            start_sequence=start_sequence,
            tool_result_recorder=tool_result_recorder,
            environment_recorder=environment_recorder,
            handoff_recorder=handoff_recorder,
        )

        attributed: list[EvidenceEvent] = []
        for event in normalized:
            agent: str | None = None
            call_id = event.payload.get("call_id")
            if event.kind is EvidenceKind.TOOL_REQUEST:
                agent = _event_agent_for_call(
                    request_agents,
                    call_id,
                    phase="normalized tool request",
                )
            elif event.kind is EvidenceKind.TOOL_RESULT:
                agent = _event_agent_for_call(
                    result_agents,
                    call_id,
                    phase="normalized tool result",
                )
            elif event.kind is EvidenceKind.APPROVAL_REQUEST:
                agent = _event_agent_for_call(
                    approval_agents,
                    call_id,
                    phase="normalized approval request",
                )

            if agent is None:
                attributed.append(event)
                continue
            payload = dict(event.payload)
            payload["agent"] = agent
            attributed.append(event.model_copy(update={"payload": payload}))

        return attributed


def _record_unique_agent(
    existing: Mapping[str, str],
    *,
    call_id: str,
    item: object,
    phase: str,
) -> str:
    if call_id in existing:
        raise AdapterPreconditionError(
            code="openai_agent_call_identity_ambiguous",
            reason=f"OpenAI {phase} reused a call identity within one normalized run",
        )
    return _required_agent_name(item, phase=phase)


def _event_agent_for_call(
    agents: Mapping[str, str],
    call_id: object,
    *,
    phase: str,
) -> str:
    stable_call_id = _required_call_id(call_id, phase=phase)
    agent = agents.get(stable_call_id)
    if agent is None:
        raise AdapterPreconditionError(
            code="openai_agent_attribution_missing",
            reason=f"{phase} has no matching public SDK run-item agent identity",
        )
    return agent


def _tool_call_item_id(item: object) -> str:
    raw_item = getattr(item, "raw_item", None)
    call_id = _raw_attr(raw_item, "call_id") or _raw_attr(raw_item, "id")
    return _required_call_id(call_id, phase="tool request")


def _required_call_id(value: object, *, phase: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise AdapterPreconditionError(
            code="openai_agent_call_identity_missing",
            reason=f"OpenAI {phase} lacks a stable non-empty call identity",
        )
    return value


def _required_agent_name(item: object, *, phase: str) -> str:
    agent = getattr(item, "agent", None)
    return _required_identity(getattr(agent, "name", None), phase=f"{phase} agent")


def _required_identity(value: object, *, phase: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise AdapterPreconditionError(
            code="openai_agent_identity_unavailable",
            reason=f"OpenAI {phase} lacks a stable non-empty SDK agent name",
        )
    return value


def _raw_attr(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)
