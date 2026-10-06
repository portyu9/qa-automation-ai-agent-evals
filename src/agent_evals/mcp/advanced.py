"""Hosted/remote MCP and advanced protocol assurance contracts.

This module is deliberately separate from the local stdio fault laboratory and loopback
authorization laboratories. It can probe an arbitrary HTTPS Streamable-HTTP endpoint, but its
receipts remain protocol/control-plane evidence only. They never become agent behavioral PASS.
"""

from __future__ import annotations

import hashlib
import hmac
import http.client
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from enum import StrEnum
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from agent_evals._receipt_validation import (
    is_receipt_construction,
    validate_receipt_construction,
)

_PROTOCOL_VERSION = "2026-07-28"
_ENDPOINT_SCHEMA: Literal["agent-evals/mcp-hosted-endpoint/v1"] = (
    "agent-evals/mcp-hosted-endpoint/v1"
)
_REMOTE_POLICY_SCHEMA: Literal["agent-evals/mcp-remote-policy/v1"] = (
    "agent-evals/mcp-remote-policy/v1"
)
_REMOTE_OBSERVATION_SCHEMA: Literal["agent-evals/mcp-remote-observation/v1"] = (
    "agent-evals/mcp-remote-observation/v1"
)
_REMOTE_RECEIPT_SCHEMA: Literal["agent-evals/mcp-remote-receipt/v1"] = (
    "agent-evals/mcp-remote-receipt/v1"
)
_CAPABILITY_SCHEMA: Literal["agent-evals/mcp-capability-snapshot/v1"] = (
    "agent-evals/mcp-capability-snapshot/v1"
)
_CAPABILITY_EXERCISE_SCHEMA: Literal["agent-evals/mcp-capability-exercise-receipt/v1"] = (
    "agent-evals/mcp-capability-exercise-receipt/v1"
)
_LIST_CHANGED_SCHEMA: Literal["agent-evals/mcp-list-changed-receipt/v1"] = (
    "agent-evals/mcp-list-changed-receipt/v1"
)
_CONCURRENCY_SCHEMA: Literal["agent-evals/mcp-concurrency-receipt/v1"] = (
    "agent-evals/mcp-concurrency-receipt/v1"
)
_MULTI_SERVER_SCHEMA: Literal["agent-evals/mcp-multi-server-receipt/v1"] = (
    "agent-evals/mcp-multi-server-receipt/v1"
)
_HOSTILE_SCHEMA: Literal["agent-evals/mcp-hostile-server-receipt/v1"] = (
    "agent-evals/mcp-hostile-server-receipt/v1"
)
_REMOTE_RECEIPT_DOMAIN = b"agent-evals/mcp-remote-receipt/v1\0"
_CAPABILITY_EXERCISE_DOMAIN = b"agent-evals/mcp-capability-exercise-receipt/v1\0"
_LIST_CHANGED_DOMAIN = b"agent-evals/mcp-list-changed-receipt/v1\0"
_CONCURRENCY_DOMAIN = b"agent-evals/mcp-concurrency-receipt/v1\0"
_MULTI_SERVER_DOMAIN = b"agent-evals/mcp-multi-server-receipt/v1\0"
_HOSTILE_DOMAIN = b"agent-evals/mcp-hostile-server-receipt/v1\0"


class MCPRemoteCondition(StrEnum):
    HEALTHY = "healthy"
    TLS_FAILURE = "tls-failure"
    DNS_FAILURE = "dns-failure"
    PROXY_FAILURE = "proxy-failure"
    GATEWAY_FAILURE = "gateway-failure"
    LATENCY_LIMIT = "latency-limit"
    DISCONNECT = "disconnect"
    STREAM_INTERRUPTION = "stream-interruption"
    RATE_LIMIT = "rate-limit"
    OVERSIZED_RESPONSE = "oversized-response"
    HANG_TIMEOUT = "hang-timeout"
    PROTOCOL_TRICKERY = "protocol-trickery"
    RESOURCE_PRESSURE = "resource-pressure"


class MCPCapability(StrEnum):
    RESOURCES = "resources"
    PROMPTS = "prompts"
    ROOTS = "roots"
    SUBSCRIPTIONS = "subscriptions"
    ELICITATION = "elicitation"
    SAMPLING = "sampling"
    TASKS = "tasks"
    TOOLS_LIST_CHANGED = "tools/list_changed"


