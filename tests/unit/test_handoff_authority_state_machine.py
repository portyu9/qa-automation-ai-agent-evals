from __future__ import annotations

import pytest
from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from agent_evals.authority import HandoffPathState, advance_handoff
from agent_evals.contracts.models import AuthorityPolicy, HandoffAuthorityGrant
from agent_evals.contracts.resource import ResourceScope
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind

_ROOT = "root-agent"
_SPECIALIST = "specialist-agent"
_WORKER = "worker-agent"
_REEXPANDED = "reexpanded-agent"
_UNKNOWN = "unknown-agent"


def scope(*components: str) -> ResourceScope:
    return ResourceScope(domain="tenant", components=components)


def _grant(
    source: str,
    target: str,
    *,
    tools: frozenset[str],
    resources: tuple[ResourceScope, ...],
    approvals: frozenset[str] = frozenset(),
    max_tool_calls: int,
    max_handoffs: int,
) -> HandoffAuthorityGrant:
    return HandoffAuthorityGrant(
        source_agent=source,
        target_agent=target,
        allowed_tools=tools,
        allowed_resource_scopes=resources,
        additional_approval_required_tools=approvals,
        max_tool_calls=max_tool_calls,
        max_handoffs=max_handoffs,
    )


def _policy() -> AuthorityPolicy:
    return AuthorityPolicy(
        allowed_tools=frozenset({"read", "write", "refund"}),
        approval_required_tools=frozenset({"refund"}),
        allowed_resource_scopes=(scope("7"),),
        max_tool_calls=8,
        max_handoffs=3,
        root_agent=_ROOT,
        handoff_grants=(
            _grant(
                _ROOT,
                _SPECIALIST,
                tools=frozenset({"read", "write"}),
                resources=(scope("7", "orders"),),
                approvals=frozenset({"write"}),
                max_tool_calls=4,
                max_handoffs=2,
            ),
            _grant(
                _SPECIALIST,
                _WORKER,
                tools=frozenset({"read"}),
                resources=(scope("7", "orders", "open"),),
                approvals=frozenset({"read"}),
                max_tool_calls=2,
                max_handoffs=1,
            ),
            # This grant is legal relative to root authority but broadens the authority that the
            # specialist actually inherited. Runtime path attenuation must reject it.
            _grant(
                _SPECIALIST,
                _REEXPANDED,
                tools=frozenset({"read", "write", "refund"}),
                resources=(scope("7"),),
                max_tool_calls=6,
                max_handoffs=3,
            ),
        ),
    )


def _handoff(source: object, target: object) -> EvidenceEvent:
    return EvidenceEvent(
        sequence=0,
        kind=EvidenceKind.HANDOFF,
        source="state-machine",
        payload={"source_agent": source, "target_agent": target},
    )


class HandoffAuthorityStateMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.policy = _policy()
        self.state = HandoffPathState.from_policy(self.policy)
        self.root_authority = self.state.authority

    @precondition(lambda self: self.state.active_agent == _ROOT)
    @rule()
    def accept_root_to_specialist(self) -> None:
        previous = self.state
        updated, reasons = advance_handoff(
            self.policy,
            previous,
            _handoff(_ROOT, _SPECIALIST),
        )

        assert reasons == ()
        assert updated.epoch == previous.epoch + 1
        assert updated.path_sha256 != previous.path_sha256
        self.state = updated

    @precondition(lambda self: self.state.active_agent == _SPECIALIST)
    @rule()
    def accept_specialist_to_worker(self) -> None:
        previous = self.state
        updated, reasons = advance_handoff(
            self.policy,
            previous,
            _handoff(_SPECIALIST, _WORKER),
        )

        assert reasons == ()
        assert updated.epoch == previous.epoch + 1
        assert updated.path_sha256 != previous.path_sha256
        self.state = updated

    @precondition(lambda self: self.state.active_agent == _SPECIALIST)
    @rule()
    def reject_path_local_reexpansion(self) -> None:
        previous = self.state
        updated, reasons = advance_handoff(
            self.policy,
            previous,
            _handoff(_SPECIALIST, _REEXPANDED),
        )

        assert updated == previous
        assert any("broadens source tool authority" in reason for reason in reasons)
        assert any("broadens source resource authority" in reason for reason in reasons)
        assert any("broadens source tool-call budget" in reason for reason in reasons)
        assert any("broadens source handoff budget" in reason for reason in reasons)

    @rule()
    def reject_non_active_source(self) -> None:
        active = self.state.active_agent
        if active == _ROOT:
            source, target = _SPECIALIST, _WORKER
        elif active == _SPECIALIST:
            source, target = _ROOT, _SPECIALIST
        else:
            source, target = _SPECIALIST, _WORKER

        previous = self.state
        updated, reasons = advance_handoff(
            self.policy,
            previous,
            _handoff(source, target),
        )

        assert updated == previous
        assert any("not the currently active agent" in reason for reason in reasons)

    @rule()
    def reject_unknown_target(self) -> None:
        previous = self.state
        updated, reasons = advance_handoff(
            self.policy,
            previous,
            _handoff(previous.active_agent, _UNKNOWN),
        )

        assert updated == previous
        assert any("unauthorized handoff transition" in reason for reason in reasons)

    @rule()
    def reject_malformed_identity(self) -> None:
        previous = self.state
        updated, reasons = advance_handoff(
            self.policy,
            previous,
            _handoff(previous.active_agent, " malformed "),
        )

        assert updated == previous
        assert any(
            "requires non-empty source_agent and target_agent" in reason for reason in reasons
        )

    @rule()
    def reject_non_handoff_event(self) -> None:
        event = EvidenceEvent(
            sequence=0,
            kind=EvidenceKind.STATE,
            source="state-machine",
            payload={},
        )
        with pytest.raises(ValueError, match="requires HANDOFF evidence"):
            advance_handoff(self.policy, self.state, event)

    @invariant()
    def accepted_path_is_exact_and_monotonic(self) -> None:
        assert self.state.epoch == len(self.state.transitions)
        assert self.state.root_agent == _ROOT
        assert self.state.authority.allowed_tools <= self.root_authority.allowed_tools
        assert self.state.authority.approval_required_tools <= self.state.authority.allowed_tools
        assert self.state.authority.max_tool_calls <= self.root_authority.max_tool_calls
        assert self.state.authority.max_handoffs <= self.root_authority.max_handoffs

        if self.state.active_agent == _ROOT:
            assert self.state.transitions == ()
            assert self.state.authority == self.root_authority
        elif self.state.active_agent == _SPECIALIST:
            assert self.state.transitions == ((_ROOT, _SPECIALIST),)
            assert self.state.authority.allowed_tools == frozenset({"read", "write"})
            assert self.state.authority.approval_required_tools == frozenset({"write"})
            assert self.state.authority.allowed_resource_scopes == (scope("7", "orders"),)
            assert self.state.authority.max_tool_calls == 4
            assert self.state.authority.max_handoffs == 2
        elif self.state.active_agent == _WORKER:
            assert self.state.transitions == (
                (_ROOT, _SPECIALIST),
                (_SPECIALIST, _WORKER),
            )
            assert self.state.authority.allowed_tools == frozenset({"read"})
            assert self.state.authority.approval_required_tools == frozenset({"read"})
            assert self.state.authority.allowed_resource_scopes == (
                scope("7", "orders", "open"),
            )
            assert self.state.authority.max_tool_calls == 2
            assert self.state.authority.max_handoffs == 1
        else:
            raise AssertionError(f"unexpected active agent: {self.state.active_agent!r}")


TestHandoffAuthorityStateMachine = HandoffAuthorityStateMachine.TestCase
TestHandoffAuthorityStateMachine.settings = settings(
    max_examples=100,
    stateful_step_count=30,
    deadline=None,
)
