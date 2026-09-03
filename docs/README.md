# ƳƤ AI Agent Evaluation & Assurance Framework — Documentation

This documentation is organized by the question a reviewer is trying to answer. The framework keeps **subject identity**, **observed evidence**, **deterministic authority**, and **statistical inference** separate. A statement from one domain never silently becomes proof in another.

## Review paths

| Reviewer goal | Recommended path |
|---|---|
| Architecture / principal engineering | [Architecture](ARCHITECTURE.md) → [Evaluation Model](EVALUATION_MODEL.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [Metamorphic Testing](METAMORPHIC_TESTING.md) → [Statistical Assurance](STATISTICAL_ASSURANCE.md) → [Limitations](LIMITATIONS.md) |
| QA / AI evaluation engineering | [Evaluation Model](EVALUATION_MODEL.md) → [Metamorphic Testing](METAMORPHIC_TESTING.md) → [Statistical Assurance](STATISTICAL_ASSURANCE.md) → [Architecture](ARCHITECTURE.md) |
| Security / red team | [Security](SECURITY.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [Metamorphic Testing](METAMORPHIC_TESTING.md) → [Architecture](ARCHITECTURE.md) → [Limitations](LIMITATIONS.md) |
| Adoption / code review | [Architecture](ARCHITECTURE.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → repository tests → [Limitations](LIMITATIONS.md) |

## Cross-cutting invariants

```text
Agent claim                ≠ environment outcome
Tool request               ≠ successful side effect
Approval request           ≠ approval grant
Provider availability      ≠ subject correctness
Model confidence           ≠ grading authority
Single passing trial       ≠ reliability
Raw percentage delta       ≠ statistically established change
Exact trajectory mismatch  ≠ failure unless the trajectory is contractual
Blocked execution          ≠ behavioral FAIL
Inconclusive evidence      ≠ PASS
Critical safety violation  ≠ compensable score loss
Narrower-looking policy    ≠ proven authority reduction
```

## Current documentation set

| Document | Primary question |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Where do identity, evidence, grading, and release authority live? |
| [EVALUATION_MODEL.md](EVALUATION_MODEL.md) | What exactly constitutes a task, trial, outcome, policy violation, and verdict? |
| [OPENAI_ADAPTER.md](OPENAI_ADAPTER.md) | How are OpenAI Agents SDK events normalized without making the provider the oracle? |
| [METAMORPHIC_TESTING.md](METAMORPHIC_TESTING.md) | Which behavioral relations can be verified without brittle golden outputs? |
| [STATISTICAL_ASSURANCE.md](STATISTICAL_ASSURANCE.md) | How is nondeterministic behavior quantified without overstating certainty? |
| [SECURITY.md](SECURITY.md) | Which agentic threats are modeled and which controls are already deterministic? |
| [LIMITATIONS.md](LIMITATIONS.md) | What does the repository deliberately not claim yet? |

As implementation surfaces land, new documents are added only when there is executable code or a deployment boundary that requires an explicit contract.

[← Repository README](../README.md)
