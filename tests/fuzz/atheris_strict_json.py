"""Coverage-guided Atheris fuzzing of the evaluator-owned strict JSON trust boundary.

Unlike Hypothesis property tests, this is a real native libFuzzer-backed input
mutation and coverage campaign. It is bounded by the *workflow* invocation.
"""

from __future__ import annotations

import json
import sys

import atheris

with atheris.instrument_imports():
    from agent_evals._strict_json import StrictJsonError, strict_json_loads


@atheris.instrument_func
def test_one_input(data: bytes) -> None:
    if len(data) > 4096:
        return
    try:
        decoded = strict_json_loads(data, label="atheris hostile JSON")
    except StrictJsonError:
        try:
            strict_json_loads(data, label="atheris hostile JSON", require_object=True)
        except StrictJsonError:
            return
        raise AssertionError("object-root decoder accepted rejected JSON bytes") from None

    try:
        root = strict_json_loads(data, label="atheris object root", require_object=True)
    except StrictJsonError:
        if type(decoded) is dict:
            raise AssertionError("strict decoder rejected a valid JSON object root") from None
    else:
        if type(decoded) is not dict or root != decoded:
            raise AssertionError("JSON object-root decoder disagreed with general parser")

    serialized = json.dumps(
        decoded,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if strict_json_loads(serialized, label="atheris round-trip") != decoded:
        raise AssertionError("accepted JSON does not survive strict canonical round trip")


def main() -> None:
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
