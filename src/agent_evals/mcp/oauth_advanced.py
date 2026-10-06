"""Advanced OAuth/JWT, sender-constraining, replay, and authorization-drift assurance.

These models record externally verified protocol facts. They do not implement an identity provider,
mint tokens, or treat a receipt hash as authentication.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_KEYSET_SCHEMA: Literal["agent-evals/oauth-keyset-snapshot/v1"] = (
    "agent-evals/oauth-keyset-snapshot/v1"
)
_EVENT_SCHEMA: Literal["agent-evals/oauth-session-event/v1"] = "agent-evals/oauth-session-event/v1"
_POLICY_SCHEMA: Literal["agent-evals/oauth-advanced-policy/v1"] = "agent-evals/oauth-advanced-policy/v1"
_RECEIPT_SCHEMA: Literal["agent-evals/oauth-advanced-receipt/v1"] = (
    "agent-evals/oauth-advanced-receipt/v1"
)
_DRIFT_SCHEMA: Literal["agent-evals/oauth-authorization-drift-receipt/v1"] = (
    "agent-evals/oauth-authorization-drift-receipt/v1"
)
_RECEIPT_DOMAIN = b"agent-evals/oauth-advanced-receipt/v1\0"
_DRIFT_DOMAIN = b"agent-evals/oauth-authorization-drift-receipt/v1\0"


class OAuthSenderBinding(StrEnum):
    BEARER = "bearer"
    DPOP = "dpop"
    MTLS = "mtls"


class OAuthSessionEventKind(StrEnum):
    INITIAL = "initial"
    REFRESH = "refresh"
    REVOKE = "revoke"
    REQUEST = "request"
    REPLAY = "replay"


class OAuthKeySetSnapshot(BaseModel):
    """Observed JWKS state at one evaluator-owned logical epoch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/oauth-keyset-snapshot/v1"] = _KEYSET_SCHEMA
    issuer: str = Field(min_length=1, max_length=1024)
    jwks_uri: str = Field(min_length=1, max_length=2048)
    key_ids: tuple[str, ...] = Field(min_length=1, max_length=256)
    epoch: int = Field(ge=0, strict=True)
    verifier_revision: str = Field(min_length=1, max_length=128)

    @field_validator("key_ids")
    @classmethod
    def canonical_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() or item != item.strip() for item in value):
            raise ValueError("OAuth key IDs must be trimmed non-empty strings")
        if len(set(value)) != len(value):
            raise ValueError("OAuth key IDs must be unique")
        return tuple(sorted(value))

    @property
    def identity(self) -> str:
        return _domain_root(b"agent-evals/oauth-keyset-snapshot/v1\0", self.model_dump(mode="json"))


