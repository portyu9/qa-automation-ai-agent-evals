"""Channel-specific contracts for concrete adversarial delivery implementations."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from agent_evals.adversarial.cases import AttackChannel, AttackFixture


class _LocalToolAttackPayload(BaseModel):
    """Common exact-name routing contract for attacks targeting one local SDK tool."""

    model_config = ConfigDict(frozen=True, extra="allow")

    tool: str = Field(min_length=1, max_length=128)

    @field_validator("tool")
    @classmethod
    def normalize_tool(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("local-tool attack target must be non-empty")
        if normalized != value:
            raise ValueError("local-tool attack target must not contain surrounding whitespace")
        return normalized


class ToolResultAttackPayload(_LocalToolAttackPayload):
    """Routing contract for a deterministic tool-result replacement attack.

    The complete canonical `AttackFixture.payload_json` remains the model-visible replacement
    output. Requiring `tool` and `result` inside that same identity-bearing payload keeps both the
    target selector and the injected bytes bound to the attack identity and delivery receipt.
    Additional JSON fields are permitted because realistic tool-result envelopes vary by system.
    """

    result: Any

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


class ToolMetadataAttackPayload(_LocalToolAttackPayload):
    """Routing contract for deterministic local function-tool description poisoning.

    `tool` identifies one exact local SDK FunctionTool. `description` makes the fixture
    self-describing, while the complete canonical `AttackFixture.payload_json` is what the adapter
    places in the copied FunctionTool description. The delivery receipt therefore binds the exact
    model-visible metadata bytes rather than an adapter-selected nested field.
    """

    description: Any

    @classmethod
    def from_fixture(cls, attack: AttackFixture) -> Self:
        if attack.channel is not AttackChannel.TOOL_METADATA:
            raise ValueError(
                "tool-metadata payload contract requires a TOOL_METADATA attack fixture"
            )
        try:
            return cls.model_validate(attack.payload)
        except ValidationError as exc:
            raise ValueError(
                "tool-metadata attack payload must be a JSON object with valid 'tool' and "
                "'description' fields"
            ) from exc


class MemoryAttackPayload(BaseModel):
    """Contract for deterministic poisoned OpenAI SDK session-history memory.

    `memory` makes the fixture semantically explicit, while the complete canonical
    `AttackFixture.payload_json` becomes one prior session-history user message. That keeps the
    delivery receipt's payload digest bound to the exact bytes prepended by the SDK session layer.
    Additional fields are allowed for realistic memory envelopes.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    memory: Any

    @classmethod
    def from_fixture(cls, attack: AttackFixture) -> Self:
        if attack.channel is not AttackChannel.MEMORY:
            raise ValueError("memory payload contract requires a MEMORY attack fixture")
        try:
            return cls.model_validate(attack.payload)
        except ValidationError as exc:
            raise ValueError(
                "memory attack payload must be a JSON object with a 'memory' field"
            ) from exc
