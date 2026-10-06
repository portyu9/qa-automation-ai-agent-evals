"""Versioned, unambiguous selectors for terminal JSON state.

Historical EvaluationScenario.required_outcomes/forbidden_outcomes continue to use their existing
dotted-key interpretation. OutcomeSelectorV1 is an additive migration target: an RFC-6901-style JSON
Pointer subset whose version and escaping rules are explicit.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

_SELECTOR_SCHEMA: Literal["agent-evals/outcome-selector/v1"] = "agent-evals/outcome-selector/v1"


def _escape(segment: str) -> str:
    return segment.replace("~", "~0").replace("/", "~1")


def _unescape(segment: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(segment):
        char = segment[index]
        if char != "~":
            output.append(char)
            index += 1
            continue
        if index + 1 >= len(segment):
            raise ValueError("outcome selector contains a dangling escape")
        escape = segment[index + 1]
        if escape == "0":
            output.append("~")
        elif escape == "1":
            output.append("/")
        else:
            raise ValueError("outcome selector contains an unsupported escape")
        index += 2
    return "".join(output)


class OutcomeSelectorV1(BaseModel):
    """Canonical JSON-pointer selector with explicit schema/version identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["agent-evals/outcome-selector/v1"] = _SELECTOR_SCHEMA
    pointer: str = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_pointer(self) -> Self:
        segments = self.segments
        canonical = "/" + "/".join(_escape(segment) for segment in segments)
        if self.pointer != canonical:
            raise ValueError("outcome selector pointer is not canonical v1 form")
        return self

    @property
    def segments(self) -> tuple[str, ...]:
        if not self.pointer.startswith("/"):
            raise ValueError("outcome selector v1 must start with '/'")
        raw = self.pointer[1:].split("/")
        if not raw or any(segment == "" for segment in raw):
            raise ValueError("outcome selector v1 requires non-empty path segments")
        return tuple(_unescape(segment) for segment in raw)

    @classmethod
    def from_segments(cls, segments: tuple[str, ...]) -> Self:
        if not segments or any(type(segment) is not str or not segment for segment in segments):
            raise ValueError("outcome selector requires non-empty exact string segments")
        pointer = "/" + "/".join(_escape(segment) for segment in segments)
        return cls(pointer=pointer)

    def lookup(self, state: dict[str, Any]) -> tuple[bool, Any]:
        current: Any = state
        for segment in self.segments:
            if not isinstance(current, dict) or segment not in current:
                return False, None
            current = current[segment]
        return True, current