class OAuthSessionEvent(BaseModel):
    """One externally verified token/session event without retaining bearer material."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/oauth-session-event/v1"] = _EVENT_SCHEMA
    event_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    kind: OAuthSessionEventKind
    epoch: int = Field(ge=0, strict=True)
    issuer: str = Field(min_length=1, max_length=1024)
    subject: str = Field(min_length=1, max_length=512)
    audience: str = Field(min_length=1, max_length=1024)
    token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    jti_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signing_kid: str = Field(min_length=1, max_length=256)
    scopes: frozenset[str]
    sender_binding: OAuthSenderBinding
    sender_key_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    jwt_signature_verified: bool = Field(strict=True)
    accepted_by_resource: bool = Field(strict=True)
    parent_token_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not scope.strip() or scope != scope.strip() for scope in value):
            raise ValueError("OAuth scopes must be trimmed non-empty strings")
        return value

    @model_validator(mode="after")
    def validate_binding_and_kind(self) -> Self:
        if self.sender_binding is OAuthSenderBinding.BEARER:
            if self.sender_key_sha256 is not None:
                raise ValueError("bearer token event cannot carry sender-key binding")
        elif self.sender_key_sha256 is None:
            raise ValueError("DPoP/mTLS event requires sender-key fingerprint")
        if self.kind is OAuthSessionEventKind.REFRESH and self.parent_token_sha256 is None:
            raise ValueError("refresh event requires parent token identity")
        if self.kind is OAuthSessionEventKind.INITIAL and self.parent_token_sha256 is not None:
            raise ValueError("initial token event cannot carry parent token identity")
        if self.kind is OAuthSessionEventKind.REVOKE and self.accepted_by_resource:
            raise ValueError("revocation event cannot be accepted as a resource request")
        if self.kind in {OAuthSessionEventKind.REPLAY, OAuthSessionEventKind.REVOKE}:
            if self.accepted_by_resource:
                raise ValueError("replay/revocation event must not be accepted by resource server")
        return self


class OAuthAdvancedPolicy(BaseModel):
    """Qualification policy for key rotation, refresh, revocation, replay and sender binding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/oauth-advanced-policy/v1"] = _POLICY_SCHEMA
    allowed_issuers: frozenset[str] = Field(min_length=1)
    require_key_rotation: bool = Field(default=True, strict=True)
    require_refresh: bool = Field(default=True, strict=True)
    require_revocation_rejection: bool = Field(default=True, strict=True)
    require_replay_rejection: bool = Field(default=True, strict=True)
    require_sender_constraint: bool = Field(default=True, strict=True)
    allowed_sender_bindings: frozenset[OAuthSenderBinding] = frozenset(
        {OAuthSenderBinding.DPOP, OAuthSenderBinding.MTLS}
    )

    @field_validator("allowed_issuers")
    @classmethod
    def validate_issuers(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not item.strip() or item != item.strip() for item in value):
            raise ValueError("OAuth allowed issuers must be trimmed non-empty strings")
        return value

    @model_validator(mode="after")
    def validate_binding_policy(self) -> Self:
        if self.require_sender_constraint and not self.allowed_sender_bindings:
            raise ValueError("sender-constrained OAuth policy requires at least one binding mode")
        return self


