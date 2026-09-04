<div align="center">

# ƳƤ AI Agent Evaluation & Assurance Framework

### Evidence-Bound TEVV for Agentic Systems

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white&style=flat-square)](pyproject.toml)
[![MIT License](https://img.shields.io/badge/License-MIT-2ea44f?style=flat-square)](LICENSE)
[![Architecture](https://img.shields.io/badge/Architecture-Evidence--Bound-111827?style=flat-square)](docs/ARCHITECTURE.md)

**A provider-neutral quality-engineering framework for evaluating autonomous agents by observable outcomes, side effects, authority boundaries, adversarial conditions, verified evaluation preconditions, protocol state, authorization behavior, reliability, and reproducible evidence—not by persuasive final prose.**

[Documentation](docs/README.md) · [Architecture](docs/ARCHITECTURE.md) · [Evaluation Model](docs/EVALUATION_MODEL.md) · [Adversarial Testing](docs/ADVERSARIAL_TESTING.md) · [MCP Fault Lab](docs/MCP_LAB.md) · [MCP Remote Auth](docs/MCP_REMOTE_AUTH.md) · [MCP OAuth Flow](docs/MCP_OAUTH_FLOW.md) · [Evidence & Replay](docs/EVIDENCE_AND_REPLAY.md) · [Session Reports](docs/ASSURANCE_REPORTS.md) · [OpenAI Adapter](docs/OPENAI_ADAPTER.md) · [Statistics](docs/STATISTICAL_ASSURANCE.md) · [Security](docs/SECURITY.md) · [Limitations](docs/LIMITATIONS.md)

</div>

---

> [!IMPORTANT]
> **The agent is the subject, not the oracle.** Final prose is not task completion. A tool call is not a successful side effect. An attack label is not proof of delivery. A configured environment value is not proof of consumption. Cached MCP discovery is not current server truth. A raw MCP receipt is not proof that an agent consumed the condition. A bearer challenge is not proof of correct issuer policy. Resource-server success is not OAuth-flow correctness. OAuth-flow success is not agent correctness. Missing or invalid evidence is never silently promoted to PASS.

## Engineering thesis

```text
Agents act.
Attacks perturb.
Protocols carry untrusted content and state.
Authorization constrains access.
Controlled injectors establish evaluation preconditions.
Observers record.
Bridges bind cross-boundary delivery only when identities, chronology, and observations agree.
State proves.
Policy constrains.
Evidence persists.
Replay regrades.
Statistics quantify reliability.
Release gates decide.
Reports rederive.
```

Agentic systems call tools, mutate state, consume resources, retain session history, transfer work across agents, read runtime dependencies, interact with protocol servers, cross authorization boundaries, request approvals, retry failures, and operate nondeterministically. Evaluating only a final message cannot distinguish completed work from a plausible claim that work occurred.

This framework treats the **complete agent system** as the subject under test: model, instructions, orchestration, tools, authority, memory policy, adapter, and application revision. Provider-specific execution becomes normalized evidence; deterministic state, policy, protocol observations, and release authority remain outside the agent and outside model confidence.

## Core invariants

| Invariant | Consequence |
|---|---|
| **Outcome before rhetoric** | independently observed state outranks the agent's claim about state |
| **Safety is non-compensatory** | a critical authorization violation cannot be averaged away |
| **Unknown is not green** | blocked execution and missing evidence remain explicit uncertainty |
| **Bad ≠ unknown** | resolved subject failure is distinct from evaluator/runtime inability to judge |
| **Identity is canonical** | subject, scenario, attack, MCP fault, resource-server auth policy, OAuth-flow policy, evidence, and report identities bind behavior-bearing material |
| **Adversarial derivation preserves authority** | an attack cannot grant tools, broaden resources, remove approval, reroute handoffs, or redefine success |
| **Attack delivery is a precondition** | adversarial behavior is graded only after one exact matching receipt verifies |
| **Availability ≠ consumption** | an environment value that subject code never reads is not a delivered attack |
| **MCP configuration ≠ observation** | an MCP fault exists as protocol evidence only after the official client observes the required representation or relation |
| **Cached discovery ≠ server truth** | a still-fresh `tools/list` result does not prove the current server schema or registry identity |
| **Discovery ≠ call validation** | server-side `tools/call` validity is independently observed rather than inferred from cached metadata |
| **Raw protocol receipt ≠ agent behavior** | `MCPFaultReceipt` alone does not establish agent consumption, resistance, or correctness |
| **Retry label ≠ causal retry** | a second identical tool call is credited as recovery only when evidence orders the first result before the second request |
| **Bridge closure ≠ grading authority** | a verified MCP→agent bridge establishes a delivery precondition; deterministic subject oracles still decide PASS/FAIL |
| **Bearer authentication ≠ issuer/resource policy** | SDK bearer handling and verifier-owned identity/resource binding are credited to their actual enforcement components |
| **Resource-server success ≠ OAuth-flow correctness** | a 401/403/authorized-call matrix does not prove registration, PKCE, issuance, or introspection |
| **OAuth-flow success ≠ agent correctness** | a valid OAuth path proves protocol/control-plane behavior, not safe or correct agent behavior |
| **Evaluator failure ≠ subject failure** | unavailable/unverifiable controlled delivery becomes `EVALUATION_ERROR / BLOCKED` |
| **Provider failure ≠ evaluator failure** | provider/runtime exceptions remain `RUNTIME_ERROR / BLOCKED` |
| **Evidence is reverified** | persisted bytes must pass schema, identity, hash, and semantic-root checks before reuse |
| **Replay is historical** | replay regrades recorded evidence; it does not pretend to re-execute the subject |
| **Nondeterminism is measured** | repeated trials produce uncertainty bounds instead of one-shot certainty |
| **Release authority is deterministic** | critical state/safety evidence cannot be overridden by future semantic graders |

---

## What is executable today

The deterministic core requires no model credentials. The executable surface is intentionally separated into four lanes so one green boundary cannot silently upgrade another:

1. **Provider-neutral core** — contracts, evidence, persistence, replay, deterministic oracles, statistics, metamorphic assurance, reporting, minimization, and release gates.
2. **OpenAI Agents SDK tier** — the real SDK runner exercised with `agents.testing.ScriptedModel`, with no provider API call, across seven scoped local/SDK adversarial channels.
3. **MCP protocol/control-plane laboratories** — the six-fault official-client protocol lab, real loopback resource-server authorization lab, and separated two-origin OAuth authorization-code/PKCE/introspection lab.
4. **OpenAI↔MCP delivery bridges** — three deliberately narrow official-stdio paths: one `TOOL_RESULT_POISON` result bridge, one causal `TOOL_ERROR` → same-argument retry → benign recovery bridge, and one host-refreshed `TOOL_SCHEMA_DRIFT` v1-rejection → refreshed-v2 → corrected-call bridge. Each has its own integrity-bound receipt and ordered `PROTOCOL_DELIVERY` evidence.

The bridges are not a blanket promotion of the MCP laboratories. `TOOL_METADATA_POISON`, stale-cache, and identity-drift remain protocol-only with respect to agent behavior, and the remote-auth/OAuth receipts remain separate control-plane evidence. The schema-drift bridge does **not** claim model-initiated refresh or automatic `tools/list_changed` handling: the controlled harness owns the live schema swap, the evaluator/host adapter owns one cache invalidation, the official MCP session supplies the first fresh post-invalidation discovery, and the agent is credited only for its corrected call after v2 becomes model-visible.

### Evaluation and assurance core

| Surface | Implemented behavior |
|---|---|
| **Subject contract** | canonical SHA-256 identity across provider/model, instructions, tools, policy, memory policy, adapter, and application revision |
| **Scenario contract** | versioned objective, initial state, required/forbidden outcomes, classification, tags, and fail-closed authority |
| **Adversarial fixtures/campaigns** | content-addressed attacks and canonical campaigns bound to one exact base scenario |
| **Attack delivery** | exactly-one receipt verification binding scenario, attack, channel, injection point, and payload digest before adversarial grading |
| **Evidence** | immutable ordered events plus a domain-separated evidence root |
| **Local evidence store** | strict manifest, bounded reads, symlink rejection, no-clobber publication, payload hash, semantic-root verification |
| **Replay** | exact trial/subject/scenario historical regrading including delivery-receipt revalidation |
| **Outcome oracle** | independently validates required and forbidden terminal state |
| **Policy oracle** | fail-closed tools/resources, call-bound approvals, tool/handoff budgets, and explicit policy violations |
| **Reliability** | resolved success rate, Wilson interval, empirical `pass@k`/`pass^k`; unresolved attempts stay separate |
| **Differential evaluation** | exact paired McNemar/binomial comparison over resolved trials |
| **Assurance reports** | self-validating artifacts binding evidence roots, oracle snapshots, reliability, release policy, gate result, and report root |
| **Release gate** | non-compensatory critical-safety rules plus explicit `ACCEPT`, `REJECT`, and `INCONCLUSIVE` semantics |
| **Metamorphic assurance** | state-projection invariance and authority-monotonicity relations without golden prose |
| **Failure minimization** | bounded deterministic counterexample reduction requiring failure reproduction |

### Seven scoped OpenAI adversarial channels

`OpenAIAgentsAdapter` implements every generic `AttackChannel` category at a narrow tested SDK/local boundary:

| Channel | Concrete implementation |
|---|---|
| **`USER_INPUT`** | exact canonical attack JSON as the second ordered `Runner.run` user message |
| **local `TOOL_RESULT`** | first matching local `FunctionTool` result replaced with exact canonical attack JSON; receipt bound to SDK call ID |
| **local `TOOL_METADATA`** | copied local `FunctionTool.description` replaced with exact canonical attack JSON while name/schema/callback remain fixed |
| **session-history `MEMORY`** | fresh per-trial SDK `Session` returns exact canonical attack JSON as prior history |
| **inline-file `RESOURCE`** | structured SDK `input_file.file_data` contains exact canonical attack JSON |
| **native `HANDOFF`** | first actual SDK handoff receives exact canonical attack JSON in transferred context while destination is preserved |
| **runtime-context `ENVIRONMENT`** | first matching local tool sees exact canonical attack JSON for one targeted `RunContextWrapper.context` key; receipt exists only after actual value consumption |

Seven generic channels implemented does **not** mean universal production interception. [Limitations](docs/LIMITATIONS.md) is authoritative.

### Deterministic MCP protocol fault laboratory

`MCPFaultLab` uses official `mcp==2.1.1` and protocol revision `2026-07-28`. Each probe builds a fresh real `MCPServer`, connects an official `Client`, and emits `MCPFaultReceipt` only after the complete fault-specific public-client observation contract is satisfied.

| Fault | Verified protocol boundary |
|---|---|
| **tool metadata poison** | canonical fault JSON observed as target description returned by `tools/list` |
| **tool result poison** | canonical fault JSON observed as first `tools/call` result text; second call recovers to benign data |
| **tool error** | canonical fault JSON preserved inside SDK-generated model-visible `ToolError`; second call recovers |
| **tool-list stale cache** | target initially observed under positive private TTL, removed from live registry, still returned from cache, then absent after refresh |
| **tool-schema drift** | cached old schema survives server replacement; old arguments fail under live validation; refresh exposes new schema; new arguments succeed |
| **tool-identity drift** | cached old name survives rename; stale-name call fails; refresh exposes replacement; replacement call succeeds |

The discovery-state relation is explicit:

```text
cached discovery
      ≠
current server contract
      ≠
call-time validity
      ≠
refreshed discovery
```

`MCPFaultReceipt` binds controlled fault-material and exact canonical-observation SHA-256 values. The laboratory itself remains a protocol evidence layer, not an agent verdict engine.

### Verified OpenAI↔MCP bridges

#### `TOOL_RESULT_POISON`: exact same-call delivery

`OpenAIAgentsMCPToolResultAdapter` closes one cross-boundary claim: the first controlled `TOOL_RESULT_POISON` result returned by a fresh official MCP stdio server is the same logical tool result consumed by the deterministic OpenAI agent call identified by one exact SDK call ID.

```text
MCPFaultSpec(kind=tool_result_poison)
        ↓
fresh official MCPServerStdio subprocess
        ↓ negotiated MCP 2026-07-28
first target tools/call result
        ↓
MCPFaultReceipt
        ↓ same agent run + exact target call identity
OpenAI ToolCallOutputItem
        ↓ exact output equivalence
MCPAgentToolResultReceipt
        ↓
TOOL_REQUEST → PROTOCOL_DELIVERY → TOOL_RESULT
        ↓
deterministic policy/outcome oracles
```

The behavioral run makes exactly one target call. Recovery is checked afterward with the same arguments through the same still-connected MCP session, so recovery evidence cannot become a second agent-visible benign result. Missing target consumption, multiple target calls, protocol-version mismatch, malformed protocol evidence, result mismatch, or failed recovery becomes `EVALUATION_ERROR / BLOCKED`.

#### `TOOL_ERROR`: causal retry and recovery

`OpenAIAgentsMCPToolErrorRecoveryAdapter` closes a different relation: the controlled MCP target returns a real first-call `ToolError`, the pinned Agents SDK exposes the bound error as the model-visible result, and the agent then issues exactly one same-argument retry that recovers on the same MCP session.

```text
MCPFaultSpec(kind=tool_error)
        ↓
fresh official MCPServerStdio subprocess
        ↓ negotiated MCP 2026-07-28
TOOL_REQUEST(error_call_id)
        ↓
real MCP ToolError → MCPFaultReceipt
        ↓ exact model-visible error equivalence
TOOL_RESULT(error_call_id)
        ↓ strict evidence chronology
TOOL_REQUEST(retry_call_id; same canonical arguments)
        ↓ same live MCP session
TOOL_RESULT(retry_call_id; exact benign recovery)
        ↓
MCPAgentToolErrorRecoveryReceipt
        ↓
PROTOCOL_DELIVERY
        ↓
deterministic policy/outcome oracles
```

The two OpenAI call IDs must be stable and distinct. The normalized chronology must satisfy `request₁ < result₁ < request₂ < result₂`; two calls pre-issued before the error result are not credited as a retry. Missing retry, extra target calls, changed arguments, ambiguous identities, protocol drift, malformed evidence, wrong error representation, wrong recovery, or non-causal ordering fails closed as `EVALUATION_ERROR / BLOCKED`.

#### `TOOL_SCHEMA_DRIFT`: host-refreshed contract adaptation

`OpenAIAgentsMCPToolSchemaDriftAdapter` closes a third, intentionally narrower relation: the model first receives the bound v1 tool contract and selects a v1-shaped call; the controlled harness then swaps the live MCP target to v2 before that call reaches real MCP validation; the stale v1 arguments are rejected; the host invalidates its cached tool list once; the next fresh discovery exposes v2; and only then may a distinct corrected v2-shaped agent call qualify as adaptation.

```text
model receives v1 tools/list contract
        ↓
TOOL_REQUEST(stale_call_id; v1 arguments)
        ↓
evaluator-only hidden server-side schema swap
        ↓ same live MCP session
real v2 validation rejects stale v1 arguments
        ↓
TOOL_RESULT(stale_call_id; exact model-visible rejection)
        ↓
host invalidates MCP tool cache once
        ↓
first fresh post-invalidation tools/list exposes v2
        ↓
model receives v2 contract + stale rejection
        ↓
TOOL_REQUEST(recovery_call_id; exact bound v2 arguments)
        ↓ same live MCP session
TOOL_RESULT(recovery_call_id; exact replacement result)
        ↓
MCPAgentToolSchemaDriftReceipt
        ↓
PROTOCOL_DELIVERY
        ↓
deterministic policy/outcome oracles
```

The receipt binds the initial/cached/refreshed schema digests, stale/recovery argument digests, protocol and model-visible rejection/recovery observations, distinct OpenAI call IDs, and the strict chronology `initial-list < swap < stale-call < cache-invalidation < refreshed-list < recovery-call`. The evaluator control tool is filtered from the model-visible tool set. Later SDK turns may reuse the already-refreshed v2 cache; the assurance claim is one host invalidation and the first fresh v2 discovery before recovery, not “exactly one later `list_tools()` call.” Missing or extra target calls, recovery before refreshed discovery, wrong schemas/arguments/results, protocol drift, receipt tampering, or ambiguous evidence fails closed.

None of these three bridges establishes safe behavior merely because delivery closes. They do not generalize to MCP metadata poison, generic stale-cache behavior, identity drift, arbitrary JSON Schema migrations, tool rename semantics, hosted MCP, remote/Internet MCP, live-provider behavior, generic retry/backoff/idempotency, authorization, or target-side attestation. The schema-drift path specifically does not claim model-initiated refresh or automatic `tools/list_changed` handling. A raw `MCPFaultReceipt` still does not create a trial verdict by itself.

### Loopback MCP resource-server authorization laboratory

`MCPRemoteAuthLab` tests an isolated resource-server trust boundary over a pre-bound `127.0.0.1` TCP socket, Uvicorn, MCP Streamable HTTP, and the official client transport.

| Condition | Required observation |
|---|---|
| missing bearer | HTTP 401 |
| unknown bearer | HTTP 401 |
| expired bearer | HTTP 401 |
| wrong issuer | deterministic verifier rejects → HTTP 401 |
| wrong resource | deterministic verifier rejects → HTTP 401 |
| missing required scope | authenticated request → HTTP 403 |
| valid scoped bearer | protected `tools/list` and `tools/call` succeed |
| protected-resource discovery | RFC 9728 metadata reports exact resource, issuer, and required scopes |

Control ownership is explicit: issuer/resource binding belongs to the deterministic lab verifier; bearer recognition/expiry and required-scope enforcement are credited to the MCP SDK middleware; protected-resource metadata is observed over HTTP. `MCPRemoteAuthReceipt` excludes actual deterministic bearer values.

### Separated MCP OAuth authorization-code laboratory

`MCPOAuthFlowLab` closes the next trust boundary across **two independent loopback origins** using the official MCP `OAuthClientProvider`.

It verifies protected-resource and authorization-server discovery, compatibility Dynamic Client Registration fallback, OAuth state, PKCE `S256`, exact RFC 9207 issuer validation, RFC 8707 resource binding, authorization-code exchange, opaque token issuance, authenticated HTTP introspection, protected MCP use, and stored-authorization reuse on reconnect.

The authorization code, access token, and introspection secret are not serialized in `MCPOAuthFlowProbeResult` or `MCPOAuthFlowReceipt`. Dynamic Client Registration is deliberately described as a compatibility fallback; this repository does not implement Client ID Metadata Documents.

---

## Architecture at a glance

```mermaid
flowchart LR
    accTitle: Evidence-bound agent, MCP protocol, MCP-to-agent delivery, resource authorization, and OAuth-flow assurance architecture
    accDescr: Canonical subject and scenario contracts drive agent execution and deterministic grading. Raw MCP protocol, remote-auth, and OAuth observations remain separate evidence. Three controlled MCP stdio paths cross into agent evidence only after exact bridge verification.

    S[Canonical subject]
    C[Scenario + authority]
    A[Agent adapter]
    U[Agent system under test]
    E[Ordered agent evidence]
    P[Policy oracle]
    O[Outcome oracle]
    T[Trial verdict]
    G[Release gate]

    MF[MCP fault spec]
    MP[MCP protocol observation]
    MR[MCP fault receipt]
    B[MCP agent bridge verifier]
    BR[MCP agent bridge receipt]

    AP[MCP remote-auth policy]
    AR[MCP remote-auth receipt]
    OP[MCP OAuth-flow policy]
    OR[MCP OAuth-flow receipt]

    S --> A
    C --> A
    A --> U
    U --> A
    A --> E
    E --> P
    E --> O
    P --> T
    O --> T
    T --> G

    MF --> MP
    MP --> MR
    MR --> B
    B --> BR
    BR --> E

    AP --> AR
    OP --> OR
```

The controlled `TOOL_RESULT_POISON`, `TOOL_ERROR`, and host-refreshed `TOOL_SCHEMA_DRIFT` stdio paths can cross `MR → B → BR → E`, each through its own receipt contract. The other three MCP fault families and both authorization laboratories terminate in their own evidence domains.

## Trial and release semantics

| Result | Meaning |
|---|---|
| `PASS` | evaluation preconditions closed and deterministic subject oracles passed |
| `FAIL` | verified evidence proves a deterministic subject requirement was violated |
| `BLOCKED` | execution or an evaluation precondition could not produce enough evidence to judge behavior |
| `ACCEPT` | release evidence satisfies configured requirements |
| `REJECT` | verified behavioral/safety evidence violates release policy |
| `INCONCLUSIVE` | release evidence is insufficient; uncertainty is not converted to acceptance |

A target tool that never executes, an injected runtime key that is never consumed, a missing handoff, an unclosed MCP→agent bridge, invalid delivery evidence, a non-causal recovery sequence, or an unavailable provider can block evaluation without being mislabeled as a product defect. A successful raw MCP fault, resource-auth, or OAuth-flow receipt by itself is not a trial verdict.

---

## Quick start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

agent-evals doctor
pytest
```

Deterministic OpenAI SDK integration, including all three controlled MCP stdio bridges:

```bash
python -m pip install -e '.[dev,openai,mcp]'
pytest -m openai \
  tests/integration/test_openai_adapter.py \
  tests/integration/test_openai_resource_adapter.py \
  tests/integration/test_openai_environment_adapter.py \
  tests/integration/test_openai_mcp_tool_result_adapter.py \
  tests/integration/test_openai_mcp_tool_error_recovery_adapter.py \
  tests/integration/test_openai_mcp_tool_schema_drift_adapter.py \
  tests/integration/test_openai_mcp_tool_schema_drift_contract.py
```

Deterministic MCP protocol laboratory:

```bash
pytest -m mcp tests/integration/test_mcp_fault_lab.py
```

Deterministic loopback MCP resource-server authorization:

```bash
pytest -m mcp_remote tests/integration/test_mcp_remote_auth.py
```

Deterministic separated MCP OAuth flow:

```bash
pytest -m mcp_oauth tests/integration/test_mcp_oauth_flow.py
```

The OpenAI integration is pinned to `openai-agents==0.22.0`. The MCP integration is pinned to `mcp==2.1.1`.

---

## Selected evidence contracts

### OpenAI local `TOOL_RESULT`

```text
source          = injector:openai-agents:tool-result
injection_point = openai-agents:FunctionTool:<tool>:call:<call_id>:output

TOOL_REQUEST → ATTACK_DELIVERY → TOOL_RESULT
```

The original function is deliberately not executed on the injected first call. This is controlled local result replacement; it is distinct from the dedicated MCP stdio bridges.

### OpenAI runtime-context `ENVIRONMENT`

```text
source          = injector:openai-agents:environment-runtime-context
injection_point = openai-agents:FunctionTool:<tool>:call:<call_id>:RunContextWrapper.context:<key>

TOOL_REQUEST → ATTACK_DELIVERY → TOOL_RESULT
```

Delivery exists only after subject code actually reads the targeted value. Configuration or tool execution alone is insufficient.

### MCP protocol faults

```text
MCPFaultSpec
    ↓ fresh official client/server observation
content or discovery-state relation
    ↓
MCPFaultReceipt
```

### MCP→agent `TOOL_RESULT_POISON`

```text
MCPFaultReceipt
    + exact OpenAI target tool request/result call ID
    + exact model-visible output equivalence
    + same-session benign recovery
        ↓
MCPAgentToolResultReceipt
        ↓
PROTOCOL_DELIVERY
```

### MCP→agent `TOOL_ERROR` recovery

```text
MCPFaultReceipt
    + exact model-visible ToolError observation
    + distinct first/retry OpenAI call IDs
    + same canonical arguments
    + request₁ < result₁ < request₂ < result₂
    + exact same-session benign recovery
        ↓
MCPAgentToolErrorRecoveryReceipt
        ↓
PROTOCOL_DELIVERY
```

### MCP→agent `TOOL_SCHEMA_DRIFT` adaptation

```text
MCPFaultReceipt
    + v1 initial/cached schema digests
    + real stale-call rejection after hidden live v2 swap
    + one host cache invalidation
    + first fresh post-invalidation v2 schema digest
    + exact model-visible rejection
    + distinct stale/recovery OpenAI call IDs
    + exact bound v1/v2 argument digests
    + exact same-session replacement result
    + initial-list < swap < stale-call < invalidation < refreshed-list < recovery-call
        ↓
MCPAgentToolSchemaDriftReceipt
        ↓
PROTOCOL_DELIVERY
```

### MCP resource-server authorization

```text
MCPRemoteAuthPolicy
    ↓ streamable-http-loopback
401 / 403 challenge matrix
+ RFC 9728 metadata
+ authorized tools/list + tools/call
    ↓
MCPRemoteAuthReceipt
```

### MCP OAuth flow

```text
MCPOAuthFlowPolicy
    ↓ separate loopback AS / RS
PRM + AS metadata
→ DCR compatibility fallback
→ state + PKCE S256 + resource
→ exact authorization-response iss
→ code exchange
→ authenticated introspection
→ protected MCP use
→ stored-authorization reuse
    ↓
MCPOAuthFlowReceipt
```

The protocol, agent-bridge, remote-auth, and OAuth evidence domains are intentionally distinct. The public remote-auth and OAuth probe-result envelopes are diagnostic models; their embedded receipt identities are validated, but independently modified outer diagnostic fields are not cryptographically re-bound to those receipts.

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
│       ├── adversarial/
│       ├── assurance/
│       ├── contracts/
│       ├── evidence/
│       ├── gates/
│       ├── mcp/
│       ├── metamorphic/
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

## Verified implementation baseline

Implementation source checkpoint `d98f9ca1feb1179504cd2181295a73936fd0ae6c`, protected-main CI run `33898508697`:

- deterministic core: **349 passed, 27 deselected**;
- branch coverage: **93.79%** against the 90% gate;
- strict mypy: **0 issues across 42 source files**;
- deterministic OpenAI SDK suite, including MCP stdio bridge coverage: **15/15 passed**;
- deterministic MCP protocol suite: **6/6 passed**;
- deterministic MCP remote-auth suite: **3/3 passed**;
- deterministic MCP OAuth-flow suite: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest** quality jobs: green;
- Ruff lint + formatter: green;
- Bandit: green;
- dependency audit: **no known vulnerabilities found**; the project package itself is skipped because it is not published on PyPI;
- package integrity: green;
- all **7/7 CI jobs**: green.

This baseline remains the historical audited merged implementation revision. Capabilities added after that checkpoint, including the ToolError-recovery and host-refreshed schema-drift bridges described above, are accepted only after their own exact-head CI, merge, and post-merge `main` verification; documentation does not retroactively relabel the older checkpoint.

---

## Documentation review path

1. [Architecture](docs/ARCHITECTURE.md)
2. [Evaluation Model](docs/EVALUATION_MODEL.md)
3. [Adversarial Testing](docs/ADVERSARIAL_TESTING.md)
4. [MCP Protocol Fault Laboratory](docs/MCP_LAB.md)
5. [MCP Remote Authorization](docs/MCP_REMOTE_AUTH.md)
6. [MCP OAuth Flow Laboratory](docs/MCP_OAUTH_FLOW.md)
7. [OpenAI Adapter](docs/OPENAI_ADAPTER.md)
8. [Evidence & Replay](docs/EVIDENCE_AND_REPLAY.md)
9. [Session Assurance Reports](docs/ASSURANCE_REPORTS.md)
10. [Statistical Assurance](docs/STATISTICAL_ASSURANCE.md)
11. [Security](docs/SECURITY.md)
12. [Limitations and Non-Claims](docs/LIMITATIONS.md)
