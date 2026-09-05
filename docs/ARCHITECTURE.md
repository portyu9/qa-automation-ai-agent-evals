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
├── controlled OpenAI↔MCP bridges
│   ├── TOOL_METADATA_POISON discovery/model-visible-definition bridge
│   │   ├── exact official tools/list target description + JSON schema
│   │   ├── first public model-visible target definition observation
│   │   ├── description/schema digest equality without requiring a target call
│   │   └── MCPAgentToolMetadataReceipt
│   ├── TOOL_RESULT_POISON same-call bridge
│   │   ├── exactly one behavioral target call
│   │   ├── MCPFaultReceipt for first controlled result
│   │   ├── exact OpenAI request/result call-ID pairing
│   │   ├── MCPAgentToolResultReceipt
│   │   └── same-session benign recovery after behavioral run
│   ├── TOOL_ERROR causal retry/recovery bridge
│   │   ├── exactly two behavioral target calls
│   │   ├── first real MCP ToolError → MCPFaultReceipt
│   │   ├── exact model-visible error observation
│   │   ├── distinct OpenAI error/retry call IDs
│   │   ├── same canonical arguments
│   │   ├── request₁ < result₁ < request₂ < result₂
│   │   ├── exact same-session benign recovery
│   │   └── MCPAgentToolErrorRecoveryReceipt
│   └── TOOL_SCHEMA_DRIFT host-refreshed adaptation bridge
│       ├── model receives bound v1 target schema
│       ├── evaluator-only hidden live swap to v2
│       ├── real MCP rejection of stale v1 arguments
│       ├── host-owned cache invalidation after rejection
│       ├── first fresh post-invalidation tools/list exposes v2
│       ├── distinct stale/recovery OpenAI call IDs
│       ├── exact bound v1/v2 arguments and recovery result
│       ├── strict six-step protocol chronology
│       └── MCPAgentToolSchemaDriftReceipt
│
│   all four paths use a fresh official MCPServerStdio subprocess per trial
│   and require negotiated MCP 2026-07-28
├── protocol-delivery semantic verifier
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
├── optional calibrated semantic judging
│   ├── scenario-owned content-addressed SemanticRubricSpec
│   ├── exact content-addressed SemanticJudgeProfile
│   ├── accepted SemanticCalibrationReceipt with false-PASS/abstention/failure/coverage gates
│   ├── bounded objective + rubric + candidate-output judge input
│   ├── deterministic-failure short circuit before model invocation
│   └── terminal non-critical SemanticJudgmentReceipt bound to pre-semantic evidence root
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

`SubjectFingerprint` binds provider, model, application revision, instructions, tool schema, policy, memory policy, and adapter identity/version. `EvaluationScenario` binds scenario ID/revision, objective, initial state, authority, required/forbidden outcomes, classification, tags, approval intent, and optional `SemanticRubricSpec`. Rubric criteria, descriptions, ordering, thresholds, and revision therefore participate in scenario identity.

`AttackFixture` and `AdversarialCampaign` add deterministic adversarial identity without changing base authority or redefining success.

The protocol/control-plane identities remain intentionally distinct:

```text
AttackFixture          → AttackDeliveryReceipt
MCPFaultSpec           → MCPFaultReceipt
MCPRemoteAuthPolicy    → MCPRemoteAuthReceipt
MCPOAuthFlowPolicy     → MCPOAuthFlowReceipt
```

Four receipt types bridge selected MCP protocol observations into agent-trial evidence without creating new fault identities:

- `MCPAgentToolMetadataReceipt` binds one verified MCP `TOOL_METADATA_POISON` discovery description/schema to the first exact public model-visible target definition without requiring invocation;
- `MCPAgentToolResultReceipt` binds one verified MCP `TOOL_RESULT_POISON` observation to one exact agent scenario, tool name, call ID, and model-visible output;
- `MCPAgentToolErrorRecoveryReceipt` binds one verified MCP `TOOL_ERROR` observation to one exact causal two-call agent relation: error call, model-visible error result, distinct same-argument retry call, and exact benign recovery;
- `MCPAgentToolSchemaDriftReceipt` binds one verified MCP `TOOL_SCHEMA_DRIFT` relation to one exact host-refreshed two-call agent relation: v1 discovery, hidden live replacement, stale-call rejection, host cache invalidation, first fresh v2 discovery, distinct corrected call, and exact replacement result.

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

