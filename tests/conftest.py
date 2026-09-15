from __future__ import annotations

import pytest


def pytest_make_parametrize_id(
    config: pytest.Config,
    val: object,
    argname: str,
) -> str | None:
    """Keep pytest ID generation from invoking hostile string-subclass overrides."""

    if isinstance(val, str) and type(val) is not str:
        return f"{type(val).__name__}-{argname}"
    return None
