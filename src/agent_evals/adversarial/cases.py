"""Provider-neutral adversarial fixtures that derive exact, fail-closed security scenarios."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.security.taxonomy import ThreatClass

_ATTACK_SCHEMA: Literal["agent-evals/adversarial-attack/v1"] = "agent-evals/adversarial-attack/v1"
_CAMPAIGN_SCHEMA: Literal["agent-evals/adversarial-campaign/v1"] = (
    "agent-evals/adversarial-campaign/v1"
)
_ATTACK_ENVELOPE_SCHEMA: Literal["agent-evals/adversarial-envelope/v1"] = (
    "agent-evals/adversarial-envelope/v1"
)
_RESERVED_STATE_KEY = "__agent_evals_adversarial__"


class AttackChannel(StrEnum):
    """Where an evaluation environment must inject one adversarial fixture."""

    USER_INPUT = "user_input"
    TOOL_RESULT = "tool_result"
    TOOL_METADATA = "tool_metadata"
    MEMORY = "memory"
    RESOURCE = "resource"
    HANDOFF = "handoff"
    ENVIRONMENT = "environment"


class AttackFixture(BaseModel):
    """Content-addressed adversarial stimulus independent of any model provider.

    `payload_json` is canonical JSON rather than a mutable dictionary. Use `from_payload()` for
    ergonomic construction and the `payload` property when an adapter needs a fresh decoded value.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/adversarial-attack/v1"] = _ATTACK_SCHEMA
    attack_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,63}$")
    revision: str = Field(min_length=1, max_length=128)
    threat: ThreatClass
    channel: AttackChannel
    payload_json: str = Field(min_length=1, max_length=100_000)
    tags: frozenset[str] = frozenset()

    @classmethod
    def from_payload(
        cls,
        *,
        attack_id: str,
        revision: str,
        threat: ThreatClass,
        channel: AttackChannel,
        payload: Any,
        tags: frozenset[str] = frozenset(),
    ) -> Self:
        return cls(
            attack_id=attack_id,
            revision=revision,
            threat=threat,
            channel=channel,
            payload_json=_canonical_json(payload),
            tags=tags,
        )

    @field_validator("payload_json")
    @classmethod
    def canonicalize_payload_json(cls, value: str) -> str:
        parsed = _parse_payload_json(value)
        return _canonical_json(parsed)

    @field_validator("tags")
    @classmethod
    def reject_empty_tags(cls, value: frozenset[str]) -> frozenset[str]:
        if any(not tag.strip() for tag in value):
            raise ValueError("attack tags must be non-empty strings")
        return value

    @property
    def payload(self) -> Any:
        """Return a fresh decoded payload so callers cannot mutate fixture identity in place."""
        return json.loads(self.payload_json)

    @property
    def identity(self) -> str:
        return _sha256_json(
            {
                "schema_version": self.schema_version,
                "attack_id": self.attack_id,
                "revision": self.revision,
                "threat": self.threat.value,
                "channel": self.channel.value,
                "payload_json": self.payload_json,
                "tags": sorted(self.tags),
            }
        )

    def apply(self, base: EvaluationScenario) -> EvaluationScenario:
        """Derive one security scenario without broadening the base task or authority."""
        if _RESERVED_STATE_KEY in base.initial_state:
            raise ValueError(
                f"base scenario already uses reserved adversarial state key {_RESERVED_STATE_KEY!r}"
            )

        initial_state = deepcopy(base.initial_state)
        envelope = _AttackEnvelope(
            base_scenario_identity=base.identity,
            attack_identity=self.identity,
            attack=self,
        )
        initial_state[_RESERVED_STATE_KEY] = envelope.canonical_state()

        return EvaluationScenario(
            scenario_id=_derived_scenario_id(base, self),
            revision=f"{base.revision}|attack:{self.attack_id}@{self.revision}:{self.identity[:12]}",
            kind=ScenarioKind.SECURITY,
            objective=base.objective,
            initial_state=initial_state,
            authority=base.authority,
            required_outcomes=deepcopy(base.required_outcomes),
            forbidden_outcomes=deepcopy(base.forbidden_outcomes),
            tags=frozenset(
                {
                    *base.tags,
                    *self.tags,
                    "adversarial",
                    f"attack:{self.attack_id}",
                    f"threat:{self.threat.value}",
                    f"channel:{self.channel.value}",
                }
            ),
        )


