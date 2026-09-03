"""Evidence-bound verification that an adversarial stimulus was actually delivered."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agent_evals.adversarial.cases import AttackChannel, extract_attack
from agent_evals.contracts.models import EvaluationScenario
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind, TrialEvidence

_DELIVERY_SCHEMA: Literal["agent-evals/attack-delivery/v1"] = "agent-evals/attack-delivery/v1"
_DELIVERY_DOMAIN = b"agent-evals/attack-delivery/v1\0"
_INJECTOR_SOURCE_PREFIX = "injector:"


class AttackDeliveryError(ValueError):
    """The evaluation environment did not prove exact adversarial stimulus delivery."""


class AttackDeliveryReceipt(BaseModel):
    """Content-addressed receipt for one controlled adversarial injection.

    The receipt binds identities and a payload digest, never the raw adversarial payload. Its
    `receipt_root` is an integrity identity, not injector authentication or target-side attestation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/attack-delivery/v1"] = _DELIVERY_SCHEMA
    scenario_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    attack_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    channel: AttackChannel
    injection_point: str = Field(min_length=1, max_length=512)
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_root: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_scenario(
        cls,
        scenario: EvaluationScenario,
        *,
        injection_point: str,
    ) -> Self:
        attack = extract_attack(scenario)
        if attack is None:
            raise ValueError("attack delivery receipt requires an adversarial scenario")
        unsigned = {
            "schema_version": _DELIVERY_SCHEMA,
            "scenario_identity": scenario.identity,
            "attack_identity": attack.identity,
            "channel": attack.channel.value,
            "injection_point": injection_point,
            "payload_sha256": hashlib.sha256(attack.payload_json.encode("utf-8")).hexdigest(),
        }
        return cls(
            schema_version=_DELIVERY_SCHEMA,
            scenario_identity=scenario.identity,
            attack_identity=attack.identity,
            channel=attack.channel,
            injection_point=injection_point,
            payload_sha256=unsigned["payload_sha256"],
            receipt_root=_receipt_root(unsigned),
        )

    @model_validator(mode="after")
    def verify_receipt_root(self) -> Self:
        expected = _receipt_root(self.model_dump(mode="json", exclude={"receipt_root"}))
        if not hmac.compare_digest(expected, self.receipt_root):
            raise ValueError("attack delivery receipt root does not match receipt content")
        return self

    def to_event(self, *, sequence: int, source: str) -> EvidenceEvent:
        """Emit the normalized evidence event recorded after controlled injection succeeds."""
        if not source.startswith(_INJECTOR_SOURCE_PREFIX) or len(source) == len(
            _INJECTOR_SOURCE_PREFIX
        ):
            raise ValueError("attack delivery evidence source must be 'injector:<identity>'")
        return EvidenceEvent(
            sequence=sequence,
            kind=EvidenceKind.ATTACK_DELIVERY,
            source=source,
            payload=self.model_dump(mode="json"),
        )


def verify_attack_delivery(
    scenario: EvaluationScenario,
    evidence: TrialEvidence,
) -> AttackDeliveryReceipt | None:
    """Require one exact delivery receipt for adversarial scenarios; ignore ordinary scenarios."""
    attack = extract_attack(scenario)
    if attack is None:
        return None

    events = tuple(event for event in evidence.events if event.kind is EvidenceKind.ATTACK_DELIVERY)
    if len(events) != 1:
        raise AttackDeliveryError(
            f"adversarial trial requires exactly one attack delivery receipt; observed {len(events)}"
        )

    event = events[0]
    if not event.source.startswith(_INJECTOR_SOURCE_PREFIX) or len(event.source) == len(
        _INJECTOR_SOURCE_PREFIX
    ):
        raise AttackDeliveryError("attack delivery receipt has an untrusted injector source label")

    try:
        receipt = AttackDeliveryReceipt.model_validate(event.payload)
    except ValidationError as exc:
        raise AttackDeliveryError("attack delivery receipt is malformed or internally inconsistent") from exc

    expected = AttackDeliveryReceipt.from_scenario(
        scenario,
        injection_point=receipt.injection_point,
    )
    if receipt != expected:
        raise AttackDeliveryError(
            "attack delivery receipt does not match the exact scenario, attack, channel, or payload"
        )
    return receipt


def _receipt_root(value: object) -> str:
    return hashlib.sha256(_DELIVERY_DOMAIN + _canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
