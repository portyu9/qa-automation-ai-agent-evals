from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from agent_evals.evidence.store import LocalEvidenceStore


@pytest.mark.parametrize(
    "invalid_ceiling",
    [
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
        1.5,
        "64",
        None,
    ],
)
def test_payload_byte_ceiling_requires_positive_integer(
    tmp_path: Path,
    invalid_ceiling: object,
) -> None:
    root = tmp_path / "evidence"

    with pytest.raises(ValueError, match="byte ceilings must be positive integers"):
        LocalEvidenceStore(root, max_payload_bytes=cast(int, invalid_ceiling))

    assert not root.exists()


@pytest.mark.parametrize(
    "invalid_ceiling",
    [
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
        1.5,
        "64",
        None,
    ],
)
def test_manifest_byte_ceiling_requires_positive_integer(
    tmp_path: Path,
    invalid_ceiling: object,
) -> None:
    root = tmp_path / "evidence"

    with pytest.raises(ValueError, match="byte ceilings must be positive integers"):
        LocalEvidenceStore(root, max_manifest_bytes=cast(int, invalid_ceiling))

    assert not root.exists()
