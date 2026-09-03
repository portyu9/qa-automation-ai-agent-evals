"""Channel-specific contracts for concrete adversarial delivery implementations."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from agent_evals.adversarial.cases import AttackChannel, AttackFixture


class ToolResultAttackPayload(BaseModel):
    """Routing contract for a deterministic tool-result replacement attack.

    The complete canonical `AttackFixture.payload_json` remains the model-visible replacement
    output. Requiring `tool` and `result` inside that same identity-bearing payload keeps both the
    target selector and the injected bytes bound to the attack identity and delivery receipt.
    Additional JSON fields are permitted because realistic tool-result envelopes vary by system.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    tool: str = Field(min_length=1, max_length=128)
    result: Any

    @field_validator("tool")
    @classmethod
    def normalize_tool(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tool-result attack tool must be non-empty")
        if normalized != value:
            raise ValueError("tool-result attack tool must not contain surrounding whitespace")
        return normalized

    @classmethod
    def from_fixture(cls, attack: AttackFixture) -> Self:
        if attack.channel is not AttackChannel.TOOL_RESULT:
            raise ValueError("tool-result payload contract requires a TOOL_RESULT attack fixture")
        try:
            return cls.model_validate(attack.payload)
        except ValidationError as exc:
            raise ValueError(
                "tool-result attack payload must be a JSON object with valid 'tool' and 'result' fields"
            ) from exc
