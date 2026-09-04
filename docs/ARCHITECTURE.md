# Architecture

## Purpose

The framework evaluates an **agent system**, not a detached model response. The evaluated subject includes provider/model configuration, application revision, instructions, tool schemas, authority policy, memory policy, adapter identity, and adapter version.

Architecture starts with identity and evidence, then derives conclusions. It never starts with a score and works backward to justify it.

## Trust model

```text
Trusted evaluation control plane
├── subject/scenario contracts
├── deterministic adversarial derivation
├── controlled OpenAI attack injectors
│   ├── USER_INPUT
│   ├── local FunctionTool TOOL_RESULT
│   ├── local FunctionTool TOOL_METADATA description
│   ├── per-trial Session-history MEMORY
│   ├── structured inline-file RESOURCE
│   ├── first-native-handoff context
│   └── targeted runtime-context ENVIRONMENT
├── attack-delivery verifier
├── deterministic MCP protocol fault laboratory
│   ├── tools/list description poison
│   ├── first tools/call result poison
│   ├── first tools/call model-visible ToolError
│   ├── private tools/list stale cache after server-side removal
│   ├── tool-schema drift across cached discovery / call validation / refresh
│   └── tool-identity drift across cached discovery / stale lookup / refresh
├── controlled OpenAI↔MCP tool-result bridge
│   ├── fresh official MCPServerStdio subprocess per trial
│   ├── negotiated MCP 2026-07-28
│   ├── exactly one behavioral target call
│   ├── MCPFaultReceipt for first controlled result
│   ├── exact OpenAI request/result call-ID pairing
│   ├── MCPAgentToolResultReceipt
│   └── same-session benign recovery after behavioral run
├── MCP resource-server authorization laboratory
│   ├── pre-bound loopback TCP + Uvicorn + Streamable HTTP
│   ├── verifier-owned issuer/resource binding
│   ├── SDK bearer authentication + expiry checks
│   ├── SDK required-scope enforcement
│   └── RFC 9728 protected-resource metadata
├── separated MCP OAuth-flow laboratory
│   ├── independent loopback authorization-server and resource-server origins
│   ├── protected-resource + authorization-server metadata discovery
│   ├── compatibility Dynamic Client Registration fallback
│   ├── authorization code + state + PKCE S256
│   ├── exact RFC 9207 issuer validation
│   ├── exact RFC 8707 resource binding
│   ├── token exchange
│   ├── authenticated HTTP token introspection
│   ├── protected MCP use through introspection-backed verification
│   └── stored-authorization reuse on reconnect
├── evidence normalization and persistence verification
├── exact-identity replay
├── deterministic policy and outcome oracles
├── statistical assurance
├── assurance-report verification
└── release gate

Untrusted / evaluated subject
└── agent runtime + model + orchestration + tools + memory + resources + handoffs + app context

External / not presently attested
└── live model providers, hosted/external MCP servers, Internet transport,
    third-party/production authorization servers and IdPs, production memory/retrieval,
    target systems, proxies, TLS infrastructure, cloud/IAM, and production fault injectors
```

External content can become evidence or adversarial stimulus. It does not become control-plane authority merely because a model, tool, MCP server, resource, session, handoff, application context, HTTP endpoint, OAuth server, authorization middleware, or external service produced it.

## Identity domains

`SubjectFingerprint` binds provider, model, application revision, instructions, tool schema, policy, memory policy, and adapter identity/version. `EvaluationScenario` binds scenario ID/revision, objective, initial state, authority, required/forbidden outcomes, classification, and tags.

`AttackFixture` and `AdversarialCampaign` add deterministic adversarial identity without changing base authority or redefining success.

The protocol/control-plane identities remain intentionally distinct:

```text
AttackFixture          → AttackDeliveryReceipt
MCPFaultSpec           → MCPFaultReceipt
MCPRemoteAuthPolicy    → MCPRemoteAuthReceipt
MCPOAuthFlowPolicy     → MCPOAuthFlowReceipt
```

A fifth receipt, `MCPAgentToolResultReceipt`, is a **bridge receipt**, not a new fault identity. It binds an already verified MCP tool-result receipt to one exact agent scenario, tool name, call ID, and model-visible output.

These identities answer different questions and do not inherit authority from one another.

### Protocol-fault identity

`MCPFaultSpec` binds schema, fault ID/revision, `MCPFaultKind`, original tool name, and canonical finite JSON payload. The six kinds are:

