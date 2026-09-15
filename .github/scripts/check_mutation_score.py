from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Final

MINIMUM_MUTATION_SCORE: Final = 95.0
_COUNT_FIELDS: Final = (
    "killed",
    "survived",
    "no_tests",
    "skipped",
    "suspicious",
    "timeout",
    "check_was_interrupted_by_user",
    "segfault",
)
_REQUIRED_FIELDS: Final = frozenset((*_COUNT_FIELDS, "total"))
_UNRESOLVED_FIELDS: Final = (
    "no_tests",
    "skipped",
    "suspicious",
    "timeout",
    "check_was_interrupted_by_user",
    "segfault",
)


class MutationScorePolicyError(ValueError):
    """Raised when mutation statistics cannot satisfy the repository policy."""


def _validated_counts(payload: object) -> dict[str, int]:
    if type(payload) is not dict:
        raise MutationScorePolicyError("mutation statistics root must be an exact JSON object")

    raw = payload
    actual_fields = set(raw)
    missing = sorted(_REQUIRED_FIELDS - actual_fields)
    unexpected = sorted(actual_fields - _REQUIRED_FIELDS)
    if missing or unexpected:
        raise MutationScorePolicyError(
            f"mutation statistics schema mismatch: missing={missing}, unexpected={unexpected}"
        )

    counts: dict[str, int] = {}
    for field in (*_COUNT_FIELDS, "total"):
        value = raw[field]
        if type(value) is not int or value < 0:
            raise MutationScorePolicyError(
                f"mutation statistic {field!r} must be a non-negative exact integer"
            )
        counts[field] = value
    return counts


def evaluate_mutation_statistics(payload: object) -> float:
    """Validate complete Mutmut CI statistics and return the accepted score."""

    counts = _validated_counts(payload)
    total = counts["total"]
    if total == 0:
        raise MutationScorePolicyError("mutation run produced zero mutants")

    exported_total = sum(counts[field] for field in _COUNT_FIELDS)
    if exported_total != total:
        # Mutmut 3.8.0 includes not-checked and type-check-caught mutants in `total`
        # but omits those statuses from export-cicd-stats. Any remainder is therefore
        # incomplete/unreported authority and must not silently improve the score.
        raise MutationScorePolicyError(
            "mutation statistics are incomplete: "
            f"total={total}, exported_statuses={exported_total}, "
            f"unreported={total - exported_total}"
        )

    unresolved = {field: counts[field] for field in _UNRESOLVED_FIELDS if counts[field]}
    if unresolved:
        raise MutationScorePolicyError(f"mutation run has unresolved statuses: {unresolved}")

    score = counts["killed"] * 100.0 / total
    if score < MINIMUM_MUTATION_SCORE:
        raise MutationScorePolicyError(
            f"mutation score {score:.2f}% is below required {MINIMUM_MUTATION_SCORE:.2f}% "
            f"({counts['killed']} killed, {counts['survived']} survived, {total} total)"
        )
    return score


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MutationScorePolicyError(f"mutation statistics file is missing: {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MutationScorePolicyError(
            f"cannot read valid mutation statistics from {path}: {exc}"
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enforce the repository mutation-score policy from Mutmut CI statistics."
    )
    parser.add_argument("stats", type=Path, help="path to mutmut-cicd-stats.json")
    args = parser.parse_args()

    try:
        payload = _load_json(args.stats)
        score = evaluate_mutation_statistics(payload)
    except MutationScorePolicyError as exc:
        parser.exit(1, f"mutation policy failed: {exc}\n")

    print(f"mutation policy passed: score={score:.2f}% minimum={MINIMUM_MUTATION_SCORE:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