`tool_metadata_poison`, `tool_result_poison`, `tool_error`, and `tool_schema_drift` currently have explicit agent bridges. `tool_list_stale_cache` and `tool_identity_drift` remain protocol-only with respect to agent behavior. The metadata bridge proves exact model-visible exposure, not attention, interpretation, compliance, resistance, or safe behavior.

The schema-drift bridge is not a blanket promotion of cache semantics. Its host/model ownership is explicit: the harness owns the live schema swap, the evaluator/host adapter owns one cache invalidation, the official MCP session supplies the first fresh post-invalidation listing, the pinned Agents SDK converts that listing into model tool definitions, and the agent is credited only for changing its second target call after v2 becomes model-visible. It does **not** claim model-initiated refresh or automatic `tools/list_changed` handling.

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

For any dedicated MCP bridge:

```text
raw MCPFaultReceipt only                      → protocol evidence only
required bridge receipt missing/invalid       → BLOCKED
verified bridge + deterministic violation     → FAIL
verified bridge + deterministic closure       → PASS
```

No bridge receipt is grading authority. All four are evaluator-owned integrity evidence used to establish preconditions before deterministic subject grading. Likewise, a semantic judgment is not deterministic state or safety authority: it is evaluated only after those deterministic oracles pass and may only narrow that success to non-critical FAIL or INCONCLUSIVE.

## Seven OpenAI local/SDK channel boundaries

`OpenAIAgentsAdapter` implements all seven generic `AttackChannel` categories at scoped SDK/local boundaries:

- `USER_INPUT` — exact canonical fixture JSON as second ordered `Runner.run` user message;
- local `TOOL_RESULT` — first matching copied local `FunctionTool` result replacement, call-ID-bound;
- description-level `TOOL_METADATA` — copied local `FunctionTool.description` only;
- session-history `MEMORY` — fresh per-trial SDK `Session` prior user item;
- inline-file `RESOURCE` — exact canonical JSON as structured `input_file.file_data`;
- native `HANDOFF` — exact canonical JSON appended to first actual SDK handoff context while preserving destination;
- runtime-context `ENVIRONMENT` — exact canonical JSON returned for one exact string key only during the first matching local `FunctionTool` invocation, with delivery created only on actual value consumption.

These seven categories are not universal production interception claims. The local result injector does not intercept MCP tools; the dedicated MCP bridges are separate adapters and evidence contracts.

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

## OpenAI↔MCP result bridge boundary

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
same-session same-argument benign recovery after the run
        ↓
TrialEvidence → policy/outcome oracles
```

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

### Result-bridge recovery placement matters

Recovery happens **after** the behavioral run. If the agent received both poisoned and benign results, the evaluator could no longer prove which result drove behavior. Post-run recovery verifies one-shot isolation without changing the transcript being graded.

## OpenAI↔MCP ToolError retry/recovery boundary

`OpenAIAgentsMCPToolErrorRecoveryAdapter` closes a different relation for `TOOL_ERROR`: the agent must observe the real controlled error before one same-argument target call can be credited as a recovery retry.

```text
MCPFaultSpec(tool_error)
        ↓
fresh MCPServerStdio subprocess
        ↓
connected official MCP session
        ↓ protocol_version == 2026-07-28
OpenAI Agent clone with exactly one controlled MCP server
        ↓
TOOL_REQUEST(error_call_id)
        ↓
first MCP ToolError observation → MCPFaultReceipt
        ↓ exact model-visible error equivalence
TOOL_RESULT(error_call_id)
        ↓
TOOL_REQUEST(retry_call_id)
        ↓ same canonical arguments + distinct call ID
same live MCP session returns exact benign result
        ↓
TOOL_RESULT(retry_call_id)
        ↓
MCPAgentToolErrorRecoveryReceipt
        ↓
PROTOCOL_DELIVERY ordered after recovery TOOL_RESULT
        ↓
