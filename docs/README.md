# ƳƤ AI Agent Evaluation & Assurance Framework — Documentation

This documentation is organized by the question a reviewer is trying to answer. The framework keeps **subject identity**, **scenario/adversarial identity**, **observed evidence**, **deterministic authority**, **persistence integrity**, **session derivation**, and **statistical inference** separate. A statement from one domain never silently becomes proof in another.

## Review paths

| Reviewer goal | Recommended path |
|---|---|
| Architecture / principal engineering | [Architecture](ARCHITECTURE.md) → [Evaluation Model](EVALUATION_MODEL.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Session Reports](ASSURANCE_REPORTS.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [Metamorphic Testing](METAMORPHIC_TESTING.md) → [Statistical Assurance](STATISTICAL_ASSURANCE.md) → [Limitations](LIMITATIONS.md) |
| QA / AI evaluation engineering | [Evaluation Model](EVALUATION_MODEL.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Session Reports](ASSURANCE_REPORTS.md) → [Metamorphic Testing](METAMORPHIC_TESTING.md) → [Statistical Assurance](STATISTICAL_ASSURANCE.md) → [Architecture](ARCHITECTURE.md) |
| Security / red team | [Security](SECURITY.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Session Reports](ASSURANCE_REPORTS.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [Architecture](ARCHITECTURE.md) → [Limitations](LIMITATIONS.md) |
| Adoption / code review | [Architecture](ARCHITECTURE.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Session Reports](ASSURANCE_REPORTS.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → repository tests → [Limitations](LIMITATIONS.md) |

## Cross-cutting invariants

```text
Agent claim                ≠ environment outcome
Tool request               ≠ successful side effect
Approval request           ≠ approval grant
Provider availability      ≠ subject correctness
Model confidence           ≠ grading authority
Attack channel label       ≠ proof the stimulus was delivered
Attack fixture hash        ≠ proof the subject resisted the attack
Single passing trial       ≠ reliability
Raw percentage delta       ≠ statistically established change
Exact trajectory mismatch  ≠ failure unless the trajectory is contractual
Blocked execution          ≠ behavioral FAIL
Inconclusive evidence      ≠ PASS
Critical safety violation  ≠ compensable score loss
Narrower-looking policy    ≠ proven authority reduction
Stored hash                ≠ authenticated publisher
Evidence replay            ≠ fresh execution
Serialized gate result     ≠ trusted without recomputation
Assurance report root      ≠ signed attestation
```

## Current documentation set

| Document | Primary question |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Where do identity, adversarial derivation, evidence, grading, persistence, reporting, and release authority live? |
| [EVALUATION_MODEL.md](EVALUATION_MODEL.md) | What exactly constitutes a task, trial, outcome, policy violation, and verdict? |
| [ADVERSARIAL_TESTING.md](ADVERSARIAL_TESTING.md) | How are red-team stimuli made deterministic and content-addressed without pretending a channel label proves delivery? |
| [EVIDENCE_AND_REPLAY.md](EVIDENCE_AND_REPLAY.md) | How are local evidence records committed, reverified, and replayed without overstating provenance? |
| [ASSURANCE_REPORTS.md](ASSURANCE_REPORTS.md) | How are session conclusions bound and rederived without turning a serialized score or gate label into authority? |
| [OPENAI_ADAPTER.md](OPENAI_ADAPTER.md) | How are OpenAI Agents SDK events normalized without making the provider the oracle? |
| [METAMORPHIC_TESTING.md](METAMORPHIC_TESTING.md) | Which behavioral relations can be verified without brittle golden outputs? |
| [STATISTICAL_ASSURANCE.md](STATISTICAL_ASSURANCE.md) | How is nondeterministic behavior quantified without overstating certainty? |
| [SECURITY.md](SECURITY.md) | Which agentic threats are modeled, which adversarial controls exist, and which boundaries remain external? |
| [LIMITATIONS.md](LIMITATIONS.md) | What does the repository deliberately not claim yet? |

As implementation surfaces land, new documents are added only when there is executable code or a deployment boundary that requires an explicit contract.

[← Repository README](../README.md)
