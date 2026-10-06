from __future__ import annotations

import agent_evals
from agent_evals.assurance import report as assurance_report
from agent_evals.evidence import legacy_v2
from agent_evals.receipts import ReceiptEnvelopeV1
from agent_evals.verification import EvidenceChain, VerificationFactClaim


def test_public_verification_api_is_additive_and_discoverable() -> None:
    expected = {
        "EvidenceChain",
        "OutcomeSelectorV1",
        "ProducerCapabilityAuthority",
        "ReceiptEnvelopeV1",
        "VerificationFactClaim",
        "VerificationGraph",
        "VerifiedCriticalityRecord",
        "project_typed_event",
        "structured_oracle_failures",
        "verify_fact_claim",
    }

    assert expected <= set(agent_evals.__all__)
    for name in expected:
        assert getattr(agent_evals, name) is not None


def test_schema_history_keeps_historical_domains_separate() -> None:
    assert legacy_v2._EVIDENCE_ROOT_DOMAIN == b"agent-evals/trial-evidence/v2\0"
    assert assurance_report._REPORT_SCHEMA == "agent-evals/assurance-report/v6"
    assert assurance_report._EVIDENCE_SCHEMA == "agent-evals/trial-evidence/v2"

    assert VerificationFactClaim.model_fields["schema_version"].default == (
        "agent-evals/verification-fact/v1"
    )
    assert (
        EvidenceChain.model_fields["schema_version"].default
        == "agent-evals/evidence-chain/v1"
    )
    assert ReceiptEnvelopeV1.model_fields["schema_version"].default == (
        "agent-evals/receipt-envelope/v1"
    )


def test_verification_module_does_not_import_provider_adapters() -> None:
    import agent_evals.verification as verification

    source_names = set(verification.__dict__)
    assert not any(name.startswith("OpenAIAgents") for name in source_names)
    assert "AgentAdapter" not in source_names