class MCPHostedEndpointSpec(BaseModel):
    """One external HTTPS MCP endpoint and bounded transport policy inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-hosted-endpoint/v1"] = _ENDPOINT_SCHEMA
    endpoint_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    url: str = Field(min_length=1, max_length=2048)
    expected_server_identity: str = Field(min_length=1, max_length=256)
    protocol_version: str = Field(default=_PROTOCOL_VERSION, min_length=1, max_length=64)
    proxy_url: str | None = Field(default=None, max_length=2048)
    gateway_identity: str | None = Field(default=None, min_length=1, max_length=256)
    timeout_ms: int = Field(default=5_000, ge=100, le=120_000, strict=True)
    max_latency_ms: int = Field(default=3_000, ge=1, le=120_000, strict=True)
    max_response_bytes: int = Field(default=2 * 1024 * 1024, ge=1, le=64 * 1024 * 1024, strict=True)
    max_stream_frames: int = Field(default=1_000, ge=1, le=100_000, strict=True)

    @field_validator("url")
    @classmethod
    def require_https(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("hosted MCP endpoint must be an absolute https URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("hosted MCP endpoint URL must not embed credentials")
        if parsed.fragment:
            raise ValueError("hosted MCP endpoint URL must not contain a fragment")
        return value

    @field_validator("proxy_url")
    @classmethod
    def validate_proxy(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("MCP proxy URL must be an absolute http/https URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("MCP proxy URL must not embed credentials")
        return value

    @property
    def identity(self) -> str:
        return _domain_root(b"agent-evals/mcp-hosted-endpoint/v1\0", self.model_dump(mode="json"))


class MCPRemotePolicy(BaseModel):
    """Required fault/transport classes for one hosted MCP qualification campaign."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-remote-policy/v1"] = _REMOTE_POLICY_SCHEMA
    required_conditions: frozenset[MCPRemoteCondition] = frozenset(
        {
            MCPRemoteCondition.HEALTHY,
            MCPRemoteCondition.TLS_FAILURE,
            MCPRemoteCondition.DNS_FAILURE,
            MCPRemoteCondition.PROXY_FAILURE,
            MCPRemoteCondition.GATEWAY_FAILURE,
            MCPRemoteCondition.LATENCY_LIMIT,
            MCPRemoteCondition.DISCONNECT,
            MCPRemoteCondition.STREAM_INTERRUPTION,
            MCPRemoteCondition.RATE_LIMIT,
        }
    )
    require_tls_on_healthy: bool = Field(default=True, strict=True)
    require_dns_on_healthy: bool = Field(default=True, strict=True)

    @model_validator(mode="after")
    def require_healthy_baseline(self) -> Self:
        if MCPRemoteCondition.HEALTHY not in self.required_conditions:
            raise ValueError("remote MCP policy must require a healthy baseline")
        return self