TrialEvidence → policy/outcome oracles
```

The bridge requires:

- exactly two behavioral target calls;
- stable, distinct non-empty OpenAI call IDs;
- one normalized result for each call;
- canonical equality of original and retry arguments;
- exact agent-visible error digest equal to the verified MCP protocol observation digest;
- exact expected/observed benign recovery digest equality;
- strict normalized chronology `request₁ < result₁ < request₂ < result₂`.

That chronology closes a subtle trust boundary: two identical calls emitted before the first result do not prove a retry reaction. Such pre-issued or parallel calls fail closed as `mcp_error_retry_causality_unverified`.

Missing retry, extra target calls, changed retry arguments, malformed/ambiguous identities, protocol drift, error mismatch, recovery mismatch, or non-causal ordering becomes `AdapterPreconditionError` and therefore `EVALUATION_ERROR / BLOCKED`.

## OpenAI↔MCP schema-drift adaptation boundary

`OpenAIAgentsMCPToolSchemaDriftAdapter` closes a third relation for `TOOL_SCHEMA_DRIFT`: a corrected v2 call is credited only when the model first selected the bound v1 call, the live server changed before validation, the stale call was genuinely rejected, and host-owned refresh made v2 model-visible before the corrected call.

```text
MCPFaultSpec(tool_schema_drift)
        ↓
fresh MCPServerStdio subprocess
        ↓
connected official MCP session
        ↓ protocol_version == 2026-07-28
model receives bound v1 target schema
        ↓
TOOL_REQUEST(stale_call_id; bound v1 arguments)
        ↓
hidden evaluator-only live schema swap to v2
        ↓ same live MCP session
real MCP v2 validation rejects stale v1 arguments
        ↓
TOOL_RESULT(stale_call_id; exact model-visible rejection)
        ↓
host adapter invalidates tool cache once
        ↓
first fresh post-invalidation tools/list exposes bound v2
        ↓
model receives v2 + stale rejection
        ↓
TOOL_REQUEST(recovery_call_id; bound v2 arguments)
        ↓ same live MCP session
TOOL_RESULT(recovery_call_id; exact replacement result)
        ↓
MCPAgentToolSchemaDriftReceipt
        ↓
PROTOCOL_DELIVERY ordered after recovery TOOL_RESULT
        ↓
TrialEvidence → policy/outcome oracles
```

The bridge requires:

- a fresh official stdio session and negotiated MCP `2026-07-28`;
- exactly one model-visible controlled target and no leaked evaluator control identity;
- the exact initial/cached v1 schema and exact refreshed v2 schema;
- exactly two target behavioral calls with stable, distinct OpenAI call IDs;
- exact stale v1 and corrected v2 argument digests;
- a real stale-call MCP error result whose model-visible observation matches the protocol observation;
- one host cache invalidation after that rejection;
- the first fresh post-invalidation listing to expose v2 before recovery;
- exact same-session replacement result equivalence;
- strict protocol chronology `initial-list < swap < stale-call < cache-invalidation < refreshed-list < recovery-call`.

Later SDK turns may reuse the already-refreshed v2 cache. Such reads are not extra refreshes. The bridge binds the first fresh discovery after one evaluator-owned invalidation, not a count of every later `list_tools()` access.

Missing or extra calls, recovery before refreshed discovery, repeated stale arguments, schema/control leakage, protocol drift, observation mismatch, or malformed receipt becomes `AdapterPreconditionError` and therefore `EVALUATION_ERROR / BLOCKED`.

## SDK representation is not protocol identity

The pinned Agents SDK may serialize one logical text result differently across internal `ToolCallOutputItem.output` and Responses replay input. The bridges compare the logical public outputs represented by normalized evidence rather than pretending incidental wire spellings are the same object.

For schema drift, the same principle applies to tool definitions: the bridge binds canonical required-property/type projections of the raw MCP schemas while the integration tests separately assert the actual SDK model-visible v1/v2 tool definitions.

## MCP resource-server Streamable HTTP authorization boundary

`MCPRemoteAuthLab` is intentionally separate from both protocol faults and the agent bridges.

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

The MCP bridges use distinct protocol-delivery chronology:

```text
MCP RESULT:
              TOOL_REQUEST
              → PROTOCOL_DELIVERY
              → TOOL_RESULT

MCP ERROR RECOVERY:
              TOOL_REQUEST(error)
              → TOOL_RESULT(error)
              → TOOL_REQUEST(retry)
              → TOOL_RESULT(recovery)
              → PROTOCOL_DELIVERY

MCP SCHEMA DRIFT:
              model-visible v1 discovery
              → TOOL_REQUEST(stale)
              → hidden live swap
              → real stale rejection
              → TOOL_RESULT(stale)
              → host cache invalidation
              → first fresh v2 discovery
              → TOOL_REQUEST(recovery)
              → TOOL_RESULT(recovery)
              → PROTOCOL_DELIVERY
