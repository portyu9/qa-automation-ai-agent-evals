# ƳƤ AI Agent Evaluation & Assurance Framework — Documentation

This documentation is organized by the question a reviewer is trying to answer. The framework keeps **subject identity**, **scenario/adversarial identity**, **approval-intent evidence**, **side-effect observation evidence**, **evaluation-precondition evidence**, **retrieval-delivery evidence**, **MCP protocol-fault evidence**, **MCP→agent bridge evidence**, **MCP resource-server authorization evidence**, **MCP OAuth-flow evidence**, **subject evidence**, **deterministic authority**, **calibrated semantic-judgment evidence**, **persistence integrity**, **session derivation**, and **statistical inference** separate. A statement from one domain never silently becomes proof in another.

## Review paths

| Reviewer goal | Recommended path |
|---|---|
| Architecture / principal engineering | [Architecture](ARCHITECTURE.md) → [Evaluation Model](EVALUATION_MODEL.md) → [Calibrated Semantic Judging](SEMANTIC_JUDGING.md) → [Handoff Authority](HANDOFF_AUTHORITY.md) → [Native HITL Approval Intent](APPROVAL_INTENT.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [MCP Fault Lab](MCP_LAB.md) → [MCP Identity Drift](MCP_IDENTITY_DRIFT.md) → [MCP Remote Authorization](MCP_REMOTE_AUTH.md) → [MCP OAuth Flow](MCP_OAUTH_FLOW.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Session Reports](ASSURANCE_REPORTS.md) → [Metamorphic Testing](METAMORPHIC_TESTING.md) → [Statistical Assurance](STATISTICAL_ASSURANCE.md) → [Limitations](LIMITATIONS.md) |
| QA / AI evaluation engineering | [Evaluation Model](EVALUATION_MODEL.md) → [Calibrated Semantic Judging](SEMANTIC_JUDGING.md) → [Handoff Authority](HANDOFF_AUTHORITY.md) → [Native HITL Approval Intent](APPROVAL_INTENT.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [MCP Fault Lab](MCP_LAB.md) → [MCP Identity Drift](MCP_IDENTITY_DRIFT.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Session Reports](ASSURANCE_REPORTS.md) → [Metamorphic Testing](METAMORPHIC_TESTING.md) → [Statistical Assurance](STATISTICAL_ASSURANCE.md) → [Architecture](ARCHITECTURE.md) |
| Security / red team | [Security](SECURITY.md) → [Handoff Authority](HANDOFF_AUTHORITY.md) → [Native HITL Approval Intent](APPROVAL_INTENT.md) → [Adversarial Testing](ADVERSARIAL_TESTING.md) → [MCP Fault Lab](MCP_LAB.md) → [MCP Identity Drift](MCP_IDENTITY_DRIFT.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [MCP Remote Authorization](MCP_REMOTE_AUTH.md) → [MCP OAuth Flow](MCP_OAUTH_FLOW.md) → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Limitations](LIMITATIONS.md) |
| Adoption / code review | [Architecture](ARCHITECTURE.md) → [Handoff Authority](HANDOFF_AUTHORITY.md) → [Native HITL Approval Intent](APPROVAL_INTENT.md) → [OpenAI Adapter](OPENAI_ADAPTER.md) → [MCP Fault Lab](MCP_LAB.md) → [MCP Identity Drift](MCP_IDENTITY_DRIFT.md) → repository tests → [Evidence & Replay](EVIDENCE_AND_REPLAY.md) → [Security](SECURITY.md) → [Limitations](LIMITATIONS.md) |

## Cross-cutting invariants

```text
Agent claim                   ≠ environment outcome
Tool request                  ≠ successful side effect
Approval request              ≠ approval grant
Approval decision receipt     ≠ human identity or external authorization
Duplicate-looking tool result ≠ proof of idempotent physical effect
Legacy approval               ≠ stronger native HITL approval decision
Provider availability         ≠ subject correctness
Model confidence              ≠ grading authority
Semantic PASS                 ≠ external state, authorization, or safety proof
Semantic calibration          ≠ universal judge correctness
Semantic ABSTAIN              ≠ PASS or FAIL
Attack channel label          ≠ delivery evidence
Retrieval contract            ≠ model-visible retrieval delivery
Controlled poison in top-k    ≠ behavioral PASS or FAIL
Environment availability      ≠ environment consumption
Handoff observation           ≠ delegated authority
Raw handoff count             ≠ accepted authority epoch
Same handoff depth            ≠ same authority path
Root authority                ≠ child authority after handoff
SDK agent name                ≠ cryptographic/global identity
MCP fault configuration       ≠ MCP client observation
Cached MCP discovery          ≠ current MCP server contract
Current MCP contract          ≠ cached client discovery
Cache invalidation            ≠ model-owned refresh
Refreshed discovery           ≠ correct agent adaptation
Replacement tool name         ≠ cryptographic/global tool identity
Raw MCP protocol receipt      ≠ agent behavioral assurance
Verified MCP bridge           ≠ automatic PASS
Bearer authentication         ≠ verifier-owned issuer/resource policy
Resource-server success       ≠ OAuth-flow correctness
OAuth-flow success            ≠ agent correctness
Remote-auth receipt           ≠ OAuth-flow receipt
OAuth-flow receipt            ≠ agent behavioral assurance
Delivery receipt              ≠ target-side attestation
Unverified delivery           ≠ behavioral FAIL
Single passing trial          ≠ reliability
Raw percentage delta          ≠ statistically established change
Exact trajectory mismatch     ≠ failure unless the trajectory is contractual
Blocked execution             ≠ behavioral FAIL
Inconclusive evidence         ≠ PASS
Critical safety violation     ≠ compensable score loss
Narrower-looking policy       ≠ proven authority reduction
Stored hash                   ≠ authenticated publisher
Evidence replay               ≠ fresh execution or fresh injection
Serialized gate result        ≠ trusted without recomputation
Assurance report root         ≠ signed attestation
```

For native handoffs, the distinction is deliberately scenario-owned rather than receipt-owned:

```text
OpenAI SDK run-item agent identity
    = run-local provenance for who generated one observed item

HandoffAuthorityGrant
    = scenario-owned directed authorization for one source → target transition

PolicyOracle
    = deterministic authority engine that proves path-local attenuation
      and grades delegated tools/resources/approvals/budgets
```

No new handoff receipt is required because handoff and tool events already inhabit the same normalized subject-evidence domain. The specialized adapter supplies provenance; the scenario contract and deterministic oracle remain the authority.

Native HITL approval introduces a different relation because a decision must bind a pending interruption to its exact continuation:

```text
ApprovalIntentSpec
    = scenario-owned exact target + approve/reject intent

ApprovalIntentReceipt
    = integrity-bound relation over scenario, decision, agent, tool,
      call identity, canonical argument digest, exact resource,
      accepted authority epoch/path, and approval-request sequence

APPROVAL_DECISION
    = evaluator-owned evidence for that exact native interruption

PolicyOracle
    = still the deterministic authority engine; a decision cannot
      legitimize an otherwise unauthorized pending action
```

The receipt binds accepted authority **path identity**, not just depth. Two valid handoff paths reaching the same agent at the same epoch remain different approval contexts. Legacy call-scoped or persistent `APPROVAL` evidence cannot substitute for `APPROVAL_DECISION` when `ApprovalIntentSpec` is configured.

The MCP distinction is especially important:

```text
MCPFaultReceipt
    = verified protocol observation

MCPAgentToolMetadataReceipt
    = exact verified discovery-description/schema → model-visible-definition relation

MCPAgentToolResultReceipt
    = exact verified protocol result → one OpenAI call/result relation

MCPAgentToolErrorRecoveryReceipt
    = exact causal error → retry → recovery relation with distinct calls

MCPAgentToolSchemaDriftReceipt
    = exact host-refreshed v1 rejection → v2 discovery → corrected-call relation

MCPAgentToolIdentityDriftReceipt
    = exact host-refreshed original-name rejection → replacement-only discovery/model
      visibility → exact replacement-name call relation

Trial PASS / FAIL
    = deterministic subject grading after required bridge evidence closes
```

Five MCP fault families have explicit agent bridges: `TOOL_METADATA_POISON`, `TOOL_RESULT_POISON`, `TOOL_ERROR`, `TOOL_SCHEMA_DRIFT`, and `TOOL_IDENTITY_DRIFT`. `TOOL_LIST_STALE_CACHE` remains protocol-only with respect to agent behavior. Metadata delivery closes at exact model-visible target definition; schema/identity adaptation closes only after the complete host-refreshed multi-step relation. None establishes attention, safe behavior, or automatic PASS.

For both drift bridges the refresh is deliberately **host-owned**: the harness owns the live mutation, the evaluator/host adapter owns cache invalidation, the official MCP session owns refreshed discovery, and the model is credited only for changing its next call after the replacement contract/identity becomes visible. Neither path claims model-initiated refresh or automatic `tools/list_changed` handling.

## Current documentation set

| Document | Primary question |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Where do identity, adversarial derivation, protocol faults, five MCP→agent bridges, authorization/OAuth, evidence, grading, persistence, reporting, and release authority live? |
| [EVALUATION_MODEL.md](EVALUATION_MODEL.md) | What exactly constitutes a task, trial, outcome, policy violation, semantic judgment, and verdict? |
| [SEMANTIC_JUDGING.md](SEMANTIC_JUDGING.md) | How are rubrics, judge profiles, calibration, bounded inputs, semantic receipts, deterministic precedence, replay, and OpenAI SDK judge behavior kept evidence-bound? |
| [HANDOFF_AUTHORITY.md](HANDOFF_AUTHORITY.md) | How are native OpenAI handoffs authorized as a scenario-bound directed graph, how is run-item agent provenance bound, and how is authority forced to attenuate across each observed hop? |
| [APPROVAL_INTENT.md](APPROVAL_INTENT.md) | How is one native OpenAI HITL approve/reject decision bound to the exact pending invocation, accepted delegated-authority path, same-run continuation, and deterministic failure semantics? |
| [SIDE_EFFECT_IDEMPOTENCY.md](SIDE_EFFECT_IDEMPOTENCY.md) | How are two exact attempts to one logical operation bound to independently observed effect digests, reverified on replay, and graded without suppressing bad subject behavior? |
| [ADVERSARIAL_TESTING.md](ADVERSARIAL_TESTING.md) | How are red-team stimuli made deterministic, how is delivery required before grading, and what does an adversarial receipt still not prove? |
| [RETRIEVAL_ASSURANCE.md](RETRIEVAL_ASSURANCE.md) | How are corpus/query/ranker/poison identity, deterministic ranking, exact model-visible retrieval delivery, replay, and production-RAG non-claims kept separate? |
| [OPENAI_ADAPTER.md](OPENAI_ADAPTER.md) | How are OpenAI SDK events normalized and how do native handoff/HITL/idempotency plus metadata/result/ToolError/schema/identity MCP bridges and the calibrated semantic judge preserve exact trust boundaries? |
| [MCP_LAB.md](MCP_LAB.md) | How are six deterministic MCP faults observed, and which five exact fault families have explicit agent bridges? |
| [MCP_IDENTITY_DRIFT.md](MCP_IDENTITY_DRIFT.md) | How is one live old→replacement MCP tool rename bound across protocol discovery, real stale rejection, host refresh, exact model-visible identity transition, replacement call, receipt, replay, and non-claims? |
| [MCP_REMOTE_AUTH.md](MCP_REMOTE_AUTH.md) | How is the isolated loopback Streamable HTTP resource-server bearer/scope/verifier boundary tested over real TCP? |
| [MCP_OAUTH_FLOW.md](MCP_OAUTH_FLOW.md) | How does the separated two-origin loopback OAuth flow verify discovery, compatibility DCR, PKCE, exact issuer/resource binding, exchange, introspection, and protected MCP use? |
| [EVIDENCE_AND_REPLAY.md](EVIDENCE_AND_REPLAY.md) | How are local evidence records committed, reverified, and replayed without overstating provenance, including typed metadata/result/error/schema/identity `PROTOCOL_DELIVERY` revalidation? |
| [ASSURANCE_REPORTS.md](ASSURANCE_REPORTS.md) | How does AssuranceReport v2 keep deterministic oracle authority separate from optional semantic receipts while rederiving trial verdicts, reliability, and release gates? |
| [METAMORPHIC_TESTING.md](METAMORPHIC_TESTING.md) | Which behavioral relations can be verified without brittle golden outputs? |
| [STATISTICAL_ASSURANCE.md](STATISTICAL_ASSURANCE.md) | How is nondeterministic behavior quantified without overstating certainty? |
| [SECURITY.md](SECURITY.md) | Which threats and trust boundaries are actually controlled, and which claims remain external? |
| [LIMITATIONS.md](LIMITATIONS.md) | What does the repository deliberately not claim yet? |

## Evidence-domain routing guide

Use the evidence contract that matches the boundary actually observed:

| Observed boundary | Evidence contract | What it does **not** imply |
|---|---|---|
| native handoff path with delegated authority | `TrialEvidence` + exact scenario `AuthorityPolicy` / `HandoffAuthorityGrant` graph | cryptographic agent identity, provider-side enforcement, or distributed delegation |
| native OpenAI HITL interruption and exact approve/reject continuation | `ApprovalIntentSpec` + `ApprovalIntentReceipt` / `APPROVAL_DECISION` + normalized continuation evidence | human identity, enterprise approval attestation, production IAM, or target-side authorization |
| two exact local OpenAI tool attempts to one logical operation | `SideEffectIdempotencySpec` + `SideEffectIdempotencyReceipt` / `SIDE_EFFECT_OBSERVATION` + exact request/result chronology | distributed exactly-once execution, durable deduplication, concurrency/crash safety, or external-target enforcement |
| OpenAI local/SDK adversarial injection | `AttackDeliveryReceipt` | target-side attestation or automatic PASS |
| evaluator-owned deterministic retrieval ranking and exact model-visible delivery | `RetrievalContractSpec` + `RetrievalDeliveryReceipt` / `RETRIEVAL_DELIVERY` | hosted vector-search correctness, citation correctness, production RAG lifecycle, or behavioral PASS |
| standalone MCP fault observation | `MCPFaultReceipt` | agent consumption or behavior |
| exact MCP metadata discovery bound to model-visible target definition | `MCPAgentToolMetadataReceipt` + `PROTOCOL_DELIVERY` | model attention, safe behavior, or release acceptance |
| controlled MCP result correlated to exact OpenAI call | `MCPAgentToolResultReceipt` + `PROTOCOL_DELIVERY` | safe behavior or release acceptance |
| controlled MCP ToolError followed by one verified causal retry/recovery | `MCPAgentToolErrorRecoveryReceipt` + `PROTOCOL_DELIVERY` | generic retry correctness, safe behavior, or release acceptance |
| controlled live schema replacement followed by host refresh and exact corrected agent call | `MCPAgentToolSchemaDriftReceipt` + `PROTOCOL_DELIVERY` | model-owned refresh, arbitrary schema migration, safe behavior, or release acceptance |
| controlled live identity replacement followed by host refresh, exact replacement model visibility, and exact replacement-name call | `MCPAgentToolIdentityDriftReceipt` + `PROTOCOL_DELIVERY` | model-owned refresh, arbitrary rename migration, global tool identity, safe behavior, or release acceptance |
| loopback MCP resource authorization | `MCPRemoteAuthReceipt` | OAuth issuance correctness or agent behavior |
| separated loopback OAuth flow | `MCPOAuthFlowReceipt` | production IdP assurance or agent behavior |
| persisted agent trial with semantic judgment | terminal `SEMANTIC_JUDGMENT` + `SemanticJudgmentReceipt` inside `TrialEvidence` | deterministic state/safety proof, current-model liveness, or authority to rescue deterministic failure |
| persisted agent trial | `TrialEvidence` | authenticated publisher identity |
| rederived session/release artifact | `AssuranceReport` | signed attestation |

The explicit relations are important precisely because the framework refuses to infer cross-domain truth from matching labels, similar payloads, or a decision event with insufficient invocation identity.

## Native handoff authority in one paragraph

`OpenAIAgentsHandoffAuthorityAdapter` is a stronger, explicit OpenAI adapter boundary for scenarios that declare native handoff authority. It binds the configured root to the supplied SDK Agent before execution, uses public pinned-SDK run-item agent identity to attribute normalized tool request/result/approval-request evidence, verifies request/result ownership for each completed call, and checks handoff-item generating-agent identity against the SDK handoff source. The scenario-owned directed graph then drives `PolicyOracle`: every observed source→target transition must have one exact grant, child tools/resources/budgets may only stay equal or narrow, inherited approvals cannot be removed for retained tools, and a failed transition never advances the active agent. Agent names are run-local SDK evidence identities, not cryptographic or globally unique principals. See [Native Handoff Authority](HANDOFF_AUTHORITY.md).

## Native HITL approval intent in one paragraph

`OpenAIAgentsHITLApprovalAdapter` exercises the pinned SDK's real `ToolApprovalItem` → `RunState.approve(...)` / `RunState.reject(...)` → same-`RunState` resume path under `agents.testing.ScriptedModel`. `ApprovalIntentReceipt` binds the scenario decision to the exact run-local agent, tool, stable call ID, canonical finite-JSON argument digest, normalized resource, accepted authority epoch, exact accepted handoff-path hash, and approval-request sequence. Approval requires exactly one matching executable request/result after resume; clean rejection requires explicit matching rejection-result evidence and no protected executable request. If a rejected invocation nevertheless executes, that resolved evidence is preserved for critical policy `FAIL`. Legacy call-scoped and persistent approvals cannot downgrade the stronger requirement. See [Native HITL Approval Intent](APPROVAL_INTENT.md).

## Side-effect idempotency in one paragraph

`OpenAIAgentsSideEffectIdempotencyAdapter` wraps a copied local `FunctionTool` only to sample evaluator-owned effect state immediately before and after the real subject callback. Both callbacks execute, their output/exception behavior is preserved, and two distinct OpenAI call identities plus strict equal arguments must close one continuous two-attempt receipt. `TrialRunner` revalidates the receipt before `SideEffectIdempotencyOracle` can grade it. A verified second physical mutation is critical `FAIL`; missing or contradictory observation/provenance is `BLOCKED`. Replay rechecks the historical receipt without rerunning either callback or the effect reader. See [Side-Effect Idempotency Assurance](SIDE_EFFECT_IDEMPOTENCY.md).

## MCP agent-bridge scope in one paragraph

The repository implements **five deliberately narrow official-MCP-stdio ↔ OpenAI-agent assurance paths**. `OpenAIAgentsMCPToolMetadataAdapter` closes exact discovery-to-model-visible metadata exposure without requiring a call. `OpenAIAgentsMCPToolResultAdapter` correlates one controlled result to one stable OpenAI call/result and checks post-run same-session recovery. `OpenAIAgentsMCPToolErrorRecoveryAdapter` requires a real model-visible error followed causally by one same-argument retry with a distinct call ID and same-session recovery. `OpenAIAgentsMCPToolSchemaDriftAdapter` verifies model-visible v1, hidden live v2 replacement, real stale rejection, host invalidation, fresh v2 discovery, then one exact corrected v2 call. `OpenAIAgentsMCPToolIdentityDriftAdapter` verifies model-visible original identity, hidden live old→replacement mutation, real stale-name rejection, host invalidation, replacement-only protocol/model visibility, then one exact replacement-name call. Multi-step bridges emit `PROTOCOL_DELIVERY` only after their full relation closes. None establishes behavioral PASS by itself, and none covers hosted/remote/Internet MCP, live-provider behavior, generic schema/rename migration, model-owned refresh, generic retry/cache policy, authorization, or target-side attestation.

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

This checkpoint remains a historical audited merged baseline. Capabilities added after it—including metadata delivery, ToolError recovery, host-refreshed schema drift, host-refreshed identity drift, native handoff authority, native HITL approval intent, retrieval assurance, side-effect idempotency, and calibrated semantic judging—require their own exact-head CI, merge, and post-merge `main` verification; documentation does not retroactively relabel the older checkpoint.

[← Repository README](../README.md)
