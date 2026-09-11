from __future__ import annotations

from agent_evals.contracts.models import AuthorityPolicy, HandoffAuthorityGrant
from agent_evals.contracts.resource import ResourceScope
from agent_evals.metamorphic.relations import MetamorphicDecision, authority_does_not_expand


def scope(*components: str, domain: str = "tenant") -> ResourceScope:
    return ResourceScope(domain=domain, components=components)


def _root_policy(
    *grants: HandoffAuthorityGrant,
    root_agent: str | None = "router",
) -> AuthorityPolicy:
    return AuthorityPolicy(
        allowed_tools=frozenset({"read", "write"}),
        approval_required_tools=frozenset({"write"}),
        allowed_resource_scopes=(scope("7"),),
        max_turns=20,
        max_tool_calls=20,
        max_handoffs=5,
        root_agent=root_agent,
        handoff_grants=grants,
    )


def _grant(
    *,
    source: str = "router",
    target: str = "specialist",
    tools: frozenset[str] = frozenset({"read"}),
    resources: tuple[ResourceScope, ...] = (ResourceScope(domain="tenant", components=("7", "orders")),),
    approvals: frozenset[str] = frozenset(),
    max_tool_calls: int = 8,
    max_handoffs: int = 2,
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


def test_authority_monotonicity_rejects_removing_delegated_attenuation() -> None:
    baseline = _root_policy(_grant())
    transformed = _root_policy(root_agent=None)

    result = authority_does_not_expand(baseline, transformed)

    assert result.decision is MetamorphicDecision.VIOLATED
    assert "delegated handoff attenuation removed" in result.reasons[0]


def test_authority_monotonicity_rejects_new_delegation_transition() -> None:
    baseline = _root_policy(_grant())
    transformed = _root_policy(
        _grant(),
        _grant(source="specialist", target="auditor", max_tool_calls=4, max_handoffs=1),
    )

    result = authority_does_not_expand(baseline, transformed)

    assert result.decision is MetamorphicDecision.VIOLATED
    assert any("new delegated handoff transitions" in reason for reason in result.reasons)


def test_authority_monotonicity_rejects_retained_grant_tool_expansion() -> None:
    baseline = _root_policy(_grant(tools=frozenset({"read"})))
    transformed = _root_policy(_grant(tools=frozenset({"read", "write"})))

    result = authority_does_not_expand(baseline, transformed)

    assert result.decision is MetamorphicDecision.VIOLATED
    assert any("delegated tools broadened" in reason for reason in result.reasons)


def test_authority_monotonicity_rejects_delegated_approval_weakening() -> None:
    baseline = _root_policy(_grant(tools=frozenset({"read"}), approvals=frozenset({"read"})))
    transformed = _root_policy(_grant(tools=frozenset({"read"}), approvals=frozenset()))

    result = authority_does_not_expand(baseline, transformed)

    assert result.decision is MetamorphicDecision.VIOLATED
    assert any("delegated approval requirement removed" in reason for reason in result.reasons)


def test_authority_monotonicity_rejects_delegated_resource_and_budget_expansion() -> None:
    baseline = _root_policy(
        _grant(
            resources=(scope("7", "orders"),),
            max_tool_calls=4,
            max_handoffs=1,
        )
    )
    transformed = _root_policy(
        _grant(
            resources=(scope("7"),),
            max_tool_calls=8,
            max_handoffs=2,
        )
    )

    result = authority_does_not_expand(baseline, transformed)

    assert result.decision is MetamorphicDecision.VIOLATED
    assert any("delegated resource scope broadened" in reason for reason in result.reasons)
    assert any("delegated tool-call budget expanded" in reason for reason in result.reasons)
    assert any("delegated handoff budget expanded" in reason for reason in result.reasons)


def test_authority_monotonicity_rejects_delegated_component_prefix_collision() -> None:
    baseline = _root_policy(_grant(resources=(scope("1"),)))
    transformed = _root_policy(_grant(resources=(scope("10"),)))

    result = authority_does_not_expand(baseline, transformed)

    assert result.decision is MetamorphicDecision.VIOLATED
    assert any("delegated resource scope broadened" in reason for reason in result.reasons)


def test_authority_monotonicity_accepts_path_local_delegation_narrowing() -> None:
    baseline = _root_policy(
        _grant(
            tools=frozenset({"read", "write"}),
            resources=(scope("7"),),
            approvals=frozenset({"write"}),
            max_tool_calls=12,
            max_handoffs=3,
        )
    )
    transformed = _root_policy(
        _grant(
            tools=frozenset({"read"}),
            resources=(scope("7", "orders"),),
            max_tool_calls=4,
            max_handoffs=1,
        )
    )

    result = authority_does_not_expand(baseline, transformed)

    assert result.decision is MetamorphicDecision.SATISFIED
    assert result.reasons == ()


def test_authority_monotonicity_accepts_graph_added_to_single_authority_root_as_attenuation() -> None:
    baseline = _root_policy(root_agent=None)
    transformed = _root_policy(_grant())

    result = authority_does_not_expand(baseline, transformed)

    assert result.decision is MetamorphicDecision.SATISFIED
    assert result.reasons == ()