class MCPRemoteProbeObservation(BaseModel):
    """Bounded observation from one real or synthetic hosted-MCP transport probe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-remote-observation/v1"] = _REMOTE_OBSERVATION_SCHEMA
    endpoint_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    condition: MCPRemoteCondition
    dns_resolved: bool = Field(strict=True)
    tls_verified: bool = Field(strict=True)
    connected: bool = Field(strict=True)
    latency_ms: int = Field(ge=0, le=120_000, strict=True)
    http_status: int | None = Field(default=None, ge=100, le=599, strict=True)
    response_bytes: int = Field(default=0, ge=0, le=64 * 1024 * 1024 + 1, strict=True)
    stream_frames: int = Field(default=0, ge=0, le=100_001, strict=True)
    complete: bool = Field(strict=True)
    protocol_valid: bool = Field(strict=True)
    observed_server_identity: str | None = Field(default=None, max_length=256)
    retry_after_ms: int | None = Field(default=None, ge=0, le=86_400_000, strict=True)
    error_code: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._-]{1,127}$")

    @model_validator(mode="after")
    def validate_condition_shape(self) -> Self:
        if self.condition is MCPRemoteCondition.HEALTHY:
            if not self.complete or not self.protocol_valid or not self.connected:
                raise ValueError(
                    "healthy hosted MCP observation must complete a valid protocol response"
                )
            if self.http_status is None or not 200 <= self.http_status < 300:
                raise ValueError("healthy hosted MCP observation requires a 2xx HTTP status")
            if self.observed_server_identity is None:
                raise ValueError("healthy hosted MCP observation requires server identity")
            if self.error_code is not None:
                raise ValueError("healthy hosted MCP observation cannot carry an error code")
        elif self.error_code is None:
            raise ValueError("faulted hosted MCP observation requires a bounded error code")
        if self.condition is MCPRemoteCondition.RATE_LIMIT and self.http_status != 429:
            raise ValueError("rate-limit observation must bind HTTP 429")
        if self.condition is MCPRemoteCondition.TLS_FAILURE and self.tls_verified:
            raise ValueError("TLS-failure observation cannot claim verified TLS")
        if self.condition is MCPRemoteCondition.DNS_FAILURE and self.dns_resolved:
            raise ValueError("DNS-failure observation cannot claim successful resolution")
        return self


class MCPRemoteAssuranceReceipt(BaseModel):
    """Integrity-bound remote transport qualification; never behavioral grading authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-remote-receipt/v1"] = _REMOTE_RECEIPT_SCHEMA
    endpoint: MCPHostedEndpointSpec
    policy: MCPRemotePolicy
    observations: tuple[MCPRemoteProbeObservation, ...] = Field(min_length=1)
    covered_conditions: tuple[MCPRemoteCondition, ...]
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        endpoint: MCPHostedEndpointSpec,
        policy: MCPRemotePolicy,
        observations: tuple[MCPRemoteProbeObservation, ...],
    ) -> Self:
        _require_exact(endpoint, MCPHostedEndpointSpec, "hosted MCP endpoint")
        _require_exact(policy, MCPRemotePolicy, "hosted MCP policy")
        checked_endpoint = MCPHostedEndpointSpec.model_validate_json(endpoint.model_dump_json())
        checked_policy = MCPRemotePolicy.model_validate_json(policy.model_dump_json())
        checked: list[MCPRemoteProbeObservation] = []
        for item in observations:
            _require_exact(item, MCPRemoteProbeObservation, "hosted MCP observation")
            value = MCPRemoteProbeObservation.model_validate_json(item.model_dump_json())
            if value.endpoint_identity != checked_endpoint.identity:
                raise ValueError("hosted MCP observation endpoint identity mismatch")
            checked.append(value)
        covered = tuple(sorted({item.condition for item in checked}, key=lambda item: item.value))
        healthy = [item for item in checked if item.condition is MCPRemoteCondition.HEALTHY]
        accepted = (
            checked_policy.required_conditions <= set(covered)
            and len(healthy) >= 1
            and all(item.latency_ms <= checked_endpoint.max_latency_ms for item in healthy)
            and all(item.response_bytes <= checked_endpoint.max_response_bytes for item in checked)
            and all(item.stream_frames <= checked_endpoint.max_stream_frames for item in checked)
            and all(
                item.observed_server_identity == checked_endpoint.expected_server_identity
                for item in healthy
            )
            and (
                not checked_policy.require_tls_on_healthy
                or all(item.tls_verified for item in healthy)
            )
            and (
                not checked_policy.require_dns_on_healthy
                or all(item.dns_resolved for item in healthy)
            )
        )
        unsigned = {
            "schema_version": _REMOTE_RECEIPT_SCHEMA,
            "endpoint": checked_endpoint.model_dump(mode="json"),
            "policy": checked_policy.model_dump(mode="json"),
            "observations": [item.model_dump(mode="json") for item in checked],
            "covered_conditions": [item.value for item in covered],
            "accepted": accepted,
        }
        return validate_receipt_construction(
            cls,
            endpoint=checked_endpoint,
            policy=checked_policy,
            observations=tuple(checked),
            covered_conditions=covered,
            accepted=accepted,
            receipt_root=_domain_root(_REMOTE_RECEIPT_DOMAIN, unsigned),
        )

    @model_validator(mode="after")
    def verify_receipt(self, info: ValidationInfo) -> Self:
        if is_receipt_construction(info):
            return self
        rebuilt = type(self).create(
            endpoint=self.endpoint,
            policy=self.policy,
            observations=self.observations,
        )
        if (
            self.covered_conditions != rebuilt.covered_conditions
            or self.accepted != rebuilt.accepted
            or not _constant_equal(self.receipt_root, rebuilt.receipt_root)
        ):
            raise ValueError("hosted MCP receipt does not recompute")
        return self


class MCPCapabilitySnapshot(BaseModel):
    """Versioned server capability inventory, including advanced MCP surfaces."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-capability-snapshot/v1"] = _CAPABILITY_SCHEMA
    server_identity: str = Field(min_length=1, max_length=256)
    protocol_version: str = Field(default=_PROTOCOL_VERSION, min_length=1, max_length=64)
    capabilities: frozenset[MCPCapability]
    capability_revision: str = Field(min_length=1, max_length=128)

    @property
    def identity(self) -> str:
        return _domain_root(
            b"agent-evals/mcp-capability-snapshot/v1\0",
            self.model_dump(mode="json"),
        )


class MCPCapabilityOperationObservation(BaseModel):
    """One bounded request/response observation exercising an advanced MCP capability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability: MCPCapability
    operation_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    request_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    response_bytes: int = Field(ge=0, le=64 * 1024 * 1024, strict=True)
    succeeded: bool = Field(strict=True)


