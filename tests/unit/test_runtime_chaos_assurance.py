from __future__ import annotations

from agent_evals.runtime.chaos import (
    ChaosAssuranceReceipt,
    ChaosDomain,
    ChaosObservation,
    ChaosOutcome,
    ChaosPolicy,
)


def _observation(
    domain: ChaosDomain,
    index: int,
    *,
    outcome: ChaosOutcome = ChaosOutcome.RECOVERED,
) -> ChaosObservation:
    return ChaosObservation(
        domain=domain,
        injection_id=f"chaos.{index}",
        injected=True,
        outcome=outcome,
        recovery_ticks=10 if outcome is ChaosOutcome.RECOVERED else None,
        resource_peak_bytes=1024,
        error_code="evaluator-unavailable" if outcome is ChaosOutcome.BLOCKED else None,
    )


def test_chaos_assurance_covers_all_domains_without_flattening_subject_failure() -> None:
    observations = tuple(
        _observation(
            domain,
            index,
            outcome=ChaosOutcome.SUBJECT_FAILURE
            if domain is ChaosDomain.CREDENTIAL_EXPIRY
            else ChaosOutcome.RECOVERED,
        )
        for index, domain in enumerate(ChaosDomain)
    )

    receipt = ChaosAssuranceReceipt.create(
        policy=ChaosPolicy(),
        observations=observations,
    )

    assert set(receipt.covered_domains) == set(ChaosDomain)
    assert receipt.recovered == len(ChaosDomain) - 1
    assert receipt.subject_failures == 1
    assert receipt.blocked == 0
    assert receipt.qualification_complete is True


def test_blocked_chaos_evaluator_uncertainty_remains_distinct_and_blocks_qualification() -> None:
    observations = tuple(
        _observation(
            domain,
            index,
            outcome=ChaosOutcome.BLOCKED if domain is ChaosDomain.DNS else ChaosOutcome.RECOVERED,
        )
        for index, domain in enumerate(ChaosDomain)
    )

    receipt = ChaosAssuranceReceipt.create(
        policy=ChaosPolicy(),
        observations=observations,
    )

    assert receipt.blocked == 1
    assert receipt.subject_failures == 0
    assert receipt.qualification_complete is False

def test_unordered_chaos_policy_is_root_stable_and_round_trips() -> None:
    domains = list(ChaosDomain)
    policy_a = ChaosPolicy(required_domains=frozenset(domains))
    policy_b = ChaosPolicy(required_domains=frozenset(reversed(domains)))
    observations = tuple(_observation(domain, index) for index, domain in enumerate(domains))

    receipt_a = ChaosAssuranceReceipt.create(policy=policy_a, observations=observations)
    receipt_b = ChaosAssuranceReceipt.create(policy=policy_b, observations=observations)

    assert policy_a.model_dump_json() == policy_b.model_dump_json()
    assert receipt_a.receipt_root == receipt_b.receipt_root
    round_tripped = ChaosAssuranceReceipt.model_validate_json(receipt_a.model_dump_json())
    assert round_tripped.receipt_root == receipt_a.receipt_root