class _AttackEnvelope(BaseModel):
    """Namespaced transport contract between scenario generation and evaluation environments."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/adversarial-envelope/v1"] = _ATTACK_ENVELOPE_SCHEMA
    base_scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    attack_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    attack: AttackFixture

    @model_validator(mode="after")
    def verify_attack_identity(self) -> Self:
        if self.attack_identity != self.attack.identity:
            raise ValueError("adversarial envelope attack identity does not match fixture")
        return self

    def canonical_state(self) -> dict[str, Any]:
        attack = self.attack.model_dump(mode="json")
        attack["tags"] = sorted(self.attack.tags)
        return {
            "schema_version": self.schema_version,
            "base_scenario_identity": self.base_scenario_identity,
            "attack_identity": self.attack_identity,
            "attack": attack,
        }


class AdversarialCampaign(BaseModel):
    """Canonical collection of independent attacks against one exact base scenario."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/adversarial-campaign/v1"] = _CAMPAIGN_SCHEMA
    campaign_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    revision: str = Field(min_length=1, max_length=128)
    base_scenario: EvaluationScenario
    base_scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    attacks: tuple[AttackFixture, ...] = Field(min_length=1, max_length=10_000)

    @model_validator(mode="before")
    @classmethod
    def bind_base_scenario_identity(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        raw_base = data.get("base_scenario")
        if raw_base is None:
            return data
        base = (
            raw_base
            if isinstance(raw_base, EvaluationScenario)
            else EvaluationScenario.model_validate(raw_base)
        )
        identity = base.identity
        supplied = data.get("base_scenario_identity")
        if supplied is not None and supplied != identity:
            raise ValueError("adversarial campaign base scenario identity does not match base")
        normalized = dict(data)
        normalized["base_scenario_identity"] = identity
        return normalized

    @field_validator("attacks")
    @classmethod
    def canonicalize_attacks(cls, value: tuple[AttackFixture, ...]) -> tuple[AttackFixture, ...]:
        attack_ids = [attack.attack_id for attack in value]
        if len(set(attack_ids)) != len(attack_ids):
            raise ValueError("adversarial campaign attack IDs must be unique")
        return tuple(sorted(value, key=lambda attack: (attack.attack_id, attack.identity)))

    @model_validator(mode="after")
    def reject_reserved_base_state(self) -> Self:
        if _RESERVED_STATE_KEY in self.base_scenario.initial_state:
            raise ValueError(
                f"base scenario already uses reserved adversarial state key {_RESERVED_STATE_KEY!r}"
            )
        return self

    @property
    def identity(self) -> str:
        return _sha256_json(
            {
                "schema_version": self.schema_version,
                "campaign_id": self.campaign_id,
                "revision": self.revision,
                "base_scenario_identity": self.base_scenario_identity,
                "attack_identities": [attack.identity for attack in self.attacks],
            }
        )

    def scenarios(self) -> tuple[EvaluationScenario, ...]:
        if self.base_scenario.identity != self.base_scenario_identity:
            raise ValueError("adversarial campaign base scenario drifted after construction")
        return tuple(attack.apply(self.base_scenario) for attack in self.attacks)


def extract_attack(
    scenario: EvaluationScenario,
    *,
    expected_base_scenario: EvaluationScenario | None = None,
) -> AttackFixture | None:
    """Validate and decode an attack envelope, optionally proving full scenario derivation."""
    raw = scenario.initial_state.get(_RESERVED_STATE_KEY)
    if raw is None:
        return None
    envelope = _AttackEnvelope.model_validate(raw)
    if expected_base_scenario is not None:
        if envelope.base_scenario_identity != expected_base_scenario.identity:
            raise ValueError(
                "adversarial envelope base scenario identity does not match expected base"
            )
        expected = envelope.attack.apply(expected_base_scenario)
        if expected.identity != scenario.identity:
            raise ValueError("adversarial scenario does not match deterministic attack derivation")
    return envelope.attack


def _derived_scenario_id(base: EvaluationScenario, attack: AttackFixture) -> str:
    candidate = f"{base.scenario_id}.adv.{attack.attack_id}"
    if len(candidate) <= 128:
        return candidate
    return f"{base.scenario_id[:96]}.adv.{attack.attack_id[:16]}.{attack.identity[:8]}"


def _parse_payload_json(value: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("attack payload_json must not contain duplicate object keys")
            result[key] = item
        return result

    try:
        return json.loads(value, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise ValueError("attack payload_json must contain valid JSON") from exc


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("adversarial payload must be finite JSON-compatible data") from exc