```text
tool_metadata_poison
tool_result_poison
tool_error
tool_list_stale_cache
tool_schema_drift
tool_identity_drift
```

Only `tool_result_poison` currently has an agent bridge.

### Resource-server authorization identity

`MCPRemoteAuthPolicy` separately binds lab ID/revision, issuer URL, MCP resource path, canonical required scopes, and protected tool name. This layer begins with deterministic verifier token records and tests resource-server enforcement.

### OAuth-flow identity

`MCPOAuthFlowPolicy` binds lab ID/revision, resource path, canonical required scopes, protected tool name, OAuth client name, and redirect path. Transient ports and credentials are excluded from policy identity.

`MCPOAuthFlowReceipt` exists only after discovery, compatible registration fallback, PKCE authorization, exact issuer/resource validation, token exchange, authenticated introspection, protected MCP use, and reconnect reuse all close.

A protocol fault does not silently become a remote-auth policy; resource-server authorization does not prove OAuth issuance; OAuth-flow success does not become an `AttackFixture` or agent verdict.

## Delivery is an evaluation precondition

An adversarial agent scenario is behaviorally gradeable only after the applicable controlled delivery contract closes.

For ordinary `AttackFixture` channels:

```text
unverified ATTACK_DELIVERY                    → BLOCKED
verified delivery + deterministic violation   → FAIL
verified delivery + deterministic closure     → PASS
```

For the dedicated MCP tool-result bridge:

```text
raw MCPFaultReceipt only                      → protocol evidence only
verified MCPAgentToolResultReceipt missing    → BLOCKED
verified bridge + deterministic violation     → FAIL
verified bridge + deterministic closure       → PASS
```

Neither receipt type is grading authority. Both are evaluator-owned integrity evidence used to establish preconditions before deterministic subject grading.

## Seven OpenAI local/SDK channel boundaries

`OpenAIAgentsAdapter` implements all seven generic `AttackChannel` categories at scoped SDK/local boundaries:

- `USER_INPUT` — exact canonical fixture JSON as second ordered `Runner.run` user message;
- local `TOOL_RESULT` — first matching copied local `FunctionTool` result replacement, call-ID-bound;
- description-level `TOOL_METADATA` — copied local `FunctionTool.description` only;
- session-history `MEMORY` — fresh per-trial SDK `Session` prior user item;
- inline-file `RESOURCE` — exact canonical JSON as structured `input_file.file_data`;
- native `HANDOFF` — exact canonical JSON appended to first actual SDK handoff context while preserving destination;
- runtime-context `ENVIRONMENT` — exact canonical JSON returned for one exact string key only during the first matching local `FunctionTool` invocation, with delivery created only on actual value consumption.

These seven categories are not universal production interception claims. The local result injector does not intercept MCP tools; the dedicated MCP bridge is a separate adapter and evidence contract.

## MCP protocol-fault boundary

`MCPFaultLab` is provider-neutral protocol test infrastructure. It uses official `mcp==2.1.1`, creates a fresh real `MCPServer`, and connects an official `Client` in `2026-07-28` mode.

```text
content-addressed MCPFaultSpec
        ↓
fresh MCPServer
        ↓
official Client / protocol 2026-07-28
        ↓
content observation or protocol-state relation
        ↓
MCPFaultReceipt
```

Three direct content observations are closed: target description poison, first-call result poison, and SDK-wrapped model-visible `ToolError`.

Three relational discovery observations are closed: stale removal cache, schema drift, and identity drift.

The governing relation is:

```text
cached discovery ≠ current server contract ≠ call-time validity ≠ refreshed discovery
```

`MCPFaultReceipt` binds fault-material and canonical-observation digests. Direct byte-equivalent content may produce equal digests; SDK transformation and stateful relations intentionally do not.

A raw `MCPFaultReceipt` is not OpenAI `ATTACK_DELIVERY` and does not derive agent `PASS`/`FAIL`.

## OpenAI↔MCP tool-result bridge boundary

`OpenAIAgentsMCPToolResultAdapter` closes one additional relation for `TOOL_RESULT_POISON` without weakening the protocol/agent separation.

