"""Internal helper for fully validated self-verifying receipt construction."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationInfo

_RECEIPT_CONSTRUCTION_CONTEXT = "agent_evals_receipt_construction"
TReceipt = TypeVar("TReceipt", bound=BaseModel)


def validate_receipt_construction(
    model_type: type[TReceipt],
    /,
    **values: object,
) -> TReceipt:
    """Validate all fields while suppressing only the final recomputation pass."""

    return model_type.model_validate(
        values,
        context={_RECEIPT_CONSTRUCTION_CONTEXT: True},
    )


def is_receipt_construction(info: ValidationInfo) -> bool:
    """Return whether validation is the trusted constructor's final validation pass."""

    return bool(info.context and info.context.get(_RECEIPT_CONSTRUCTION_CONTEXT) is True)


__all__ = ["is_receipt_construction", "validate_receipt_construction"]