class OAuthAdvancedReceipt(BaseModel):
    """Integrity-bound OAuth qualification result over exact keyset and session observations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/oauth-advanced-receipt/v1"] = _RECEIPT_SCHEMA
    policy: OAuthAdvancedPolicy
    keysets: tuple[OAuthKeySetSnapshot, ...] = Field(min_length=1)
    events: tuple[OAuthSessionEvent, ...] = Field(min_length=1)
    key_rotation_observed: bool = Field(strict=True)
    refresh_observed: bool = Field(strict=True)
    revocation_rejected: bool = Field(strict=True)
    replay_rejected: bool = Field(strict=True)
    sender_constraint_observed: bool = Field(strict=True)
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(
        cls,
        *,
        policy: OAuthAdvancedPolicy,
        keysets: tuple[OAuthKeySetSnapshot, ...],
        events: tuple[OAuthSessionEvent, ...],
    ) -> Self:
        _require_exact(policy, OAuthAdvancedPolicy, "advanced OAuth policy")
        checked_policy = OAuthAdvancedPolicy.model_validate_json(policy.model_dump_json())
        checked_keysets = _check_keysets(keysets)
        checked_events = _check_events(events)

        issuers = {item.issuer for item in checked_keysets} | {item.issuer for item in checked_events}
        if not issuers <= checked_policy.allowed_issuers:
            raise ValueError("OAuth observations contain issuer outside policy")
        known_kids = {item for snapshot in checked_keysets for item in snapshot.key_ids}
        if any(event.signing_kid not in known_kids for event in checked_events):
            raise ValueError("OAuth event signing kid is absent from observed JWKS snapshots")
        if any(not event.jwt_signature_verified for event in checked_events):
            raise ValueError("OAuth event lacks external JWT signature verification")

        key_rotation = len({snapshot.key_ids for snapshot in checked_keysets}) > 1
        refresh = any(event.kind is OAuthSessionEventKind.REFRESH for event in checked_events)
        revocation = any(
            event.kind is OAuthSessionEventKind.REVOKE and not event.accepted_by_resource
            for event in checked_events
        )
        replay = any(
            event.kind is OAuthSessionEventKind.REPLAY and not event.accepted_by_resource
            for event in checked_events
        )
        sender_constraint = any(
            event.sender_binding in checked_policy.allowed_sender_bindings
            and event.sender_key_sha256 is not None
            for event in checked_events
            if event.kind in {OAuthSessionEventKind.INITIAL, OAuthSessionEventKind.REFRESH}
        )
        accepted = (
            (key_rotation or not checked_policy.require_key_rotation)
            and (refresh or not checked_policy.require_refresh)
            and (revocation or not checked_policy.require_revocation_rejection)
            and (replay or not checked_policy.require_replay_rejection)
            and (sender_constraint or not checked_policy.require_sender_constraint)
        )
        material = {
            "schema_version": _RECEIPT_SCHEMA,
            "policy": checked_policy.model_dump(mode="json"),
            "keysets": [item.model_dump(mode="json") for item in checked_keysets],
            "events": [item.model_dump(mode="json") for item in checked_events],
            "key_rotation_observed": key_rotation,
            "refresh_observed": refresh,
            "revocation_rejected": revocation,
            "replay_rejected": replay,
            "sender_constraint_observed": sender_constraint,
            "accepted": accepted,
        }
        return cls(
            policy=checked_policy,
            keysets=checked_keysets,
            events=checked_events,
            key_rotation_observed=key_rotation,
            refresh_observed=refresh,
            revocation_rejected=revocation,
            replay_rejected=replay,
            sender_constraint_observed=sender_constraint,
            accepted=accepted,
            receipt_root=_domain_root(_RECEIPT_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_receipt(self) -> Self:
        rebuilt = type(self).create(policy=self.policy, keysets=self.keysets, events=self.events)
        fields = (
            "key_rotation_observed",
            "refresh_observed",
            "revocation_rejected",
            "replay_rejected",
            "sender_constraint_observed",
            "accepted",
        )
        if any(getattr(self, field) != getattr(rebuilt, field) for field in fields):
            raise ValueError("advanced OAuth receipt metrics do not recompute")
        if not hmac.compare_digest(self.receipt_root, rebuilt.receipt_root):
            raise ValueError("advanced OAuth receipt root mismatch")
        return self


class OAuthAuthorizationEpoch(BaseModel):
    """Authorization state observed during one active session epoch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    epoch: int = Field(ge=0, strict=True)
    scopes: frozenset[str]
    resource_identity: str = Field(min_length=1, max_length=1024)
    operation: str = Field(min_length=1, max_length=256)
    allowed: bool = Field(strict=True)

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not scope.strip() or scope != scope.strip() for scope in value):
            raise ValueError("authorization-drift scopes must be trimmed")
        return value


