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
    delivery receipt payload digest bound to the exact bytes prepended by the SDK session layer.
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


class ResourceAttackPayload(BaseModel):
    """Contract for one inline JSON file resource supplied to the OpenAI SDK run input.

    `resource` makes the fixture semantically explicit. The complete canonical
    `AttackFixture.payload_json` becomes the `file_data` of one structured `input_file` content
    item, so the delivery-receipt digest binds the exact resource bytes at the tested SDK input
    boundary. V1 does not claim file-search, vector-store, URL-fetch, or hosted retrieval control.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    resource: Any

    @classmethod
    def from_fixture(cls, attack: AttackFixture) -> Self:
        if attack.channel is not AttackChannel.RESOURCE:
            raise ValueError("resource payload contract requires a RESOURCE attack fixture")
        try:
            return cls.model_validate(attack.payload)
        except ValidationError as exc:
            raise ValueError(
                "resource attack payload must be a JSON object with a 'resource' field"
            ) from exc


class HandoffAttackPayload(BaseModel):
    """Contract for one-shot poisoning of context transferred across the first SDK handoff.

    `handoff` makes the fixture semantically explicit. The complete canonical
    `AttackFixture.payload_json` is appended to the run input history by the SDK handoff input
    filter, so the standard delivery-receipt digest binds the exact context bytes visible to the
    receiving agent. The v1 contract does not select or replace the destination agent.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    handoff: Any

    @classmethod
    def from_fixture(cls, attack: AttackFixture) -> Self:
        if attack.channel is not AttackChannel.HANDOFF:
            raise ValueError("handoff payload contract requires a HANDOFF attack fixture")
        try:
            return cls.model_validate(attack.payload)
        except ValidationError as exc:
            raise ValueError(
                "handoff attack payload must be a JSON object with a 'handoff' field"
            ) from exc


class EnvironmentAttackPayload(_LocalToolAttackPayload):
    """Contract for one-shot trial-local SDK runtime-context perturbation.

    `tool` selects one exact local SDK FunctionTool and `key` selects one exact application-context
    key. `environment` makes the fixture semantically explicit, while the complete canonical
    `AttackFixture.payload_json` becomes the value returned for that key only during the first
    matching tool invocation. Delivery is not established until subject code actually reads the
    key. V1 intentionally targets Mapping-compatible local SDK context rather than process-global
    ``os.environ`` or arbitrary infrastructure state.
    """

    key: str = Field(min_length=1, max_length=256)
    environment: Any

    @field_validator("key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("environment attack key must be non-empty")
        if normalized != value:
            raise ValueError("environment attack key must not contain surrounding whitespace")
        return normalized

    @classmethod
    def from_fixture(cls, attack: AttackFixture) -> Self:
        if attack.channel is not AttackChannel.ENVIRONMENT:
            raise ValueError("environment payload contract requires an ENVIRONMENT attack fixture")
        try:
            return cls.model_validate(attack.payload)
        except ValidationError as exc:
            raise ValueError(
                "environment attack payload must be a JSON object with valid 'tool', 'key', and "
                "'environment' fields"
            ) from exc