```text
MCPFaultSpec(tool_result_poison)
        ↓
fresh MCPServerStdio subprocess
        ↓
connected official MCP session
        ↓ protocol_version == 2026-07-28
OpenAI Agent clone with exactly one controlled MCP server
        ↓
exactly one behavioral target tool call
        ↓
first MCP result observation → MCPFaultReceipt
        ↓
OpenAI normalized TOOL_REQUEST(call_id)
        +
matching TOOL_RESULT(call_id, output)
        ↓ output matches protocol-observed result
MCPAgentToolResultReceipt
        ↓
PROTOCOL_DELIVERY ordered before TOOL_RESULT
        ↓
same-session same-argument benign recovery
        ↓
TrialEvidence → policy/outcome oracles
```

### Why the bridge is separate

Protocol observation and agent observation have different identities and failure modes. The bridge therefore refuses to infer one from the other.

It requires:

- fresh controlled MCP stdio boundary per trial;
- no preconfigured MCP servers on the supplied base agent;
- no local target-name collision;
- unprefixed target naming for unambiguous correlation;
- negotiated protocol version from the connected MCP session;
- exactly one target behavioral call;
- exactly one normalized agent request and one matching result;
- stable non-empty agent call ID;
- exact model-visible output equivalence;
- successful benign recovery through the same live session after the agent run.

Missing or ambiguous evidence becomes `AdapterPreconditionError` and therefore `EVALUATION_ERROR / BLOCKED`.

### Recovery placement matters

Recovery happens **after** the behavioral run. If the agent received both poisoned and benign results, the evaluator could no longer prove which result drove behavior. Post-run recovery verifies one-shot isolation without changing the transcript being graded.

### SDK representation is not protocol identity

The pinned Agents SDK may serialize one logical text result differently across internal `ToolCallOutputItem.output` and Responses replay input. The bridge compares the logical public output represented by the normalized event rather than pretending incidental wire spellings are the same object.

## MCP resource-server Streamable HTTP authorization boundary

`MCPRemoteAuthLab` is intentionally separate from both protocol faults and the agent bridge.

```text
MCPRemoteAuthPolicy
        ↓
pre-bound 127.0.0.1 TCP socket
        ↓
Uvicorn + MCP Streamable HTTP app
        ↓
resource-server auth middleware
        ↓
401/403 + RFC 9728 metadata + authorized MCP calls
        ↓
MCPRemoteAuthReceipt
```

Enforcement ownership is explicit:

- deterministic `TokenVerifier` — exact issuer/resource binding;
- MCP SDK authentication middleware — bearer recognition, verifier acceptance, expiry;
- MCP SDK authorization middleware — required scopes;
- MCP SDK protected-resource route — RFC 9728 metadata;
- official client — protected `tools/list` and `tools/call` over loopback TCP.

This layer proves resource-server enforcement, not token issuance or agent behavior.

## Separated MCP OAuth-flow boundary

`MCPOAuthFlowLab` hosts authorization server and resource server on different loopback origins and uses the official MCP `OAuthClientProvider`.

```text
MCPOAuthFlowPolicy
        ↓
protected-resource metadata
        ↓
authorization-server metadata
        ↓
DCR compatibility fallback when needed
        ↓
state + PKCE S256 + exact resource/scopes
        ↓
exact RFC 9207 authorization-response issuer
        ↓
authorization-code exchange
        ↓
opaque access token
        ↓
resource server → authenticated HTTP introspection → authorization server
        ↓
issuer/resource/scope/expiry/subject validation
        ↓
protected tools/list + tools/call
        ↓
stored-authorization reuse on reconnect
        ↓
MCPOAuthFlowReceipt
```

The resource server does not directly consult the authorization server's in-memory token table. DCR is compatibility behavior, not a claim of modern CIMD support. Authorization code, access token, and introspection secret are omitted from serialized evidence.

## Evidence chronology and separation

OpenAI local channel ordering includes:

```text
TOOL_RESULT:  TOOL_REQUEST → ATTACK_DELIVERY → TOOL_RESULT
ENVIRONMENT:  TOOL_REQUEST → ATTACK_DELIVERY → TOOL_RESULT
HANDOFF:      HANDOFF → ATTACK_DELIVERY
```

The MCP result bridge uses a distinct chronology:

```text
MCP RESULT:   TOOL_REQUEST → PROTOCOL_DELIVERY → TOOL_RESULT
```

The event kind is deliberately different. It communicates that protocol evidence crossed into agent evidence through an explicit bridge rather than through an `AttackFixture` injector.

Other MCP fault receipts, remote-auth receipts, and OAuth-flow receipts remain outside agent trial chronology.

