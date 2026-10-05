from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _PROJECT_ROOT / ".github/scripts/release_supply_chain.py"
_POLICY = _PROJECT_ROOT / ".github/dependency-license-policy.json"


def test_release_supply_chain_self_test() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "self-test"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "release supply-chain self-test: ok" in result.stdout


def test_dependency_license_policy_is_canonical_and_fail_closed() -> None:
    raw = _POLICY.read_bytes()
    payload = json.loads(raw.decode("utf-8"))

    assert raw == (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    assert payload["schema_version"] == "agent-evals/dependency-license-policy/v1"
    assert payload["allow_license_refs"] is False
    assert payload["allowed_spdx_licenses"] == sorted(set(payload["allowed_spdx_licenses"]))
    assert payload["denied_spdx_licenses"] == sorted(set(payload["denied_spdx_licenses"]))
    assert not (set(payload["allowed_spdx_licenses"]) & set(payload["denied_spdx_licenses"]))