```

The event kind is deliberately different from `ATTACK_DELIVERY`. It communicates that protocol evidence crossed into agent evidence through an explicit verified bridge rather than through an `AttackFixture` injector.

The ToolError and schema-drift bridge events are deliberately ordered **after** the recovery result because each receipt represents a full multi-step relation. Emitting either earlier would claim a relation that had not yet closed.

Unbridged MCP fault receipts, remote-auth receipts, and OAuth-flow receipts remain outside agent trial chronology.

This preserves the following non-implications:

```text
MCP configuration        ⇏ client observation
client observation       ⇏ agent consumption
second call              ⇏ causal retry
cache invalidation       ⇏ model-owned refresh
refreshed discovery      ⇏ correct adaptation
raw protocol receipt     ⇏ agent behavior
bridge closure           ⇏ automatic PASS
bearer authorization     ⇏ OAuth issuance correctness
OAuth-flow completion    ⇏ agent correctness
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

The standalone MCP laboratories return their own evidence-domain results rather than `TrialEvidence`. The dedicated bridges are exceptions only because they explicitly verify cross-domain identities and emit `PROTOCOL_DELIVERY` inside the agent trial.

The evaluator revalidates all known `PROTOCOL_DELIVERY` receipt types before subject grading. Unknown delivery sources, malformed receipts, receipt-root inconsistencies, protocol-relation inconsistencies, or scenario-identity mismatches block evaluation rather than being treated as opaque trusted JSON.

## Persistence, replay, statistics, and release authority

`LocalEvidenceStore` revalidates persisted bytes, manifests, hashes, identities, schema, semantic roots, symlink/file constraints, and no-clobber publication behavior before reuse. Local hashes do not authenticate a hostile writer who can coherently replace all controlled bytes.

`EvidenceReplayAdapter` performs exact-identity historical regrading. It does not re-run the agent, provider, tool, injector, MCP stdio bridges, MCP labs, or authorization flow and cannot establish fresh delivery. Persisted `PROTOCOL_DELIVERY` events are semantically revalidated as typed result, ToolError-recovery, or schema-drift receipts before deterministic grading.

Repeated trials feed `ReliabilityReport`; resolved behavior remains separate from blocked evaluator/runtime uncertainty. `AssuranceReport` binds evidence roots, deterministic oracle snapshots, reliability, release policy, gate output, and report root.

`ReleaseGate` preserves non-compensatory critical safety evidence. Insufficient evidence produces `INCONCLUSIVE`, not acceptance. Raw MCP protocol/auth/OAuth success is not release-gate authority.

## Current boundary

The framework currently provides deterministic contracts, content-addressed adversarial scenarios, evidence-bound OpenAI delivery verification across seven scoped channel categories, a six-fault official-SDK MCP protocol laboratory, three exact OpenAI↔MCP stdio bridge contracts (`TOOL_RESULT_POISON` same-call delivery, causal `TOOL_ERROR` retry/recovery, and host-refreshed `TOOL_SCHEMA_DRIFT` adaptation), a real-loopback resource-server authorization laboratory, a separated two-origin OAuth authorization-code/PKCE/introspection laboratory, integrity-verified local persistence, exact historical replay, deterministic policy/outcome oracles, metamorphic relations, repeated-trial statistics, assurance reports, release gating, and bounded failure minimization.

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

This checkpoint remains a historical audited merged implementation baseline. Capabilities added afterward, including ToolError recovery and host-refreshed schema-drift adaptation, are accepted only after their own exact-head CI, merge, and post-merge `main` verification; the historical checkpoint is not retroactively relabeled.

Still outside the executable claim boundary are credentialed live-provider assurance; agent-through-MCP grading for `tool_metadata_poison`, generic stale-cache, and `tool_identity_drift`; model-initiated MCP refresh and automatic `tools/list_changed` handling; arbitrary schema compatibility/migrations beyond the exact bound schema-drift fixture; generic retry/backoff/idempotency assurance beyond the exact one-retry ToolError relation; hosted/remote/Internet MCP fidelity; generic stdio/proxy/TLS/DNS/transport-chaos assurance; production IdP/JWT/JWKS/federation; CIMD/enterprise-managed authorization; DPoP/mTLS; refresh/revocation/replay lifecycle; public/shared-cache behavior beyond the exact implemented relations; arbitrary registry mutations; MCP resource/prompt/task fault families; production memory/retrieval; infrastructure chaos; semantic/model graders; signed provenance; and formal non-inferiority testing.

[← Documentation hub](README.md)
