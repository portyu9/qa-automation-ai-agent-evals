# ƳƤ AI Agent Evaluation & Assurance Framework — Documentation

This documentation is organized by the question a reviewer is trying to answer. The framework keeps **subject identity**, **scenario/adversarial identity**, **evaluation-precondition evidence**, **MCP protocol-fault evidence**, **MCP resource-server authorization evidence**, **MCP OAuth-flow evidence**, **subject evidence**, **deterministic authority**, **persistence integrity**, **session derivation**, and **statistical inference** separate. A statement from one domain never silently becomes proof in another.

## Review paths

| Reviewer goal | Recommended path |
|---|---|
| Architecture / principal engineering | [Architecture](ARCHITECTURE.md) → [Evaluation Model](EVALUATION_MODEL.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [MCP Fault Lab](MCP_LAB.md) → [MCP Remote Authorization](MCP_REMOTE_AUTH.md) → [MCP OAuth Flow](MCP_OAUTH_FLOW.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Session Reports](ASSURANCE_REPORTS.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [Metamorphic Testing](METAMORPHIC_TESTING.md) → [Statistical Assurance](STATISTICAL_ASSURANCE.md) → [Limitations](LIMITATIONS.md) |
| QA / AI evaluation engineering | [Evaluation Model](EVALUATION_MODEL.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [MCP Fault Lab](MCP_LAB.md) → [MCP Remote Authorization](MCP_REMOTE_AUTH.md) → [MCP OAuth Flow](MCP_OAUTH_FLOW.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Session Reports](ASSURANCE_REPORTS.md) → [Metamorphic Testing](METAMORPHIC_TESTING.md) → [Statistical Assurance](STATISTICAL_ASSURANCE.md) → [Architecture](ARCHITECTURE.md) |
| Security / red team | [Security](SECURITY.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [MCP Fault Lab](MCP_LAB.md) → [MCP Remote Authorization](MCP_REMOTE_AUTH.md) → [MCP OAuth Flow](MCP_OAUTH_FLOW.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Architecture](ARCHITECTURE.md) → [Limitations](LIMITATIONS.md) |
| Adoption / code review | [Architecture](ARCHITECTURE.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [MCP Fault Lab](MCP_LAB.md) → [MCP Remote Authorization](MCP_REMOTE_AUTH.md) → [MCP OAuth Flow](MCP_OAUTH_FLOW.md) → repository tests → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Limitations](LIMITATIONS.md) |

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
Cached MCP discovery       ≠ current MCP server contract
Current MCP contract       ≠ cached client discovery
MCP protocol delivery      ≠ agent behavioral resistance
Bearer authentication      ≠ verifier-owned issuer/resource policy
Resource-server success    ≠ OAuth-flow correctness
OAuth-flow success         ≠ agent correctness
Authorization success      ≠ agent correctness
Remote-auth receipt        ≠ OAuth-flow receipt
OAuth-flow receipt         ≠ agent behavioral assurance
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
| [ARCHITECTURE.md](ARCHITECTURE.md) | Where do identity, adversarial derivation, protocol faults, resource-server authorization, OAuth-flow assurance, delivery verification, evidence, grading, persistence, reporting, and release authority live? |
| [EVALUATION_MODEL.md](EVALUATION_MODEL.md) | What exactly constitutes a task, trial, outcome, policy violation, and verdict? |
| [ADVERSARIAL_TESTING.md](ADVERSARIAL_TESTING.md) | How are red-team stimuli made deterministic, how is delivery required before grading, and what does an adversarial receipt still not prove? |
| [MCP_LAB.md](MCP_LAB.md) | How are six deterministic MCP content/discovery-state faults observed without confusing protocol evidence with agent assurance? |
| [MCP_REMOTE_AUTH.md](MCP_REMOTE_AUTH.md) | How is the isolated loopback Streamable HTTP resource-server bearer/scope/verifier boundary tested over real TCP? |
| [MCP_OAUTH_FLOW.md](MCP_OAUTH_FLOW.md) | How does the separate two-origin loopback OAuth client/authorization-server flow verify discovery, compatibility DCR, PKCE, exact issuer/resource binding, token exchange, authenticated introspection, and protected MCP use? |
| [EVIDENCE_AND_REPLAY.md](EVIDENCE_AND_REPLAY.md) | How are local evidence records committed, reverified, and replayed without overstating provenance? |
| [ASSURANCE_REPORTS.md](ASSURANCE_REPORTS.md) | How are session conclusions bound and rederived without turning a serialized score or gate label into authority? |
| [OPENAI_ADAPTER.md](OPENAI_ADAPTER.md) | How are OpenAI Agents SDK events normalized without making the provider the oracle? |
| [METAMORPHIC_TESTING.md](METAMORPHIC_TESTING.md) | Which behavioral relations can be verified without brittle golden outputs? |
| [STATISTICAL_ASSURANCE.md](STATISTICAL_ASSURANCE.md) | How is nondeterministic behavior quantified without overstating certainty? |
| [SECURITY.md](SECURITY.md) | Which agentic threats are modeled, which adversarial/protocol/auth controls exist, and which boundaries remain external? |
| [LIMITATIONS.md](LIMITATIONS.md) | What does the repository deliberately not claim yet? |

New documents are added only after executable code or a real deployment/protocol boundary creates a contract that reviewers need to inspect. `MCP_REMOTE_AUTH.md` exists because the repository has an independently executable resource-server authentication/authorization boundary; `MCP_OAUTH_FLOW.md` exists because the repository now also has an independently executable authorization-client/authorization-server flow across separate loopback origins. Neither evidence domain becomes agent behavioral evidence without an explicit integration contract.

## Audited implementation checkpoint

Audited implementation source checkpoint `ed0b1f9415e49b49a23c77c9372a5d09f70682fc`, CI run `33881346071`:

- deterministic core: **330 passed, 23 deselected**;
- branch coverage: **93.61%** against the 90% gate;
- strict mypy: **0 issues across 40 source files**;
- deterministic OpenAI SDK: **11/11 passed**;
- deterministic MCP protocol: **6/6 passed**;
- deterministic MCP remote auth: **3/3 passed**;
- deterministic MCP OAuth flow: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest** quality jobs, Ruff, formatter, Bandit, dependency audit, package integrity, and all **7/7 CI jobs**: green;
- dependency audit reported **no known vulnerabilities**; the project package itself is skipped because it is not published on PyPI.

This checkpoint identifies the audited code revision before documentation-only synchronization. Documentation-only synchronization commits are validated separately by their own full PR CI and do not relabel the underlying implementation evidence.

[← Repository README](../README.md)
