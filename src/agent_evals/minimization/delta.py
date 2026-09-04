"""Delta debugging for reproducible agent failures.

The minimizer never decides that a smaller case is equivalent because it 'looks similar'. Every
accepted reduction must reproduce the caller-defined failure predicate.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")
FailurePredicate = Callable[[tuple[T, ...]], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class MinimizationResult(Generic[T]):
    original_size: int
    minimized: tuple[T, ...]
    evaluations: int
    exhausted: bool


async def ddmin(
    items: Sequence[T],
    reproduces_failure: FailurePredicate[T],
    *,
    max_evaluations: int = 1_000,
) -> MinimizationResult[T]:
    """Return a reduced failing subsequence using classic delta debugging.

    Order is preserved. The original input must reproduce the failure. Both subsets and
    complements are tested so non-monotonic failure predicates can still expose a smaller
    reproducer. A hard evaluation budget prevents a pathological oracle or expensive live agent
    from turning minimization into an unbounded secondary workload.
    """
    if not _is_positive_evaluation_budget(max_evaluations):
        raise ValueError("max_evaluations must be a positive integer")

    current = tuple(items)
    original_size = len(current)
    evaluations = 1
    if not await reproduces_failure(current):
        raise ValueError("original input does not reproduce the failure")
    if len(current) < 2:
        return MinimizationResult(original_size, current, evaluations, exhausted=False)

    granularity = 2
    while len(current) >= 2:
        ranges = _partition_ranges(len(current), granularity)
        reduced = False

        for start, stop in ranges:
            if evaluations >= max_evaluations:
                return MinimizationResult(original_size, current, evaluations, exhausted=True)
            subset = current[start:stop]
            evaluations += 1
            if await reproduces_failure(subset):
                current = subset
                granularity = 2
                reduced = True
                break
        if reduced:
            continue

        for start, stop in ranges:
            if evaluations >= max_evaluations:
                return MinimizationResult(original_size, current, evaluations, exhausted=True)
            complement = current[:start] + current[stop:]
            evaluations += 1
            if await reproduces_failure(complement):
                current = complement
                granularity = max(2, granularity - 1)
                reduced = True
                break
        if reduced:
            continue

        if granularity >= len(current):
            break
        granularity = min(len(current), granularity * 2)

    return MinimizationResult(original_size, current, evaluations, exhausted=False)


def _is_positive_evaluation_budget(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _partition_ranges(length: int, parts: int) -> tuple[tuple[int, int], ...]:
    if length < 1:
        return ()
    parts = max(1, min(parts, length))
    base, remainder = divmod(length, parts)
    ranges: list[tuple[int, int]] = []
    start = 0
    for index in range(parts):
        width = base + (1 if index < remainder else 0)
        stop = start + width
        ranges.append((start, stop))
        start = stop
    return tuple(ranges)