class OAuthAuthorizationDriftReceipt(BaseModel):
    """Prove active-session authorization contraction is honored after the drift point."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/oauth-authorization-drift-receipt/v1"] = _DRIFT_SCHEMA
    observations: tuple[OAuthAuthorizationEpoch, ...] = Field(min_length=2)
    contraction_observed: bool = Field(strict=True)
    post_contraction_denial_observed: bool = Field(strict=True)
    accepted: bool = Field(strict=True)
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def create(cls, observations: tuple[OAuthAuthorizationEpoch, ...]) -> Self:
        checked: list[OAuthAuthorizationEpoch] = []
        for item in observations:
            _require_exact(item, OAuthAuthorizationEpoch, "authorization-drift observation")
            checked.append(OAuthAuthorizationEpoch.model_validate_json(item.model_dump_json()))
        epochs = [item.epoch for item in checked]
        if epochs != sorted(epochs) or len(set(epochs)) != len(epochs):
            raise ValueError("authorization-drift epochs must be unique and increasing")

        contraction = False
        denial = False
        previous = checked[0]
        for current in checked[1:]:
            if current.scopes < previous.scopes:
                contraction = True
                removed = previous.scopes - current.scopes
                if removed and not current.allowed:
                    denial = True
            previous = current
        accepted = contraction and denial
        material = {
            "schema_version": _DRIFT_SCHEMA,
            "observations": [item.model_dump(mode="json") for item in checked],
            "contraction_observed": contraction,
            "post_contraction_denial_observed": denial,
            "accepted": accepted,
        }
        return cls(
            observations=tuple(checked),
            contraction_observed=contraction,
            post_contraction_denial_observed=denial,
            accepted=accepted,
            receipt_root=_domain_root(_DRIFT_DOMAIN, material),
        )

    @model_validator(mode="after")
    def verify_receipt(self) -> Self:
        rebuilt = type(self).create(self.observations)
        if (
            self.contraction_observed != rebuilt.contraction_observed
            or self.post_contraction_denial_observed != rebuilt.post_contraction_denial_observed
            or self.accepted != rebuilt.accepted
            or not hmac.compare_digest(self.receipt_root, rebuilt.receipt_root)
        ):
            raise ValueError("authorization-drift receipt does not recompute")
        return self


def _check_keysets(values: tuple[OAuthKeySetSnapshot, ...]) -> tuple[OAuthKeySetSnapshot, ...]:
    checked: list[OAuthKeySetSnapshot] = []
    for item in values:
        _require_exact(item, OAuthKeySetSnapshot, "OAuth keyset snapshot")
        checked.append(OAuthKeySetSnapshot.model_validate_json(item.model_dump_json()))
    if not checked:
        raise ValueError("advanced OAuth qualification requires keyset snapshots")
    epochs = [item.epoch for item in checked]
    if epochs != sorted(epochs) or len(set(epochs)) != len(epochs):
        raise ValueError("OAuth keyset epochs must be unique and increasing")
    return tuple(checked)


def _check_events(values: tuple[OAuthSessionEvent, ...]) -> tuple[OAuthSessionEvent, ...]:
    checked: list[OAuthSessionEvent] = []
    for item in values:
        _require_exact(item, OAuthSessionEvent, "OAuth session event")
        checked.append(OAuthSessionEvent.model_validate_json(item.model_dump_json()))
    if not checked:
        raise ValueError("advanced OAuth qualification requires session events")
    event_ids = [item.event_id for item in checked]
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("OAuth event IDs must be unique")
    epochs = [item.epoch for item in checked]
    if epochs != sorted(epochs):
        raise ValueError("OAuth session events must be ordered by epoch")
    seen_tokens: set[str] = set()
    revoked_tokens: set[str] = set()
    for item in checked:
        if item.kind in {OAuthSessionEventKind.INITIAL, OAuthSessionEventKind.REFRESH}:
            seen_tokens.add(item.token_sha256)
            if item.kind is OAuthSessionEventKind.REFRESH:
                parent = item.parent_token_sha256
                if parent is None or parent not in seen_tokens:
                    raise ValueError("OAuth refresh parent must reference a previously observed token")
        elif item.kind is OAuthSessionEventKind.REVOKE:
            if item.token_sha256 not in seen_tokens:
                raise ValueError("OAuth revocation must reference a previously observed token")
            revoked_tokens.add(item.token_sha256)
        elif item.kind is OAuthSessionEventKind.REPLAY:
            if item.token_sha256 not in seen_tokens:
                raise ValueError("OAuth replay must reference a previously observed token")
        elif item.kind is OAuthSessionEventKind.REQUEST:
            if item.token_sha256 in revoked_tokens and item.accepted_by_resource:
                raise ValueError("revoked OAuth token cannot be accepted after revocation")
    return tuple(checked)


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
        raise ValueError("OAuth assurance material must be finite JSON-compatible data") from exc


__all__ = [
    "OAuthAdvancedPolicy",
    "OAuthAdvancedReceipt",
    "OAuthAuthorizationDriftReceipt",
    "OAuthAuthorizationEpoch",
    "OAuthKeySetSnapshot",
    "OAuthSenderBinding",
    "OAuthSessionEvent",
    "OAuthSessionEventKind",
]
