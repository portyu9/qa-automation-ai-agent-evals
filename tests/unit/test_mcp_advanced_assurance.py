from __future__ import annotations

import hashlib
import json

import pytest
from pydantic import ValidationError

from agent_evals.mcp.advanced import (
    MCPCapability,
    MCPCapabilityExerciseReceipt,
    MCPCapabilityOperationObservation,
    MCPCapabilitySnapshot,
    MCPConcurrencyReceipt,
    MCPConcurrentOperation,
    MCPHostedEndpointSpec,
    MCPHostileServerBudget,
    MCPHostileServerObservation,
    MCPHostileServerReceipt,
    MCPMultiServerReceipt,
    MCPRemoteAssuranceReceipt,
    MCPRemoteCondition,
    MCPRemotePolicy,
    MCPRemoteProbeObservation,
    MCPServerSurface,
    MCPToolsListChangedReceipt,
)
from agent_evals.mcp.oauth_advanced import (
    OAuthAdvancedPolicy,
    OAuthAdvancedReceipt,
    OAuthAuthorizationDriftReceipt,
    OAuthAuthorizationEpoch,
    OAuthKeySetSnapshot,
    OAuthSenderBinding,
    OAuthSessionEvent,
    OAuthSessionEventKind,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _endpoint() -> MCPHostedEndpointSpec:
    return MCPHostedEndpointSpec(
        endpoint_id="hosted.primary",
        url="https://mcp.example.test/rpc",
        expected_server_identity="remote-mcp",
        max_latency_ms=500,
    )


def _remote_observation(
    endpoint: MCPHostedEndpointSpec,
    condition: MCPRemoteCondition,
) -> MCPRemoteProbeObservation:
    if condition is MCPRemoteCondition.HEALTHY:
        return MCPRemoteProbeObservation(
            endpoint_identity=endpoint.identity,
            condition=condition,
            dns_resolved=True,
            tls_verified=True,
            connected=True,
            latency_ms=25,
            http_status=200,
            response_bytes=512,
            stream_frames=1,
            complete=True,
            protocol_valid=True,
            observed_server_identity="remote-mcp",
        )
    kwargs: dict[str, object] = {
        "endpoint_identity": endpoint.identity,
        "condition": condition,
        "dns_resolved": condition is not MCPRemoteCondition.DNS_FAILURE,
        "tls_verified": condition
        not in {
            MCPRemoteCondition.TLS_FAILURE,
            MCPRemoteCondition.DNS_FAILURE,
            MCPRemoteCondition.PROXY_FAILURE,
        },
        "connected": condition
        not in {
            MCPRemoteCondition.TLS_FAILURE,
            MCPRemoteCondition.DNS_FAILURE,
            MCPRemoteCondition.PROXY_FAILURE,
            MCPRemoteCondition.DISCONNECT,
        },
        "latency_ms": 40,
        "complete": False,
        "protocol_valid": False,
        "error_code": condition.value,
    }
    if condition is MCPRemoteCondition.RATE_LIMIT:
        kwargs["http_status"] = 429
        kwargs["retry_after_ms"] = 1000
    return MCPRemoteProbeObservation(**kwargs)


def test_hosted_remote_policy_covers_transport_fault_classes() -> None:
    endpoint = _endpoint()
    policy = MCPRemotePolicy()
    observations = tuple(
        _remote_observation(endpoint, condition)
        for condition in sorted(policy.required_conditions, key=lambda item: item.value)
    )

    receipt = MCPRemoteAssuranceReceipt.create(
        endpoint=endpoint,
        policy=policy,
        observations=observations,
    )

    assert receipt.accepted is True
    assert set(receipt.covered_conditions) == set(policy.required_conditions)
    assert "behavioral" not in receipt.model_dump_json()

    wrong_identity = list(observations)
    healthy_index = next(
        index
        for index, item in enumerate(wrong_identity)
        if item.condition is MCPRemoteCondition.HEALTHY
    )
    wrong_identity[healthy_index] = wrong_identity[healthy_index].model_copy(
        update={"observed_server_identity": "other-server"}
    )
    rejected = MCPRemoteAssuranceReceipt.create(
        endpoint=endpoint,
        policy=policy,
        observations=tuple(wrong_identity),
    )
    assert rejected.accepted is False

    with pytest.raises(ValidationError, match="absolute https"):
        MCPHostedEndpointSpec(
            endpoint_id="hosted.bad",
            url="http://mcp.example.test/rpc",
            expected_server_identity="remote-mcp",
        )


def test_advanced_capabilities_list_changed_concurrency_and_multi_server_collision() -> None:
    snapshot = MCPCapabilitySnapshot(
        server_identity="remote-mcp",
        capabilities=frozenset(MCPCapability),
        capability_revision="cap-v2",
    )
    assert set(snapshot.capabilities) == set(MCPCapability)
    assert len(snapshot.identity) == 64

    exercised = MCPCapabilityExerciseReceipt.create(
        snapshot=snapshot,
        observations=tuple(
            MCPCapabilityOperationObservation(
                capability=capability,
                operation_id=f"exercise.{index}",
                request_sha256=_sha(f"request:{capability.value}"),
                response_sha256=_sha(f"response:{capability.value}"),
                response_bytes=128,
                succeeded=True,
            )
            for index, capability in enumerate(sorted(MCPCapability, key=lambda item: item.value))
        ),
    )
    assert exercised.accepted is True
    assert set(exercised.exercised_capabilities) == set(MCPCapability)

    limited_snapshot = MCPCapabilitySnapshot(
        server_identity="remote-mcp",
        capabilities=frozenset({MCPCapability.RESOURCES}),
        capability_revision="cap-limited",
    )
    limited = MCPCapabilityExerciseReceipt.create(
        snapshot=limited_snapshot,
        observations=(
            MCPCapabilityOperationObservation(
                capability=MCPCapability.RESOURCES,
                operation_id="exercise.limited-resources",
                request_sha256=_sha("limited-request"),
                response_sha256=_sha("limited-response"),
                response_bytes=64,
                succeeded=True,
            ),
        ),
    )
    assert limited.accepted is False

    incomplete = MCPCapabilityExerciseReceipt.create(
        snapshot=snapshot,
        observations=(
            MCPCapabilityOperationObservation(
                capability=MCPCapability.RESOURCES,
                operation_id="exercise.resources",
                request_sha256=_sha("request"),
                response_sha256=_sha("response"),
                response_bytes=64,
                succeeded=True,
            ),
        ),
    )
    assert incomplete.accepted is False

    changed = MCPToolsListChangedReceipt.create(
        server_identity="remote-mcp",
        before_tools=("read",),
        after_tools=("read", "write"),
        notification_sequence=7,
    )
    assert changed.before_tools == ("read",)
    assert changed.after_tools == ("read", "write")

    operations = tuple(
        MCPConcurrentOperation(
            request_id=f"req-{index}",
            server_identity="remote-mcp",
            target_identity=f"tool-{index}",
            started_tick=index,
            completed_tick=index + 4,
            outcome_sha256=_sha(str(index)),
        )
        for index in range(3)
    )
    concurrency = MCPConcurrencyReceipt.create(operations=operations, minimum_parallelism=3)
    assert concurrency.peak_parallelism == 3
    assert concurrency.accepted is True

    collision = MCPMultiServerReceipt.create(
        (
            MCPServerSurface(server_identity="a", tool_names=("lookup", "alpha")),
            MCPServerSurface(server_identity="b", tool_names=("lookup", "beta")),
        )
    )
    assert collision.accepted is False
    assert collision.collision_names == ("lookup",)

    isolated = MCPMultiServerReceipt.create(
        (
            MCPServerSurface(server_identity="a", tool_names=("alpha",)),
            MCPServerSurface(server_identity="b", tool_names=("beta",)),
        )
    )
    assert isolated.accepted is True


def test_hostile_server_resource_limits_preserve_fault_classes() -> None:
    budget = MCPHostileServerBudget(
        max_response_bytes=100,
        max_duration_ms=100,
        max_protocol_messages=10,
    )
    observations = (
        MCPHostileServerObservation(
            condition=MCPRemoteCondition.OVERSIZED_RESPONSE,
            response_bytes=101,
            duration_ms=5,
            protocol_messages=1,
            terminated_by_evaluator=True,
            escaped_budget=False,
        ),
        MCPHostileServerObservation(
            condition=MCPRemoteCondition.HANG_TIMEOUT,
            response_bytes=0,
            duration_ms=101,
            protocol_messages=0,
            terminated_by_evaluator=True,
            escaped_budget=False,
        ),
        MCPHostileServerObservation(
            condition=MCPRemoteCondition.PROTOCOL_TRICKERY,
            response_bytes=10,
            duration_ms=10,
            protocol_messages=11,
            terminated_by_evaluator=True,
            escaped_budget=False,
        ),
        MCPHostileServerObservation(
            condition=MCPRemoteCondition.RESOURCE_PRESSURE,
            response_bytes=10,
            duration_ms=10,
            protocol_messages=11,
            terminated_by_evaluator=True,
            escaped_budget=False,
        ),
    )
    receipt = MCPHostileServerReceipt.create(budget=budget, observations=observations)

    assert receipt.accepted is True
    incomplete = MCPHostileServerReceipt.create(
        budget=budget,
        observations=(observations[0],),
    )
    assert incomplete.accepted is False
    assert set(receipt.covered_conditions) == {
        MCPRemoteCondition.OVERSIZED_RESPONSE,
        MCPRemoteCondition.HANG_TIMEOUT,
        MCPRemoteCondition.PROTOCOL_TRICKERY,
        MCPRemoteCondition.RESOURCE_PRESSURE,
    }

    escaped = list(observations)
    escaped[0] = escaped[0].model_copy(update={"escaped_budget": True})
    assert (
        MCPHostileServerReceipt.create(budget=budget, observations=tuple(escaped)).accepted is False
    )


def _oauth_event(
    *,
    event_id: str,
    kind: OAuthSessionEventKind,
    epoch: int,
    token: str,
    kid: str,
    parent: str | None = None,
    accepted: bool = True,
) -> OAuthSessionEvent:
    return OAuthSessionEvent(
        event_id=event_id,
        kind=kind,
        epoch=epoch,
        issuer="https://idp.example.test",
        subject="user-7",
        audience="https://api.example.test",
        token_sha256=_sha(token),
        jti_sha256=_sha(f"jti:{event_id}"),
        signing_kid=kid,
        scopes=frozenset({"read", "write"}),
        sender_binding=OAuthSenderBinding.DPOP,
        sender_key_sha256=_sha("dpop-key"),
        sender_binding_verified=True,
        jwt_signature_verified=True,
        accepted_by_resource=accepted,
        parent_token_sha256=None if parent is None else _sha(parent),
    )


def test_advanced_oauth_rotation_refresh_revocation_replay_and_sender_binding() -> None:
    keysets = (
        OAuthKeySetSnapshot(
            issuer="https://idp.example.test",
            jwks_uri="https://idp.example.test/jwks",
            key_ids=("kid-a",),
            epoch=0,
            verifier_revision="1",
        ),
        OAuthKeySetSnapshot(
            issuer="https://idp.example.test",
            jwks_uri="https://idp.example.test/jwks",
            key_ids=("kid-b",),
            epoch=1,
            verifier_revision="1",
        ),
    )
    events = (
        _oauth_event(
            event_id="event.initial",
            kind=OAuthSessionEventKind.INITIAL,
            epoch=0,
            token="token-a",
            kid="kid-a",
        ),
        _oauth_event(
            event_id="event.refresh",
            kind=OAuthSessionEventKind.REFRESH,
            epoch=1,
            token="token-b",
            kid="kid-b",
            parent="token-a",
        ),
        _oauth_event(
            event_id="event.revoke",
            kind=OAuthSessionEventKind.REVOKE,
            epoch=2,
            token="token-a",
            kid="kid-a",
            accepted=False,
        ),
        _oauth_event(
            event_id="event.replay",
            kind=OAuthSessionEventKind.REPLAY,
            epoch=3,
            token="token-a",
            kid="kid-a",
            accepted=False,
        ),
    )
    policy = OAuthAdvancedPolicy(allowed_issuers=frozenset({"https://idp.example.test"}))

    receipt = OAuthAdvancedReceipt.create(policy=policy, keysets=keysets, events=events)

    assert receipt.accepted is True
    assert receipt.key_rotation_observed is True
    assert receipt.refresh_observed is True
    assert receipt.revocation_rejected is True
    assert receipt.replay_rejected is True
    assert receipt.sender_constraint_observed is True

    tampered = json.loads(receipt.model_dump_json())
    tampered["accepted"] = False
    with pytest.raises(ValidationError, match="metrics do not recompute"):
        OAuthAdvancedReceipt.model_validate(tampered)


def test_oauth_active_session_authorization_drift_requires_post_contraction_denial() -> None:
    receipt = OAuthAuthorizationDriftReceipt.create(
        (
            OAuthAuthorizationEpoch(
                epoch=0,
                scopes=frozenset({"read", "write"}),
                resource_identity="tenant/7",
                operation="write",
                allowed=True,
            ),
            OAuthAuthorizationEpoch(
                epoch=1,
                scopes=frozenset({"read"}),
                resource_identity="tenant/7",
                operation="write",
                allowed=False,
            ),
        )
    )
    assert receipt.contraction_observed is True
    assert receipt.post_contraction_denial_observed is True
    assert receipt.accepted is True

    no_denial = OAuthAuthorizationDriftReceipt.create(
        (
            OAuthAuthorizationEpoch(
                epoch=0,
                scopes=frozenset({"read", "write"}),
                resource_identity="tenant/7",
                operation="write",
                allowed=True,
            ),
            OAuthAuthorizationEpoch(
                epoch=1,
                scopes=frozenset({"read"}),
                resource_identity="tenant/7",
                operation="write",
                allowed=True,
            ),
        )
    )
    assert no_denial.accepted is False

    with pytest.raises(ValueError, match="one resource and operation"):
        OAuthAuthorizationDriftReceipt.create(
            (
                OAuthAuthorizationEpoch(
                    epoch=0,
                    scopes=frozenset({"read", "write"}),
                    resource_identity="tenant/7",
                    operation="write",
                    allowed=True,
                ),
                OAuthAuthorizationEpoch(
                    epoch=1,
                    scopes=frozenset({"read"}),
                    resource_identity="tenant/7",
                    operation="read",
                    allowed=False,
                ),
            )
        )

def test_unordered_mcp_and_oauth_material_is_canonical_and_root_stable() -> None:
    endpoint = _endpoint()
    conditions = list(MCPRemotePolicy().required_conditions)
    policy_a = MCPRemotePolicy(required_conditions=frozenset(conditions))
    policy_b = MCPRemotePolicy(required_conditions=frozenset(reversed(conditions)))
    observations = tuple(
        _remote_observation(endpoint, condition)
        for condition in sorted(policy_a.required_conditions, key=lambda item: item.value)
    )
    remote_a = MCPRemoteAssuranceReceipt.create(
        endpoint=endpoint,
        policy=policy_a,
        observations=observations,
    )
    remote_b = MCPRemoteAssuranceReceipt.create(
        endpoint=endpoint,
        policy=policy_b,
        observations=observations,
    )
    assert policy_a.model_dump_json() == policy_b.model_dump_json()
    assert remote_a.receipt_root == remote_b.receipt_root
    assert (
        MCPRemoteAssuranceReceipt.model_validate_json(remote_a.model_dump_json()).receipt_root
        == remote_a.receipt_root
    )

    capabilities = list(MCPCapability)
    snapshot_a = MCPCapabilitySnapshot(
        server_identity="canonical-mcp",
        capabilities=frozenset(capabilities),
        capability_revision="canonical-v1",
    )
    snapshot_b = MCPCapabilitySnapshot(
        server_identity="canonical-mcp",
        capabilities=frozenset(reversed(capabilities)),
        capability_revision="canonical-v1",
    )
    assert snapshot_a.model_dump_json() == snapshot_b.model_dump_json()
    assert snapshot_a.identity == snapshot_b.identity

    hostile_conditions = [
        MCPRemoteCondition.OVERSIZED_RESPONSE,
        MCPRemoteCondition.HANG_TIMEOUT,
        MCPRemoteCondition.PROTOCOL_TRICKERY,
        MCPRemoteCondition.RESOURCE_PRESSURE,
    ]
    budget_a = MCPHostileServerBudget(
        required_conditions=frozenset(hostile_conditions),
        max_response_bytes=100,
        max_duration_ms=100,
        max_protocol_messages=10,
    )
    budget_b = MCPHostileServerBudget(
        required_conditions=frozenset(reversed(hostile_conditions)),
        max_response_bytes=100,
        max_duration_ms=100,
        max_protocol_messages=10,
    )
    assert budget_a.model_dump_json() == budget_b.model_dump_json()

    issuers = ["https://idp.example.test", "https://backup-idp.example.test"]
    bindings = [OAuthSenderBinding.DPOP, OAuthSenderBinding.MTLS]
    oauth_policy_a = OAuthAdvancedPolicy(
        allowed_issuers=frozenset(issuers),
        allowed_sender_bindings=frozenset(bindings),
        require_key_rotation=False,
        require_refresh=False,
        require_revocation_rejection=False,
        require_replay_rejection=False,
    )
    oauth_policy_b = OAuthAdvancedPolicy(
        allowed_issuers=frozenset(reversed(issuers)),
        allowed_sender_bindings=frozenset(reversed(bindings)),
        require_key_rotation=False,
        require_refresh=False,
        require_revocation_rejection=False,
        require_replay_rejection=False,
    )
    keysets = (
        OAuthKeySetSnapshot(
            issuer="https://idp.example.test",
            jwks_uri="https://idp.example.test/jwks",
            key_ids=("kid-a",),
            epoch=0,
            verifier_revision="1",
        ),
    )
    event_a = _oauth_event(
        event_id="event.canonical",
        kind=OAuthSessionEventKind.INITIAL,
        epoch=0,
        token="canonical-token",
        kid="kid-a",
    )
    event_b = event_a.model_copy(update={"scopes": frozenset(("write", "read"))})
    oauth_a = OAuthAdvancedReceipt.create(
        policy=oauth_policy_a,
        keysets=keysets,
        events=(event_a,),
    )
    oauth_b = OAuthAdvancedReceipt.create(
        policy=oauth_policy_b,
        keysets=keysets,
        events=(event_b,),
    )

    assert oauth_policy_a.model_dump_json() == oauth_policy_b.model_dump_json()
    assert event_a.model_dump_json() == event_b.model_dump_json()
    assert oauth_a.receipt_root == oauth_b.receipt_root
    assert (
        OAuthAdvancedReceipt.model_validate_json(oauth_a.model_dump_json()).receipt_root
        == oauth_a.receipt_root
    )

    drift_a = OAuthAuthorizationDriftReceipt.create(
        (
            OAuthAuthorizationEpoch(
                epoch=0,
                scopes=frozenset(("write", "read")),
                resource_identity="tenant/canonical",
                operation="write",
                allowed=True,
            ),
            OAuthAuthorizationEpoch(
                epoch=1,
                scopes=frozenset(("read",)),
                resource_identity="tenant/canonical",
                operation="write",
                allowed=False,
            ),
        )
    )
    drift_b = OAuthAuthorizationDriftReceipt.create(
        (
            OAuthAuthorizationEpoch(
                epoch=0,
                scopes=frozenset(("read", "write")),
                resource_identity="tenant/canonical",
                operation="write",
                allowed=True,
            ),
            OAuthAuthorizationEpoch(
                epoch=1,
                scopes=frozenset(("read",)),
                resource_identity="tenant/canonical",
                operation="write",
                allowed=False,
            ),
        )
    )
    assert drift_a.receipt_root == drift_b.receipt_root
    assert (
        OAuthAuthorizationDriftReceipt.model_validate_json(drift_a.model_dump_json()).receipt_root
        == drift_a.receipt_root
    )