This preserves the following non-implications:

```text
MCP configuration       ⇏ client observation
client observation      ⇏ agent consumption
raw protocol receipt    ⇏ agent behavior
bridge closure          ⇏ automatic PASS
bearer authorization    ⇏ OAuth issuance correctness
OAuth-flow completion   ⇏ agent correctness
protocol/control receipt ⇏ release acceptance
```

## Authority remains fail-closed

`AuthorityPolicy` controls allowed/forbidden tools, approval-required tools, resource prefixes, and tool/handoff budgets. Unknown authority is not permission.

Adversarial derivation cannot broaden authority. A bridge cannot broaden authority either: it binds delivery identity, not policy permission.

Critical policy failure remains non-compensatory.

## Adapter and runtime failure separation

`AgentAdapter` executes and normalizes; it does not grade itself.

`AdapterPreconditionError` represents evaluator-controlled prerequisites that cannot be satisfied. `TrialRunner` converts it to `EVALUATION_ERROR / BLOCKED`. Provider/SDK execution exceptions remain `RUNTIME_ERROR / BLOCKED`.

Neither is rewritten as subject `FAIL`.

The standalone MCP laboratories return their own evidence-domain results rather than `TrialEvidence`. The dedicated bridge is the exception only because it explicitly verifies cross-domain identity and emits `PROTOCOL_DELIVERY` inside the agent trial.

## Persistence, replay, statistics, and release authority

`LocalEvidenceStore` revalidates persisted bytes, manifests, hashes, identities, schema, semantic roots, symlink/file constraints, and no-clobber publication behavior before reuse. Local hashes do not authenticate a hostile writer who can coherently replace all controlled bytes.

`EvidenceReplayAdapter` performs exact-identity historical regrading. It does not re-run the agent, provider, tool, injector, MCP stdio bridge, MCP labs, or authorization flow and cannot establish fresh delivery.

Repeated trials feed `ReliabilityReport`; resolved behavior remains separate from blocked evaluator/runtime uncertainty. `AssuranceReport` binds evidence roots, deterministic oracle snapshots, reliability, release policy, gate output, and report root.

`ReleaseGate` preserves non-compensatory critical safety evidence. Insufficient evidence produces `INCONCLUSIVE`, not acceptance. Raw MCP protocol/auth/OAuth success is not release-gate authority.

## Current boundary

The framework currently provides deterministic contracts, content-addressed adversarial scenarios, evidence-bound OpenAI delivery verification across seven scoped channel categories, a six-fault official-SDK MCP protocol laboratory, one exact MCP `TOOL_RESULT_POISON` → OpenAI-agent stdio delivery bridge, a real-loopback resource-server authorization laboratory, a separated two-origin OAuth authorization-code/PKCE/introspection laboratory, integrity-verified local persistence, exact historical replay, deterministic policy/outcome oracles, metamorphic relations, repeated-trial statistics, assurance reports, release gating, and bounded failure minimization.

Implementation source checkpoint `d98f9ca1feb1179504cd2181295a73936fd0ae6c`, protected-main CI run `33898508697`:

- deterministic core: **349 passed, 27 deselected**;
- branch coverage: **93.79%** against the 90% gate;
- strict mypy: **0 issues across 42 source files**;
- deterministic OpenAI SDK suite, including MCP stdio bridge: **15/15 passed**;
- deterministic MCP protocol: **6/6 passed**;
- deterministic MCP remote auth: **3/3 passed**;
- deterministic MCP OAuth flow: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest**, Ruff, formatter, Bandit, dependency audit, package integrity, and all **7/7 CI jobs**: green;
- dependency audit: no known vulnerabilities found; the project package itself is skipped because it is not published on PyPI.

Still outside the executable claim boundary are credentialed live-provider assurance; agent-through-MCP grading for the other five MCP fault families; hosted/remote/Internet MCP fidelity; generic stdio/proxy/TLS/DNS/transport-chaos assurance; production IdP/JWT/JWKS/federation; CIMD/enterprise-managed authorization; DPoP/mTLS; refresh/revocation/replay lifecycle; public/shared-cache behavior beyond the exact implemented relations; arbitrary schema/registry mutations; MCP resource/prompt/task fault families; production memory/retrieval; infrastructure chaos; semantic/model graders; signed provenance; and formal non-inferiority testing.

[← Documentation hub](README.md)
