# ƳƤ AI Agent Evaluation & Assurance Framework — Documentation

This documentation is organized by the question a reviewer is trying to answer. The framework keeps **subject identity**, **scenario/adversarial identity**, **evaluation-precondition evidence**, **protocol-fault evidence**, **subject evidence**, **deterministic authority**, **persistence integrity**, **session derivation**, and **statistical inference** separate. A statement from one domain never silently becomes proof in another.

## Review paths

| Reviewer goal | Recommended path |
|---|---|
| Architecture / principal engineering | [Architecture](ARCHITECTURE.md) → [Evaluation Model](EVALUATION_MODEL.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [MCP Fault Lab](MCP_LAB.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Session Reports](ASSURANCE_REPORTS.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [Metamorphic Testing](METAMORPHIC_TESTING.md) → [Statistical Assurance](STATISTICAL_ASSURANCE.md) → [Limitations](LIMITATIONS.md) |
| QA / AI evaluation engineering | [Evaluation Model](EVALUATION_MODEL.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [MCP Fault Lab](MCP_LAB.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Session Reports](ASSURANCE_REPORTS.md) → [Metamorphic Testing](METAMORPHIC_TESTING.md) → [Statistical Assurance](STATISTICAL_ASSURANCE.md) → [Architecture](ARCHITECTURE.md) |
| Security / red team | [Security](SECURITY.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [MCP Fault Lab](MCP_LAB.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Architecture](ARCHITECTURE.md) → [Limitations](LIMITATIONS.md) |
| Adoption / code review | [Architecture](ARCHITECTURE.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [MCP Fault Lab](MCP_LAB.md) → repository tests → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Limitations](LIMITATIONS.md) |

## Cross-cutting invariants

```text
Agent claim                ≠ environment outcome
Tool request               ≠ successful side effect
Approval request           ≠ approval grant
Provider availability      ≠ subject correctness
Model confidence           ≠ grading authority
Attack channel label       ≠ delivery evidence
Environment availability   ≠ environment consumption
MCP fault configuration    ≠ MCP client observation
MCP protocol delivery      ≠ agent behavioral resistance
Delivery receipt           ≠ target-side attestation
Unverified delivery        ≠ behavioral FAIL
Attack fixture hash        ≠ proof the subject resisted the attack
Single passing trial       ≠ reliability
Raw percentage delta       ≠ statistically established change
Exact trajectory mismatch  ≠ failure unless the trajectory is contractual
Blocked execution          ≠ behavioral FAIL
Inconclusive evidence      ≠ PASS
Critical safety violation  ≠ compensable score loss
Narrower-looking policy    ≠ proven authority reduction
Stored hash                ≠ authenticated publisher
Evidence replay            ≠ fresh execution or fresh injection
Serialized gate result     ≠ trusted without recomputation
Assurance report root      ≠ signed attestation
```

## Current documentation set

| Document | Primary question |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Where do identity, adversarial derivation, protocol faults, delivery verification, evidence, grading, persistence, reporting, and release authority live? |
| [EVALUATION_MODEL.md](EVALUATION_MODEL.md) | What exactly constitutes a task, trial, outcome, policy violation, and verdict? |
| [ADVERSARIAL_TESTING.md](ADVERSARIAL_TESTING.md) | How are red-team stimuli made deterministic, how is delivery required before grading, and what does an adversarial receipt still not prove? |
| [MCP_LAB.md](MCP_LAB.md) | How are deterministic MCP protocol faults delivered and observed without confusing protocol evidence with agent assurance? |
| [EVIDENCE_AND_REPLAY.md](EVIDENCE_AND_REPLAY.md) | How are local evidence records committed, reverified, and replayed without overstating provenance? |
| [ASSURANCE_REPORTS.md](ASSURANCE_REPORTS.md) | How are session conclusions bound and rederived without turning a serialized score or gate label into authority? |
| [OPENAI_ADAPTER.md](OPENAI_ADAPTER.md) | How are OpenAI Agents SDK events normalized without making the provider the oracle? |
| [METAMORPHIC_TESTING.md](METAMORPHIC_TESTING.md) | Which behavioral relations can be verified without brittle golden outputs? |
| [STATISTICAL_ASSURANCE.md](STATISTICAL_ASSURANCE.md) | How is nondeterministic behavior quantified without overstating certainty? |
| [SECURITY.md](SECURITY.md) | Which agentic threats are modeled, which adversarial/protocol controls exist, and which boundaries remain external? |
| [LIMITATIONS.md](LIMITATIONS.md) | What does the repository deliberately not claim yet? |

New documents are added only after executable code or a real deployment/protocol boundary creates a contract that reviewers need to inspect.

[← Repository README](../README.md)
