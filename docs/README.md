# ƳƤ AI Agent Evaluation & Assurance Framework — Documentation

This documentation is organized by the question a reviewer is trying to answer. The framework keeps **subject identity**, **scenario/adversarial identity**, **evaluation-precondition evidence**, **MCP protocol-fault evidence**, **MCP→agent bridge evidence**, **MCP resource-server authorization evidence**, **MCP OAuth-flow evidence**, **subject evidence**, **deterministic authority**, **persistence integrity**, **session derivation**, and **statistical inference** separate. A statement from one domain never silently becomes proof in another.

## Review paths

| Reviewer goal | Recommended path |
|---|---|
| Architecture / principal engineering | [Architecture](ARCHITECTURE.md) → [Evaluation Model](EVALUATION_MODEL.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [MCP Fault Lab](MCP_LAB.md) → [MCP Remote Authorization](MCP_REMOTE_AUTH.md) → [MCP OAuth Flow](MCP_OAUTH_FLOW.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Session Reports](ASSURANCE_REPORTS.md) → [Metamorphic Testing](METAMORPHIC_TESTING.md) → [Statistical Assurance](STATISTICAL_ASSURANCE.md) → [Limitations](LIMITATIONS.md) |
| QA / AI evaluation engineering | [Evaluation Model](EVALUATION_MODEL.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [MCP Fault Lab](MCP_LAB.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Session Reports](ASSURANCE_REPORTS.md) → [Metamorphic Testing](METAMORPHIC_TESTING.md) → [Statistical Assurance](STATISTICAL_ASSURANCE.md) → [Architecture](ARCHITECTURE.md) |
| Security / red team | [Security](SECURITY.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [MCP Fault Lab](MCP_LAB.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [MCP Remote Authorization](MCP_REMOTE_AUTH.md) → [MCP OAuth Flow](MCP_OAUTH_FLOW.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Limitations](LIMITATIONS.md) |
| Adoption / code review | [Architecture](ARCHITECTURE.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [MCP Fault Lab](MCP_LAB.md) → repository tests → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Security](SECURITY.md) → [Limitations](LIMITATIONS.md) |

## Cross-cutting invariants

```text
Agent claim                 ≠ environment outcome
Tool request                ≠ successful side effect
Approval request            ≠ approval grant
Provider availability       ≠ subject correctness
Model confidence            ≠ grading authority
Attack channel label        ≠ delivery evidence
Environment availability    ≠ environment consumption
MCP fault configuration     ≠ MCP client observation
Cached MCP discovery        ≠ current MCP server contract
Current MCP contract        ≠ cached client discovery
Raw MCP protocol receipt    ≠ agent behavioral assurance
Verified MCP bridge         ≠ automatic PASS
Bearer authentication       ≠ verifier-owned issuer/resource policy
Resource-server success     ≠ OAuth-flow correctness
OAuth-flow success          ≠ agent correctness
Remote-auth receipt         ≠ OAuth-flow receipt
OAuth-flow receipt          ≠ agent behavioral assurance
Delivery receipt            ≠ target-side attestation
Unverified delivery         ≠ behavioral FAIL
Single passing trial        ≠ reliability
Raw percentage delta        ≠ statistically established change
Exact trajectory mismatch   ≠ failure unless the trajectory is contractual
Blocked execution           ≠ behavioral FAIL
Inconclusive evidence       ≠ PASS
Critical safety violation   ≠ compensable score loss
Narrower-looking policy     ≠ proven authority reduction
Stored hash                 ≠ authenticated publisher
Evidence replay             ≠ fresh execution or fresh injection
Serialized gate result      ≠ trusted without recomputation
Assurance report root       ≠ signed attestation
```

The MCP distinction is especially important:

```text
MCPFaultReceipt
    = verified protocol observation

MCPAgentToolResultReceipt
    = verified correlation between one bound MCP tool result
      and one exact OpenAI agent tool call/result

MCPAgentToolErrorRecoveryReceipt
    = verified causal error → retry → recovery relation binding one
      MCP ToolError observation to two distinct OpenAI call identities

Trial PASS / FAIL
    = deterministic subject grading after required delivery evidence closes
```

Two MCP fault families currently have explicit agent bridges: `MCPFaultKind.TOOL_RESULT_POISON` and `MCPFaultKind.TOOL_ERROR`. The other four MCP protocol fault families remain protocol-only with respect to agent behavior.

## Current documentation set

| Document | Primary question |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Where do identity, adversarial derivation, protocol faults, the MCP→agent bridges, resource-server authorization, OAuth-flow assurance, evidence, grading, persistence, reporting, and release authority live? |
| [EVALUATION_MODEL.md](EVALUATION_MODEL.md) | What exactly constitutes a task, trial, outcome, policy violation, and verdict? |
| [ADVERSARIAL_TESTING.md](ADVERSARIAL_TESTING.md) | How are red-team stimuli made deterministic, how is delivery required before grading, and what does an adversarial receipt still not prove? |
| [OPENAI_ADAPTER.md](OPENAI_ADAPTER.md) | How are OpenAI Agents SDK events normalized, how do the dedicated MCP stdio result and ToolError-recovery bridges close, and why does neither provider nor protocol become the oracle? |
| [MCP_LAB.md](MCP_LAB.md) | How are six deterministic MCP faults observed, and which two exact fault families currently have explicit agent bridges? |
| [MCP_REMOTE_AUTH.md](MCP_REMOTE_AUTH.md) | How is the isolated loopback Streamable HTTP resource-server bearer/scope/verifier boundary tested over real TCP? |
| [MCP_OAUTH_FLOW.md](MCP_OAUTH_FLOW.md) | How does the separated two-origin loopback OAuth flow verify discovery, compatibility DCR, PKCE, exact issuer/resource binding, exchange, introspection, and protected MCP use? |
| [EVIDENCE_AND_REPLAY.md](EVIDENCE_AND_REPLAY.md) | How are local evidence records committed, reverified, and replayed without overstating provenance? |
| [ASSURANCE_REPORTS.md](ASSURANCE_REPORTS.md) | How are session conclusions bound and rederived without turning a serialized score or gate label into authority? |
| [METAMORPHIC_TESTING.md](METAMORPHIC_TESTING.md) | Which behavioral relations can be verified without brittle golden outputs? |
| [STATISTICAL_ASSURANCE.md](STATISTICAL_ASSURANCE.md) | How is nondeterministic behavior quantified without overstating certainty? |
| [SECURITY.md](SECURITY.md) | Which threats and trust boundaries are actually controlled, and which claims remain external? |
| [LIMITATIONS.md](LIMITATIONS.md) | What does the repository deliberately not claim yet? |

## Evidence-domain routing guide

Use the evidence contract that matches the boundary actually observed:

| Observed boundary | Evidence contract | What it does **not** imply |
|---|---|---|
| OpenAI local/SDK adversarial injection | `AttackDeliveryReceipt` | target-side attestation or automatic PASS |
| standalone MCP fault observation | `MCPFaultReceipt` | agent consumption or behavior |
| controlled MCP result correlated to exact OpenAI call | `MCPAgentToolResultReceipt` + `PROTOCOL_DELIVERY` | safe behavior or release acceptance |
| controlled MCP ToolError followed by one verified causal retry/recovery | `MCPAgentToolErrorRecoveryReceipt` + `PROTOCOL_DELIVERY` | generic retry correctness, safe behavior, or release acceptance |
| loopback MCP resource authorization | `MCPRemoteAuthReceipt` | OAuth issuance correctness or agent behavior |
| separated loopback OAuth flow | `MCPOAuthFlowReceipt` | production IdP assurance or agent behavior |
| persisted agent trial | `TrialEvidence` | authenticated publisher identity |
| rederived session/release artifact | `AssuranceReport` | signed attestation |

The explicit bridges are important precisely because the framework refuses to infer cross-domain delivery from matching labels or similar payloads.

## MCP agent-bridge scope in one paragraph

The repository implements two deliberately narrow OpenAI-agent → official-MCP-stdio assurance paths. `OpenAIAgentsMCPToolResultAdapter` verifies one `TOOL_RESULT_POISON` call, correlates the exact protocol result to one stable OpenAI call ID and model-visible result, and verifies benign recovery afterward on the same live session. `OpenAIAgentsMCPToolErrorRecoveryAdapter` verifies one real `TOOL_ERROR`, the exact model-visible SDK error output, then requires exactly one same-argument retry with a distinct call ID **after** the first result is visible in normalized chronology; that retry must return the configured benign result on the same live MCP session. Only after the complete error → observed result → retry → recovery relation closes is `MCPAgentToolErrorRecoveryReceipt` emitted as `PROTOCOL_DELIVERY`. Neither bridge establishes behavioral PASS by itself, and neither covers hosted/remote/Internet MCP, live-provider behavior, metadata/cache/schema/identity drift inside an agent trial, generic retry policies, authorization, or target-side attestation.

## Audited implementation checkpoint

Audited merged implementation source checkpoint `d98f9ca1feb1179504cd2181295a73936fd0ae6c`, CI run `33898508697`:

- deterministic core: **349 passed, 27 deselected**;
- branch coverage: **93.79%** against the 90% gate;
- strict mypy: **0 issues across 42 source files**;
- deterministic OpenAI SDK suite, including the controlled MCP stdio bridge: **15/15 passed**;
- deterministic MCP protocol: **6/6 passed**;
- deterministic MCP remote auth: **3/3 passed**;
- deterministic MCP OAuth flow: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest**, Ruff, formatter, Bandit, dependency audit, package integrity, and all **7/7 CI jobs**: green;
- dependency audit reported **no known vulnerabilities**; the project package itself is skipped because it is not published on PyPI.

This checkpoint remains a historical audited merged baseline. The ToolError-recovery capability described above is accepted only after its own exact-head CI, merge, and post-merge `main` verification; documentation does not retroactively relabel the older checkpoint.

[← Repository README](../README.md)
