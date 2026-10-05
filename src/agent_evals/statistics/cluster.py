"""Cluster-aware binary estimation without pseudo-replicating correlated attempts."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, log, sqrt

from agent_evals.evidence.models import TrialVerdict
from agent_evals.statistics.sufficient import BinarySufficientStatistics

MAX_CLUSTERS = 10_000
_MAX_CLUSTER_ID = 160


@dataclass(frozen=True, slots=True)
class ClusterCounts:
    cluster_id: str
    statistics: BinarySufficientStatistics

    def __post_init__(self) -> None:
        _validate_cluster_id(self.cluster_id)
        if type(self.statistics) is not BinarySufficientStatistics:
            raise ValueError("statistics must be exact BinarySufficientStatistics")
        self.statistics.validate()
        if self.statistics.resolved == 0:
            raise ValueError("every modeled cluster requires at least one resolved PASS/FAIL outcome")

    @property
    def success_rate(self) -> float:
        return self.statistics.passes / self.statistics.resolved

    @classmethod
    def from_verdicts(
        cls,
        cluster_id: str,
        verdicts: list[TrialVerdict] | tuple[TrialVerdict, ...],
    ) -> ClusterCounts:
        return cls(
            cluster_id=cluster_id,
            statistics=BinarySufficientStatistics.from_verdicts(verdicts),
        )


@dataclass(frozen=True, slots=True)
class ClusterAwareEstimate:
    """Equal-cluster estimate with a Hoeffding interval over independent cluster means.

    Attempts inside a cluster may be arbitrarily dependent. Interpretation still assumes the
    supplied clusters themselves are independent and represent the target cluster population.
    """

    clusters: tuple[ClusterCounts, ...]
    alpha: float = 0.05

    def __post_init__(self) -> None:
        if type(self.clusters) is not tuple:
            raise ValueError("clusters must be an exact tuple")
        if not 1 <= len(self.clusters) <= MAX_CLUSTERS:
            raise ValueError(f"cluster count must be in 1..{MAX_CLUSTERS}")
        _validate_alpha(self.alpha)
        seen: set[str] = set()
        for cluster in self.clusters:
            if type(cluster) is not ClusterCounts:
                raise ValueError("clusters must contain exact ClusterCounts values")
            if cluster.cluster_id in seen:
                raise ValueError("cluster identifiers must be unique")
            seen.add(cluster.cluster_id)

    @property
    def cluster_count(self) -> int:
        return len(self.clusters)

    @property
    def total_attempts(self) -> int:
        return sum(cluster.statistics.trials for cluster in self.clusters)

    @property
    def total_resolved(self) -> int:
        return sum(cluster.statistics.resolved for cluster in self.clusters)

    @property
    def blocked(self) -> int:
        return sum(cluster.statistics.blocked for cluster in self.clusters)

    @property
    def inconclusive(self) -> int:
        return sum(cluster.statistics.inconclusive for cluster in self.clusters)

    @property
    def equal_cluster_mean(self) -> float:
        return sum(cluster.success_rate for cluster in self.clusters) / self.cluster_count

    @property
    def interval(self) -> tuple[float, float]:
        radius = sqrt(log(2.0 / self.alpha) / (2.0 * self.cluster_count))
        return (
            max(0.0, self.equal_cluster_mean - radius),
            min(1.0, self.equal_cluster_mean + radius),
        )


def _validate_cluster_id(value: object) -> None:
    if type(value) is not str:
        raise ValueError("cluster_id must be an exact string")
    if (
        not value
        or len(value) > _MAX_CLUSTER_ID
        or value.strip() != value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(
            f"cluster_id must contain 1..{_MAX_CLUSTER_ID} trimmed characters without controls"
        )


def _validate_alpha(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, float) or not isfinite(value):
        raise ValueError("alpha must be a finite float in (0, 1)")
    if not 0.0 < value < 1.0:
        raise ValueError("alpha must be in (0, 1)")