class MCPCapabilityExerciseReceipt(BaseModel):
    """Require real bounded observations for every declared advanced MCP capability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-capability-exercise-receipt/v1"] = (
        _CAPABILITY_EXERCISE_SCHEMA
    )
    snapshot: MCPCapabilitySnapshot
    observations: tuple[MCPCapabilityOperationObservation, ...] = Field(
        min_length=1,
        max_length=10_000,
    )
    exercised_capabilities: tuple[MCPCapability, ...]
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        snapshot: MCPCapabilitySnapshot,
        observations: tuple[MCPCapabilityOperationObservation, ...],
    ) -> Self:
        _require_exact(snapshot, MCPCapabilitySnapshot, "MCP capability snapshot")
        checked_snapshot = MCPCapabilitySnapshot.model_validate_json(snapshot.model_dump_json())
        checked: list[MCPCapabilityOperationObservation] = []
        for item in observations:
            _require_exact(
                item,
                MCPCapabilityOperationObservation,
                "MCP capability operation observation",
            )
            checked.append(
                MCPCapabilityOperationObservation.model_validate_json(item.model_dump_json())
            )
        ids = [item.operation_id for item in checked]
        if len(set(ids)) != len(ids):
            raise ValueError("MCP capability operation IDs must be unique")
        observed = {item.capability for item in checked}
        if not observed <= checked_snapshot.capabilities:
            raise ValueError("MCP exercise observes capability absent from bound snapshot")
        exercised = tuple(
            sorted(
                {
                    item.capability
                    for item in checked
                    if item.succeeded
                },
                key=lambda item: item.value,
            )
        )
        accepted = checked_snapshot.capabilities <= set(exercised)
        material = {
            "schema_version": _CAPABILITY_EXERCISE_SCHEMA,
            "snapshot": checked_snapshot.model_dump(mode="json"),
            "observations": [item.model_dump(mode="json") for item in checked],
            "exercised_capabilities": [item.value for item in exercised],
            "accepted": accepted,
        }
        return validate_receipt_construction(
            cls,
            snapshot=checked_snapshot,
            observations=tuple(checked),
            exercised_capabilities=exercised,
            accepted=accepted,
            receipt_root=_domain_root(_CAPABILITY_EXERCISE_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_receipt(self, info: ValidationInfo) -> Self:
        if is_receipt_construction(info):
            return self
        rebuilt = type(self).create(snapshot=self.snapshot, observations=self.observations)
        if (
            self.exercised_capabilities != rebuilt.exercised_capabilities
            or self.accepted != rebuilt.accepted
            or not _constant_equal(self.receipt_root, rebuilt.receipt_root)
        ):
            raise ValueError("MCP capability exercise receipt does not recompute")
        return self


class MCPToolsListChangedReceipt(BaseModel):
    """Bind one tools/list_changed notification to an actual discovery delta."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-list-changed-receipt/v1"] = _LIST_CHANGED_SCHEMA
    server_identity: str = Field(min_length=1, max_length=256)
    protocol_version: str = Field(min_length=1, max_length=64)
    before_tools: tuple[str, ...]
    after_tools: tuple[str, ...]
    notification_sequence: int = Field(ge=0, strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        server_identity: str,
        before_tools: tuple[str, ...],
        after_tools: tuple[str, ...],
        notification_sequence: int,
        protocol_version: str = _PROTOCOL_VERSION,
    ) -> Self:
        before = _canonical_names(before_tools, "before tools")
        after = _canonical_names(after_tools, "after tools")
        if before == after:
            raise ValueError("tools/list_changed receipt requires an actual discovery delta")
        material = {
            "schema_version": _LIST_CHANGED_SCHEMA,
            "server_identity": server_identity,
            "protocol_version": protocol_version,
            "before_tools": list(before),
            "after_tools": list(after),
            "notification_sequence": notification_sequence,
        }
        return cls(
            server_identity=server_identity,
            protocol_version=protocol_version,
            before_tools=before,
            after_tools=after,
            notification_sequence=notification_sequence,
            receipt_root=_domain_root(_LIST_CHANGED_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_root(self) -> Self:
        material = self.model_dump(mode="json", exclude={"receipt_root"})
        if not _constant_equal(self.receipt_root, _domain_root(_LIST_CHANGED_DOMAIN, material)):
            raise ValueError("tools/list_changed receipt root mismatch")
        if self.before_tools == self.after_tools:
            raise ValueError("tools/list_changed receipt requires discovery delta")
        return self


class MCPConcurrentOperation(BaseModel):
    """One bounded concurrent MCP operation on a logical monotonic tick timeline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1, max_length=256)
    server_identity: str = Field(min_length=1, max_length=256)
    target_identity: str = Field(min_length=1, max_length=256)
    started_tick: int = Field(ge=0, strict=True)
    completed_tick: int = Field(ge=0, strict=True)
    outcome_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.completed_tick < self.started_tick:
            raise ValueError("MCP concurrent operation cannot complete before it starts")
        return self


class MCPConcurrencyReceipt(BaseModel):
    """Arbitrary parallel-call evidence with recomputed peak concurrency."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-concurrency-receipt/v1"] = _CONCURRENCY_SCHEMA
    operations: tuple[MCPConcurrentOperation, ...] = Field(min_length=2, max_length=10_000)
    peak_parallelism: int = Field(ge=1, le=10_000, strict=True)
    minimum_parallelism: int = Field(ge=2, le=10_000, strict=True)
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        operations: tuple[MCPConcurrentOperation, ...],
        minimum_parallelism: int = 2,
    ) -> Self:
        if isinstance(minimum_parallelism, bool) or not 2 <= minimum_parallelism <= 10_000:
            raise ValueError("minimum MCP parallelism must be an integer between 2 and 10000")
        checked: list[MCPConcurrentOperation] = []
        for item in operations:
            _require_exact(item, MCPConcurrentOperation, "MCP concurrent operation")
            checked.append(MCPConcurrentOperation.model_validate_json(item.model_dump_json()))
        request_ids = [item.request_id for item in checked]
        if len(set(request_ids)) != len(request_ids):
            raise ValueError("parallel MCP request IDs must be unique")
        peak = _peak_parallelism(tuple(checked))
        accepted = peak >= minimum_parallelism
        material = {
            "schema_version": _CONCURRENCY_SCHEMA,
            "operations": [item.model_dump(mode="json") for item in checked],
            "peak_parallelism": peak,
            "minimum_parallelism": minimum_parallelism,
            "accepted": accepted,
        }
        return validate_receipt_construction(
            cls,
            operations=tuple(checked),
            peak_parallelism=peak,
            minimum_parallelism=minimum_parallelism,
            accepted=accepted,
            receipt_root=_domain_root(_CONCURRENCY_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_receipt(self, info: ValidationInfo) -> Self:
        if is_receipt_construction(info):
            return self
        rebuilt = type(self).create(
            operations=self.operations,
            minimum_parallelism=self.minimum_parallelism,
        )
        if (
            self.peak_parallelism != rebuilt.peak_parallelism
            or self.accepted != rebuilt.accepted
            or not _constant_equal(self.receipt_root, rebuilt.receipt_root)
        ):
            raise ValueError("MCP concurrency receipt does not recompute")
        return self


class MCPServerSurface(BaseModel):
    """Names exposed by one MCP server before host-side prefixing or routing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    server_identity: str = Field(min_length=1, max_length=256)
    tool_names: tuple[str, ...] = ()

    @field_validator("tool_names")
    @classmethod
    def validate_tools(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_names(value, "MCP server tool names")


class MCPMultiServerReceipt(BaseModel):
    """Detect cross-server tool identity collisions instead of silently aliasing them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-multi-server-receipt/v1"] = _MULTI_SERVER_SCHEMA
    servers: tuple[MCPServerSurface, ...] = Field(min_length=2, max_length=256)
    collision_names: tuple[str, ...]
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, servers: tuple[MCPServerSurface, ...]) -> Self:
        checked: list[MCPServerSurface] = []
        for item in servers:
            _require_exact(item, MCPServerSurface, "MCP server surface")
            checked.append(MCPServerSurface.model_validate_json(item.model_dump_json()))
        identities = [item.server_identity for item in checked]
        if len(set(identities)) != len(identities):
            raise ValueError("MCP multi-server identities must be unique")
        owners: dict[str, set[str]] = {}
        for server in checked:
            for name in server.tool_names:
                owners.setdefault(name, set()).add(server.server_identity)
        collisions = tuple(sorted(name for name, owner_set in owners.items() if len(owner_set) > 1))
        accepted = not collisions
        material = {
            "schema_version": _MULTI_SERVER_SCHEMA,
            "servers": [item.model_dump(mode="json") for item in checked],
            "collision_names": list(collisions),
            "accepted": accepted,
        }
        return validate_receipt_construction(
            cls,
            servers=tuple(checked),
            collision_names=collisions,
            accepted=accepted,
            receipt_root=_domain_root(_MULTI_SERVER_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_receipt(self, info: ValidationInfo) -> Self:
        if is_receipt_construction(info):
            return self
        rebuilt = type(self).create(self.servers)
        if (
            self.collision_names != rebuilt.collision_names
            or self.accepted != rebuilt.accepted
            or not _constant_equal(self.receipt_root, rebuilt.receipt_root)
        ):
            raise ValueError("MCP multi-server receipt does not recompute")
        return self


class MCPHostileServerBudget(BaseModel):
    """Hard ceilings for hostile-server response and execution resource use."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_response_bytes: int = Field(default=2 * 1024 * 1024, ge=1, le=64 * 1024 * 1024, strict=True)
    max_duration_ms: int = Field(default=5_000, ge=1, le=120_000, strict=True)
    max_protocol_messages: int = Field(default=1_000, ge=1, le=100_000, strict=True)


class MCPHostileServerObservation(BaseModel):
    """Outcome for one hostile-server class under a declared resource budget."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    condition: MCPRemoteCondition
    response_bytes: int = Field(ge=0, le=64 * 1024 * 1024 + 1, strict=True)
    duration_ms: int = Field(ge=0, le=120_001, strict=True)
    protocol_messages: int = Field(ge=0, le=100_001, strict=True)
    terminated_by_evaluator: bool = Field(strict=True)
    escaped_budget: bool = Field(strict=True)

    @model_validator(mode="after")
    def require_hostile_class(self) -> Self:
        if self.condition not in {
            MCPRemoteCondition.OVERSIZED_RESPONSE,
            MCPRemoteCondition.HANG_TIMEOUT,
            MCPRemoteCondition.PROTOCOL_TRICKERY,
            MCPRemoteCondition.RESOURCE_PRESSURE,
        }:
            raise ValueError("hostile-server observation uses unsupported condition")
        return self


class MCPHostileServerReceipt(BaseModel):
    """Prove hostile classes were bounded; not that an arbitrary server is safe."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/mcp-hostile-server-receipt/v1"] = _HOSTILE_SCHEMA
    budget: MCPHostileServerBudget
    observations: tuple[MCPHostileServerObservation, ...] = Field(min_length=1)
    covered_conditions: tuple[MCPRemoteCondition, ...]
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        budget: MCPHostileServerBudget,
        observations: tuple[MCPHostileServerObservation, ...],
    ) -> Self:
        _require_exact(budget, MCPHostileServerBudget, "MCP hostile-server budget")
        checked_budget = MCPHostileServerBudget.model_validate_json(budget.model_dump_json())
        checked: list[MCPHostileServerObservation] = []
        for item in observations:
            _require_exact(item, MCPHostileServerObservation, "MCP hostile-server observation")
            checked.append(MCPHostileServerObservation.model_validate_json(item.model_dump_json()))
        covered = tuple(sorted({item.condition for item in checked}, key=lambda item: item.value))
        accepted = all(
            item.terminated_by_evaluator
            and not item.escaped_budget
            and (
                item.response_bytes <= checked_budget.max_response_bytes
                or item.condition is MCPRemoteCondition.OVERSIZED_RESPONSE
            )
            and (
                item.duration_ms <= checked_budget.max_duration_ms
                or item.condition is MCPRemoteCondition.HANG_TIMEOUT
            )
            and (
                item.protocol_messages <= checked_budget.max_protocol_messages
                or item.condition
                in {
                    MCPRemoteCondition.PROTOCOL_TRICKERY,
                    MCPRemoteCondition.RESOURCE_PRESSURE,
                }
            )
            for item in checked
        )
        material = {
            "schema_version": _HOSTILE_SCHEMA,
            "budget": checked_budget.model_dump(mode="json"),
            "observations": [item.model_dump(mode="json") for item in checked],
            "covered_conditions": [item.value for item in covered],
            "accepted": accepted,
        }
        return validate_receipt_construction(
            cls,
            budget=checked_budget,
            observations=tuple(checked),
            covered_conditions=covered,
            accepted=accepted,
            receipt_root=_domain_root(_HOSTILE_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_receipt(self, info: ValidationInfo) -> Self:
        if is_receipt_construction(info):
            return self
        rebuilt = type(self).create(budget=self.budget, observations=self.observations)
        if (
            self.covered_conditions != rebuilt.covered_conditions
            or self.accepted != rebuilt.accepted
            or not _constant_equal(self.receipt_root, rebuilt.receipt_root)
        ):
            raise ValueError("MCP hostile-server receipt does not recompute")
        return self


def probe_hosted_mcp_endpoint(endpoint: MCPHostedEndpointSpec) -> MCPRemoteProbeObservation:
    """Probe a real HTTPS MCP endpoint with a bounded initialize request.

    This is an operator-invoked network probe. It intentionally does not run in ordinary offline
    PR CI. Network/provider uncertainty is returned as protocol evidence, never as subject FAIL.
    """

    _require_exact(endpoint, MCPHostedEndpointSpec, "hosted MCP endpoint")
    checked = MCPHostedEndpointSpec.model_validate_json(endpoint.model_dump_json())
    payload = _canonical_json_bytes(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": checked.protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "agent-evals", "version": "1"},
            },
        }
    )
    request = urllib.request.Request(
        checked.url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    handlers: list[urllib.request.BaseHandler] = []
    if checked.proxy_url is not None:
        handlers.append(urllib.request.ProxyHandler({"https": checked.proxy_url}))
    opener = urllib.request.build_opener(*handlers)
    start = time.monotonic_ns()
    try:
        with opener.open(request, timeout=checked.timeout_ms / 1000) as response:  # nosec B310
            raw = response.read(checked.max_response_bytes + 1)
            elapsed = _elapsed_ms(start)
            if len(raw) > checked.max_response_bytes:
                return _remote_fault(
                    checked,
                    MCPRemoteCondition.OVERSIZED_RESPONSE,
                    latency_ms=elapsed,
                    dns_resolved=True,
                    tls_verified=True,
                    connected=True,
                    http_status=response.status,
                    response_bytes=len(raw),
                    error_code="response-too-large",
                )
            frames = _stream_frame_count(raw)
            if frames > checked.max_stream_frames:
                return _remote_fault(
                    checked,
                    MCPRemoteCondition.RESOURCE_PRESSURE,
                    latency_ms=elapsed,
                    dns_resolved=True,
                    tls_verified=True,
                    connected=True,
                    http_status=response.status,
                    response_bytes=len(raw),
                    stream_frames=frames,
                    error_code="stream-frame-limit",
                )
            if elapsed > checked.max_latency_ms:
                return _remote_fault(
                    checked,
                    MCPRemoteCondition.LATENCY_LIMIT,
                    latency_ms=elapsed,
                    dns_resolved=True,
                    tls_verified=True,
                    connected=True,
                    http_status=response.status,
                    response_bytes=len(raw),
                    stream_frames=frames,
                    error_code="latency-limit",
                )
            try:
                parsed = json.loads(raw)
                result = parsed.get("result") if isinstance(parsed, dict) else None
                server_info = result.get("serverInfo") if isinstance(result, dict) else None
                server_name = server_info.get("name") if isinstance(server_info, dict) else None
                response_id = parsed.get("id") if isinstance(parsed, dict) else None
            except (UnicodeDecodeError, json.JSONDecodeError):
                return _remote_fault(
                    checked,
                    MCPRemoteCondition.PROTOCOL_TRICKERY,
                    latency_ms=elapsed,
                    dns_resolved=True,
                    tls_verified=True,
                    connected=True,
                    http_status=response.status,
                    response_bytes=len(raw),
                    stream_frames=frames,
                    error_code="invalid-json",
                )
            if response_id != 1 or not isinstance(server_name, str) or not server_name:
                return _remote_fault(
                    checked,
                    MCPRemoteCondition.PROTOCOL_TRICKERY,
                    latency_ms=elapsed,
                    dns_resolved=True,
                    tls_verified=True,
                    connected=True,
                    http_status=response.status,
                    response_bytes=len(raw),
                    stream_frames=frames,
                    error_code="invalid-initialize-response",
                )
            return MCPRemoteProbeObservation(
                endpoint_identity=checked.identity,
                condition=MCPRemoteCondition.HEALTHY,
                dns_resolved=True,
                tls_verified=True,
                connected=True,
                latency_ms=elapsed,
                http_status=response.status,
                response_bytes=len(raw),
                stream_frames=frames,
                complete=True,
                protocol_valid=True,
                observed_server_identity=server_name,
            )
    except urllib.error.HTTPError as exc:
        elapsed = _elapsed_ms(start)
        if exc.code == 429:
            return _remote_fault(
                checked,
                MCPRemoteCondition.RATE_LIMIT,
                latency_ms=elapsed,
                dns_resolved=True,
                tls_verified=True,
                connected=True,
                http_status=429,
                retry_after_ms=_parse_retry_after_ms(exc.headers.get("Retry-After")),
                error_code="rate-limited",
            )
        condition = (
            MCPRemoteCondition.GATEWAY_FAILURE
            if exc.code in {502, 503, 504}
            else MCPRemoteCondition.PROTOCOL_TRICKERY
        )
        return _remote_fault(
            checked,
            condition,
            latency_ms=elapsed,
            dns_resolved=True,
            tls_verified=True,
            connected=True,
            http_status=exc.code,
            error_code=f"http-{exc.code}",
        )
    except urllib.error.URLError as exc:
        elapsed = _elapsed_ms(start)
        reason = exc.reason
        if isinstance(reason, ssl.SSLError):
            condition = MCPRemoteCondition.TLS_FAILURE
            code = "tls-failure"
            dns = True
        elif isinstance(reason, socket.gaierror):
            condition = MCPRemoteCondition.DNS_FAILURE
            code = "dns-failure"
            dns = False
        elif isinstance(reason, TimeoutError):
            condition = MCPRemoteCondition.HANG_TIMEOUT
            code = "timeout"
            dns = True
        else:
            condition = (
                MCPRemoteCondition.PROXY_FAILURE
                if checked.proxy_url is not None
                else MCPRemoteCondition.DISCONNECT
            )
            code = "proxy-failure" if checked.proxy_url is not None else "connection-failure"
            dns = True
        return _remote_fault(
            checked,
            condition,
            latency_ms=elapsed,
            dns_resolved=dns,
            tls_verified=False,
            connected=False,
            error_code=code,
        )
    except (http.client.IncompleteRead, http.client.RemoteDisconnected):
        return _remote_fault(
            checked,
            MCPRemoteCondition.STREAM_INTERRUPTION,
            latency_ms=_elapsed_ms(start),
            dns_resolved=True,
            tls_verified=True,
            connected=True,
            error_code="stream-interrupted",
        )
    except (ConnectionResetError, BrokenPipeError):
        return _remote_fault(
            checked,
            MCPRemoteCondition.DISCONNECT,
            latency_ms=_elapsed_ms(start),
            dns_resolved=True,
            tls_verified=True,
            connected=False,
            error_code="connection-reset",
        )
    except TimeoutError:
        return _remote_fault(
            checked,
            MCPRemoteCondition.HANG_TIMEOUT,
            latency_ms=_elapsed_ms(start),
            dns_resolved=True,
            tls_verified=True,
            connected=True,
            error_code="timeout",
        )


def _remote_fault(
    endpoint: MCPHostedEndpointSpec,
    condition: MCPRemoteCondition,
    *,
    latency_ms: int,
    dns_resolved: bool,
    tls_verified: bool,
    connected: bool,
    http_status: int | None = None,
    response_bytes: int = 0,
    stream_frames: int = 0,
    retry_after_ms: int | None = None,
    error_code: str,
) -> MCPRemoteProbeObservation:
    return MCPRemoteProbeObservation(
        endpoint_identity=endpoint.identity,
        condition=condition,
        dns_resolved=dns_resolved,
        tls_verified=tls_verified,
        connected=connected,
        latency_ms=min(latency_ms, 120_000),
        http_status=http_status,
        response_bytes=response_bytes,
        stream_frames=stream_frames,
        complete=False,
        protocol_valid=False,
        retry_after_ms=retry_after_ms,
        error_code=error_code,
    )


def _peak_parallelism(operations: tuple[MCPConcurrentOperation, ...]) -> int:
    ticks = sorted(
        {item.started_tick for item in operations} | {item.completed_tick for item in operations}
    )
    return max(
        sum(item.started_tick <= tick <= item.completed_tick for item in operations)
        for tick in ticks
    )


def _canonical_names(value: tuple[str, ...], label: str) -> tuple[str, ...]:
    if any(not name.strip() or name != name.strip() for name in value):
        raise ValueError(f"{label} must contain trimmed non-empty names")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")
    return tuple(sorted(value))


def _elapsed_ms(start_ns: int) -> int:
    return min((time.monotonic_ns() - start_ns) // 1_000_000, 120_000)


def _stream_frame_count(raw: bytes) -> int:
    if not raw:
        return 0
    return max(1, raw.count(b"\n\n"))


def _parse_retry_after_ms(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        seconds = int(value)
    except ValueError:
        return None
    if seconds < 0:
        return None
    return min(seconds * 1000, 86_400_000)


def _require_exact(value: object, expected: type[object], label: str) -> None:
    if type(value) is not expected:
        raise ValueError(f"{label} requires exact {expected.__name__}")


def _domain_root(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + _canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "MCP advanced assurance material must be finite JSON-compatible data"
        ) from exc


def _constant_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)


__all__ = [
    "MCPCapability",
    "MCPCapabilityExerciseReceipt",
    "MCPCapabilityOperationObservation",
    "MCPCapabilitySnapshot",
    "MCPConcurrencyReceipt",
    "MCPConcurrentOperation",
    "MCPHostedEndpointSpec",
    "MCPHostileServerBudget",
    "MCPHostileServerObservation",
    "MCPHostileServerReceipt",
    "MCPMultiServerReceipt",
    "MCPRemoteAssuranceReceipt",
    "MCPRemoteCondition",
    "MCPRemotePolicy",
    "MCPRemoteProbeObservation",
    "MCPServerSurface",
    "MCPToolsListChangedReceipt",
    "probe_hosted_mcp_endpoint",
]
