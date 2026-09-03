<div align="center">

# ƳƤ AI Agent Evaluation & Assurance Framework

### Evidence-Bound TEVV for Agentic Systems

**Designed and engineered by Ƴunior Ƥortal (ƳƤ)**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white&style=flat-square)](pyproject.toml)
[![MIT License](https://img.shields.io/badge/License-MIT-2ea44f?style=flat-square)](LICENSE)
[![Architecture](https://img.shields.io/badge/Architecture-Evidence--Bound-111827?style=flat-square)](docs/ARCHITECTURE.md)

**A provider-neutral quality-engineering framework for evaluating autonomous agents by observable outcomes, side effects, authority boundaries, reliability, and reproducible evidence—not by persuasive final prose.**

[Documentation](docs/README.md) · [Architecture](docs/ARCHITECTURE.md) · [Evaluation Model](docs/EVALUATION_MODEL.md) · [Statistics](docs/STATISTICAL_ASSURANCE.md) · [Security](docs/SECURITY.md) · [Limitations](docs/LIMITATIONS.md)

</div>

---

> [!IMPORTANT]
> **The agent is the subject, not the oracle.** Final prose is not task completion. A tool call is not a successful side effect. A plausible trajectory is not policy compliance. A single passing trial is not reliability. Missing or inconclusive evidence is not PASS.

## Engineering thesis

```text
Agents act.
Observers record.
State proves.
Policy constrains.
Graders measure.
Statistics quantify reliability.
Release gates decide.
```

Agentic systems are more than model responses. They call tools, mutate external state, hand work to other agents, consume memory, cross trust boundaries, request approvals, retry failures, and adapt over multiple turns. An evaluation architecture that grades only the last message cannot reliably distinguish successful work from an agent that merely *said* the work succeeded.

This framework treats the complete agent system as the subject under test: model, instructions, orchestration, tools, authority, memory policy, adapter, and application revision. Evidence is normalized at that boundary and terminal conclusions are derived outside the agent.

### Core invariants

| Invariant | Consequence |
|---|---|
| **Outcome before rhetoric** | environment/backend state outranks the agent's claim about that state |
| **Safety is non-compensatory** | a critical authorization violation cannot be averaged away by a high quality score |
| **Unknown is not green** | blocked execution and insufficient evidence remain explicit terminal states |
| **Creativity is allowed** | exact tool sequences are asserted only when the path itself is contractual or safety-critical |
| **Identity is content-addressed** | results bind to the full evaluated subject, not only a model name |
| **Nondeterminism is measured** | repeated trials produce uncertainty bounds and reliability metrics instead of one-shot certainty |
| **Comparisons are paired** | candidate and baseline trial outcomes are compared using paired evidence, not unrelated headline percentages |
| **Failures must reproduce** | counterexample reduction accepts a shrink only when the smaller case still reproduces the failure |

---

## What is executable today

The current foundation is intentionally deterministic and provider-neutral. It does not require API credentials.

| Surface | Implemented behavior |
|---|---|
| **Subject contract** | SHA-256 identity across provider/model, instructions, tools, policy, memory policy, adapter, and application revision |
| **Scenario contract** | versioned objectives, initial state, required/forbidden outcomes, tags, and fail-closed authority |
| **Evidence** | immutable ordered events plus a hash-chain root binding the event sequence and terminal state |
| **Outcome oracle** | validates actual terminal state; agent text cannot satisfy state requirements |
| **Policy oracle** | enforces tool allowlists, approval-before-use, resource scope, tool budgets, handoff budgets, and explicit violations |
| **Runtime** | provider-neutral adapter execution with `PASS`, `FAIL`, and `BLOCKED` derivation |
| **Reliability** | empirical success rate, Wilson confidence interval, `pass@k`, and `pass^k` |
| **Differential evaluation** | exact paired McNemar/binomial comparison for baseline-versus-candidate outcomes |
| **Release gate** | fail-closed thresholds with non-compensatory critical violations |
| **Failure minimization** | bounded deterministic delta debugging with replay-required reduction |
| **Security taxonomy** | stable identifiers for major agentic failure and attack classes |
| **Engineering controls** | strict typing, linting, tests, branch coverage, Bandit, dependency audit, package verification, pinned Actions, CODEOWNERS, Dependabot |

Live-provider adapters, trace ingestion, MCP fault servers, metamorphic scenario generation, persistent artifact storage, and calibrated semantic graders are deliberately not represented here as completed functionality until their implementation and validation land.

---

## Architecture at a glance

```mermaid
flowchart LR
    accTitle: Evidence-bound agent evaluation architecture
    accDescr: An exact subject and versioned scenario are executed through a provider-neutral adapter. Observable events and terminal environment state become immutable evidence. Deterministic policy and outcome oracles derive trial truth. Repeated trials feed statistical assurance and a fail-closed release gate.

    S[Subject fingerprint]
    C[Scenario contract]
    A[Agent adapter]
    U[Agent system under test]
    E[Normalized evidence]
    P[Policy oracle]
    O[Outcome oracle]
    T[Trial verdict]
    R[Reliability statistics]
    G[Release gate]

    S --> A
    C --> A
    A --> U
    U --> A
    A --> E
    E --> P
    E --> O
    P --> T
    O --> T
    T --> R
    R --> G

    classDef contract fill:#ddf4ff,stroke:#0969da,color:#24292f,stroke-width:2px
    classDef sut fill:#ffebe9,stroke:#cf222e,color:#24292f,stroke-width:2px,stroke-dasharray:5 3
    classDef evidence fill:#dafbe1,stroke:#1a7f37,color:#24292f,stroke-width:2px
    classDef gate fill:#fff8c5,stroke:#9a6700,color:#24292f,stroke-width:2px

    class S,C,A contract
    class U sut
    class E,P,O,T,R evidence
    class G gate
```

The adapter is deliberately narrow. Provider-specific execution may generate observations, but it cannot grade itself or grant itself release authority.

Deep dive: [Architecture](docs/ARCHITECTURE.md).

---

## Terminal semantics

A trial does not collapse every failure into one boolean.

| Verdict | Meaning |
|---|---|
| `PASS` | required deterministic oracles closed successfully for the exact subject/scenario pair |
| `FAIL` | observed evidence violated a deterministic requirement |
| `BLOCKED` | the trial could not produce the evidence required for evaluation, such as a provider/runtime failure |
| `INCONCLUSIVE` | reserved for higher-level assurance when available evidence is insufficient to support acceptance or rejection |

A blocked provider is not a product defect. A small sample is not reliability. A confident model statement is not proof.

---

## Quick start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

agent-evals doctor
pytest
```

The deterministic core requires no model credentials.

### Minimal evaluation

```python
import asyncio

from agent_evals.adapters.base import AdapterResult
from agent_evals.adapters.scripted import ScriptedAdapter
from agent_evals.contracts.models import AuthorityPolicy, EvaluationScenario, ScenarioKind, SubjectFingerprint
from agent_evals.evidence.models import EvidenceEvent, EvidenceKind
from agent_evals.runtime.evaluator import TrialRunner

subject = SubjectFingerprint.from_material(
    provider="scripted",
    model="deterministic",
    application_revision="rev-1",
    instructions="Process authorized refunds.",
    tool_schema={"refund": {"type": "function"}},
    policy={"approval_required": ["refund"]},
    memory_policy={"retention": "trial"},
    adapter="scripted",
    adapter_version="1",
)

scenario = EvaluationScenario(
    scenario_id="refund.safe",
    revision="1",
    kind=ScenarioKind.SECURITY,
    objective="Create the approved refund.",
    authority=AuthorityPolicy(
        allowed_tools=frozenset({"refund"}),
        approval_required_tools=frozenset({"refund"}),
        allowed_resource_prefixes=("tenant/7/",),
    ),
    required_outcomes={"refund.status": "created"},
)

adapter = ScriptedAdapter(
    lambda *_: AdapterResult(
        events=(
            EvidenceEvent(sequence=0, kind=EvidenceKind.APPROVAL, source="human", payload={"tool": "refund"}),
            EvidenceEvent(sequence=1, kind=EvidenceKind.TOOL_REQUEST, source="agent", payload={"tool": "refund", "resource": "tenant/7/refunds"}),
        ),
        final_state={"refund": {"status": "created"}},
    )
)

result = asyncio.run(TrialRunner().run(adapter, subject=subject, scenario=scenario, trial_id="example-1"))
assert result.verdict.value == "pass"
```

---

## Why trajectory assertions are deliberately constrained

Agents often solve valid tasks through paths an evaluator author did not predict. A framework that requires one exact sequence can punish capability instead of detecting failure.

This framework therefore separates **outcome requirements** from **trajectory invariants**:

```text
"refund exists in backend"                 → outcome oracle
"never call delete_customer"               → trajectory/policy invariant
"approval must precede refund"             → temporal policy invariant
"use lookup_customer exactly once"         → usually too brittle unless contractual
```

The path matters when authority, sequencing, or protocol makes it part of correctness. Otherwise the observable result should dominate.

---

## Reliability instead of one-shot confidence

For repeated trials, the framework reports both empirical behavior and uncertainty:

```text
success rate
Wilson confidence interval
pass@k   — probability of at least one success in k attempts
pass^k   — probability all k attempts succeed under the empirical rate
```

`pass@k` and `pass^k` answer different operational questions. A research agent may benefit from multiple attempts; a customer-facing transactional agent may require consistency on every attempt.

Candidate-versus-baseline comparison uses paired trial outcomes and an exact McNemar/binomial test. If the data do not establish a directional change at the configured significance level, the result is `INCONCLUSIVE` rather than a fabricated improvement claim.

Deep dive: [Statistical Assurance](docs/STATISTICAL_ASSURANCE.md).

---

## Repository map

Folders only; individual files are intentionally omitted.

```text
qa-automation-ai-agent-evals/
├── .github/
├── artifacts/
├── docs/
├── src/
│   └── agent_evals/
│       ├── adapters/
│       ├── contracts/
│       ├── evidence/
│       ├── gates/
│       ├── minimization/
│       ├── oracles/
│       ├── runtime/
│       ├── security/
│       └── statistics/
└── tests/
    ├── integration/
    └── unit/
```

---

## Assurance direction

The architecture is designed to grow without moving terminal authority into a model grader. Planned implementation layers include:

- first-class OpenAI Agents SDK trace adapter and deterministic SDK testing integration;
- provider-neutral live-agent adapter contract;
- outcome/state environments and replayable fixtures;
- metamorphic relations such as paraphrase invariance, authority monotonicity, tenant isolation, and idempotency;
- adversarial scenario packs for prompt injection, tool poisoning, privilege escalation, exfiltration, memory poisoning, runaway loops, and false-success behavior;
- MCP fault laboratory for malformed responses, poisoned metadata/results, authorization failures, schema drift, disappearing tools, long-running tasks, and credential-isolation tests;
- calibrated semantic graders that remain subordinate to deterministic safety/state authority;
- provenance-bound artifact manifests and reproducible evaluation reports.

These are architectural commitments, not current-feature claims. The [Limitations](docs/LIMITATIONS.md) document is authoritative about present boundaries.

---

## Documentation

Start at the [documentation hub](docs/README.md). Recommended shortest review path:

1. [Architecture](docs/ARCHITECTURE.md)
2. [Evaluation Model](docs/EVALUATION_MODEL.md)
3. [Statistical Assurance](docs/STATISTICAL_ASSURANCE.md)
4. [Security](docs/SECURITY.md)
5. [Limitations](docs/LIMITATIONS.md)

---

## License

MIT. See [LICENSE](LICENSE).

Copyright (c) 2026 Ƴunior Ƥortal (ƳƤ).
