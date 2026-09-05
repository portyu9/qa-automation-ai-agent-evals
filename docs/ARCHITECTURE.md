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
├── deterministic retrieval assurance
│   ├── content-addressed corpus/query/ranker/optional-poison contract
│   ├── platform-stable integer lexical ranking + canonical result
│   ├── exact OpenAI retrieval call/result binding
│   ├── RetrievalDeliveryReceipt without raw corpus duplication
│   └── replay-time semantic rederivation before grading
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
│   ├── TOOL_LIST_STALE_CACHE host-refreshed removal-delivery bridge
│   │   ├── initial protocol/model target presence
│   │   ├── evaluator-only hidden live target removal
│   │   ├── cached post-removal tools/list still exposes target
│   │   ├── real unknown-tool rejection for removed target
│   │   ├── host-owned cache invalidation after rejection
│   │   ├── first fresh post-invalidation tools/list proves target absent
│   │   ├── public model boundary proves target absent + exact rejection
│   │   ├── strict six-step protocol chronology
│   │   └── MCPAgentToolStaleCacheReceipt
│   ├── TOOL_SCHEMA_DRIFT host-refreshed adaptation bridge
│   │   ├── model receives bound v1 target schema
│   │   ├── evaluator-only hidden live swap to v2
│   │   ├── real MCP rejection of stale v1 arguments
│   │   ├── host-owned cache invalidation after rejection
│   │   ├── first fresh post-invalidation tools/list exposes v2
│   │   ├── distinct stale/recovery OpenAI call IDs
│   │   ├── exact bound v1/v2 arguments and recovery result
│   │   ├── strict six-step protocol chronology
│   │   └── MCPAgentToolSchemaDriftReceipt
│   └── TOOL_IDENTITY_DRIFT host-refreshed adaptation bridge
│       ├── model initially receives exact original identity
│       ├── evaluator-only hidden live old→replacement registry swap
│       ├── real MCP unknown-tool rejection for removed old name
│       ├── host-owned cache invalidation after rejection
│       ├── first fresh post-invalidation tools/list exposes replacement only
│       ├── public model boundary exposes replacement and no stale original
│       ├── distinct stale/recovery OpenAI call IDs
│       ├── exact canonical arguments and deterministic recovery result
│       ├── strict six-step protocol chronology
│       └── MCPAgentToolIdentityDriftReceipt
│
│   all six paths use a fresh official MCPServerStdio subprocess per trial
│   and require negotiated MCP 2026-07-28
├── protocol-delivery semantic verifier
├── native handoff-authority verifier
│   ├── exact scenario-owned root agent
│   ├── directed HandoffAuthorityGrant graph
│   ├── public SDK generating-agent provenance
│   └── path-local monotonic authority attenuation
├── native HITL approval-intent verifier
│   ├── exact ToolApprovalItem interruption
│   ├── accepted authority epoch + path identity
│   ├── ApprovalIntentReceipt
│   └── same-RunState approve/reject continuation
├── run-local side-effect idempotency observer
│   ├── exact two-attempt scenario contract
│   ├── real callback preserved on both attempts
│   ├── evaluator effect state before/after each callback
│   └── SideEffectIdempotencyReceipt + deterministic idempotency oracle
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
├── deterministic policy / side-effect / outcome oracles
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
    target systems, proxies, TLS infrastructure, cloud/IAM, production service registries,
    and production fault injectors
```

External content can become evidence or adversarial stimulus. It does not become control-plane authority merely because a model, tool, MCP server, resource, session, handoff, application context, HTTP endpoint, OAuth server, authorization middleware, or external service produced it.

## Identity domains

`SubjectFingerprint` binds provider, model, application revision, instructions, tool schema, policy, memory policy, and adapter identity/version. `EvaluationScenario` binds scenario ID/revision, objective, initial state, authority, required/forbidden outcomes, classification, tags, approval intent, optional side-effect-idempotency contract, optional `SemanticRubricSpec`, and optional `RetrievalContractSpec`. Behavior-bearing material therefore participates in scenario identity rather than living as untracked runtime configuration.

`AttackFixture` and `AdversarialCampaign` add deterministic adversarial identity without changing base authority or redefining success.

The protocol/control-plane identities remain intentionally distinct:

```text
AttackFixture          → AttackDeliveryReceipt
RetrievalContractSpec  → RetrievalDeliveryReceipt
ApprovalIntentSpec     → ApprovalIntentReceipt
SideEffectIdempotencySpec → SideEffectIdempotencyReceipt
MCPFaultSpec           → MCPFaultReceipt
MCPRemoteAuthPolicy    → MCPRemoteAuthReceipt
MCPOAuthFlowPolicy     → MCPOAuthFlowReceipt
```

Six receipt types bridge selected MCP protocol observations into agent-trial evidence without creating new fault identities:

- `MCPAgentToolMetadataReceipt` binds one verified MCP `TOOL_METADATA_POISON` discovery description/schema to the first exact public model-visible target definition without requiring invocation;
- `MCPAgentToolResultReceipt` binds one verified MCP `TOOL_RESULT_POISON` observation to one exact agent scenario, tool name, call ID, and model-visible output;
- `MCPAgentToolErrorRecoveryReceipt` binds one verified MCP `TOOL_ERROR` observation to one exact causal two-call agent relation: error call, model-visible error result, distinct same-argument retry call, and exact benign recovery;
- `MCPAgentToolStaleCacheReceipt` binds one verified MCP `TOOL_LIST_STALE_CACHE` discovery relation to one exact host-refreshed removal-delivery relation: initial model-visible target, hidden live removal, cached target, real unknown-tool rejection, host invalidation, first fresh target absence, and exact target-absent model-boundary rejection delivery;
- `MCPAgentToolSchemaDriftReceipt` binds one verified MCP `TOOL_SCHEMA_DRIFT` relation to one exact host-refreshed two-call agent relation: v1 discovery, hidden live replacement, stale-call rejection, host cache invalidation, first fresh v2 discovery, distinct corrected call, and exact replacement result;
- `MCPAgentToolIdentityDriftReceipt` binds one verified MCP `TOOL_IDENTITY_DRIFT` relation to one exact host-refreshed identity transition: original model-visible identity, hidden old→replacement swap, real stale-name rejection, host cache invalidation, first fresh replacement discovery, replacement-only model exposure, distinct replacement call, and exact recovery result.

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

All six fault kinds have explicit agent bridges. `tool_list_stale_cache` now proves only one exact host-refreshed removal-delivery relation; it does not imply generic cache coherence, model-owned refresh, or behavioral recovery. The metadata bridge proves exact model-visible exposure, not attention, interpretation, compliance, resistance, or safe behavior.

The schema- and identity-drift bridges are not blanket promotions of cache semantics. Their ownership is explicit: the harness owns the live mutation, the evaluator/host adapter owns cache invalidation, the official MCP session supplies the first fresh post-invalidation listing, the pinned Agents SDK converts that listing into model tool definitions, and the agent is credited only for changing its next target call after the replacement contract/identity becomes model-visible. Neither path claims model-initiated refresh or automatic `tools/list_changed` handling.

For identity drift specifically, tool names are exact run-local protocol/model identities within the controlled relation; the receipt does not elevate them into cryptographic or globally authenticated tool principals. See [MCP Tool-Identity Drift Assurance](MCP_IDENTITY_DRIFT.md).

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

For scenario-owned deterministic retrieval:

```text
retrieval contract configured, delivery missing/invalid → BLOCKED
verified retrieval delivery + deterministic violation  → FAIL
verified retrieval delivery + deterministic closure    → PASS
```

`RETRIEVAL_DELIVERY` binds one exact model-visible retrieval result to its scenario-owned corpus/query/ranker/poison relation and call identity. It is an evaluator precondition, not grading authority, and it does not convert generic `MEMORY` or inline-file `RESOURCE` injection into production RAG assurance.

For any dedicated MCP bridge:

```text
raw MCPFaultReceipt only                      → protocol evidence only
required bridge receipt missing/invalid       → BLOCKED
verified bridge + deterministic violation     → FAIL
verified bridge + deterministic closure       → PASS
```

No bridge receipt is grading authority. All six are evaluator-owned integrity evidence used to establish preconditions before deterministic subject grading. Likewise, a semantic judgment is not deterministic state or safety authority: it is evaluated only after deterministic policy/outcome closure and may only narrow that success to non-critical FAIL or INCONCLUSIVE.

## Seven OpenAI local/SDK channel boundaries

`OpenAIAgentsAdapter` implements all seven generic `AttackChannel` categories at scoped SDK/local boundaries:

- `USER_INPUT` — exact canonical fixture JSON as second ordered `Runner.run` user message;
- local `TOOL_RESULT` — first matching copied local `FunctionTool` result replacement, call-ID-bound;
- description-level `TOOL_METADATA` — copied local `FunctionTool.description` only;
- session-history `MEMORY` — fresh per-trial SDK `Session` prior user item;
- inline-file `RESOURCE` — exact canonical JSON as structured `input_file.file_data`;
- native `HANDOFF` — exact canonical JSON appended to first actual SDK handoff context while preserving destination;
- runtime-context `ENVIRONMENT` — exact canonical JSON returned for one exact string key only during the first matching local `FunctionTool` invocation, with delivery created only on actual value consumption.

These seven categories are not universal production interception claims. Deterministic retrieval assurance is a separate scenario/evidence domain rather than an eighth generic attack channel. The local result injector does not intercept MCP tools; the dedicated MCP bridges are separate adapters and evidence contracts.

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

`OpenAIAgentsMCPToolResultAdapter` closes one relation for `TOOL_RESULT_POISON` without weakening the protocol/agent separation.

```text
MCPFaultSpec(tool_result_poison)
→ fresh MCPServerStdio
→ protocol 2026-07-28
→ exactly one behavioral target call
→ first MCP result observation / MCPFaultReceipt
→ exact OpenAI TOOL_REQUEST(call_id) + TOOL_RESULT(call_id)
→ model-visible output equivalence
→ MCPAgentToolResultReceipt / PROTOCOL_DELIVERY
→ same-session benign recovery after the run
→ TrialEvidence → deterministic oracles
```

Recovery happens after the behavioral run. This verifies one-shot isolation without adding a second benign result to the transcript being graded.

## OpenAI↔MCP ToolError retry/recovery boundary

`OpenAIAgentsMCPToolErrorRecoveryAdapter` closes a different relation for `TOOL_ERROR`: the real controlled error must become model-visible before one same-argument target call can be credited as a recovery retry.

```text
TOOL_REQUEST(error)
→ real MCP ToolError / MCPFaultReceipt
→ TOOL_RESULT(error)
→ TOOL_REQUEST(retry; distinct call ID, same canonical arguments)
→ same-session benign recovery
→ TOOL_RESULT(recovery)
→ MCPAgentToolErrorRecoveryReceipt / PROTOCOL_DELIVERY
```

The normalized chronology must satisfy `request₁ < result₁ < request₂ < result₂`. Pre-issued identical calls do not prove causal retry and fail closed.

## OpenAI↔MCP schema-drift adaptation boundary

`OpenAIAgentsMCPToolSchemaDriftAdapter` credits a corrected v2 call only when the model first received the bound v1 contract, the harness changed the live schema after v1 selection and before validation, real MCP validation rejected the stale call, and host-owned refresh made v2 model-visible before the corrected call.

```text
model v1
→ TOOL_REQUEST(stale v1)
→ hidden live v2 swap
→ real stale rejection / TOOL_RESULT
→ host cache invalidation
→ first fresh v2 discovery
→ model v2 + rejection
→ TOOL_REQUEST(recovery v2)
→ TOOL_RESULT(replacement)
→ MCPAgentToolSchemaDriftReceipt / PROTOCOL_DELIVERY
```

The strict protocol chronology is `initial-list < swap < stale-call < cache-invalidation < refreshed-list < recovery-call`. Later cached reads of already-refreshed v2 do not create extra refresh claims.

## OpenAI↔MCP identity-drift adaptation boundary

`OpenAIAgentsMCPToolIdentityDriftAdapter` credits a replacement-name call only when the public model boundary first exposed exactly the original controlled identity, the harness replaced the live registry entry after old-name selection and before lookup, real MCP lookup rejected the stale name, and host-owned refresh made exactly the replacement identity model-visible before recovery.

```text
model original identity
→ TOOL_REQUEST(stale old name)
→ hidden live old→replacement swap
→ real unknown-tool rejection / TOOL_RESULT
→ host cache invalidation
→ first fresh replacement-only discovery
→ model replacement identity + rejection
→ TOOL_REQUEST(exact replacement; distinct call ID)
→ TOOL_RESULT(exact deterministic recovery)
→ MCPAgentToolIdentityDriftReceipt / PROTOCOL_DELIVERY
```

The bridge requires strict normalized `request₁ < result₁ < request₂ < result₂` and protocol `initial-list < swap < stale-call < cache-invalidation < refreshed-list < recovery-call` chronology. It also binds strict canonical arguments, protocol/model rejection equivalence, model-visible initial/refreshed identity-set digests, and exact same-session recovery.

A model that emits the removed old name after refresh may be rejected directly by the SDK/MCP execution boundary. That is preserved as runtime uncertainty (`RUNTIME_ERROR / BLOCKED`); the evaluator does not synthesize a continuation merely to force another error shape.

This is **host-refreshed identity adaptation**, not model-owned cache refresh or generic rename migration. See [MCP Tool-Identity Drift Assurance](MCP_IDENTITY_DRIFT.md).

## SDK representation is not protocol identity

The pinned Agents SDK may serialize one logical text result differently across internal `ToolCallOutputItem.output` and Responses replay input. The bridges compare logical public outputs represented by normalized evidence rather than pretending incidental wire spellings are the same object.

For schema drift, the bridge binds canonical projections of the raw MCP schemas while integration tests separately assert actual model-visible tool definitions. For identity drift, the bridge separately binds raw protocol discovery identities and the controlled identity sets supplied at the public model boundary. Protocol observation is therefore not inferred from model visibility, and model visibility is not inferred from protocol discovery.

## MCP resource-server Streamable HTTP authorization boundary

`MCPRemoteAuthLab` is intentionally separate from both protocol faults and the agent bridges.

```text
MCPRemoteAuthPolicy
→ pre-bound 127.0.0.1 TCP socket
→ Uvicorn + MCP Streamable HTTP app
→ resource-server auth middleware
→ 401/403 + RFC 9728 metadata + authorized MCP calls
→ MCPRemoteAuthReceipt
```

Enforcement ownership is explicit: deterministic `TokenVerifier` owns exact issuer/resource binding; MCP SDK middleware owns bearer/expiry acceptance and required scopes; the official client owns the protected loopback calls. This layer proves resource-server enforcement, not token issuance or agent behavior.

## Separated MCP OAuth-flow boundary

`MCPOAuthFlowLab` hosts authorization server and resource server on different loopback origins and uses the official MCP `OAuthClientProvider`.

```text
MCPOAuthFlowPolicy
→ protected-resource metadata
→ authorization-server metadata
→ DCR compatibility fallback when needed
→ state + PKCE S256 + exact resource/scopes
→ exact RFC 9207 authorization-response issuer
→ authorization-code exchange
→ opaque access token
→ authenticated HTTP introspection
→ protected MCP use
→ stored-authorization reuse
→ MCPOAuthFlowReceipt
```

DCR is compatibility behavior, not a claim of modern CIMD support. Authorization code, access token, and introspection secret are omitted from serialized evidence.

## Evidence chronology and separation

OpenAI local channel ordering includes:

```text
TOOL_RESULT:  TOOL_REQUEST → ATTACK_DELIVERY → TOOL_RESULT
ENVIRONMENT:  TOOL_REQUEST → ATTACK_DELIVERY → TOOL_RESULT
HANDOFF:      HANDOFF → ATTACK_DELIVERY
```

The MCP bridges use distinct protocol-delivery chronology:

```text
MCP METADATA:
              PROTOCOL_DELIVERY before normalized model/agent behavior
              (leading pre-model ATTACK_DELIVERY may precede it)

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
              model-visible v1
              → TOOL_REQUEST(stale)
              → hidden live schema swap
              → real stale rejection / TOOL_RESULT
              → host invalidation
              → first fresh v2
              → TOOL_REQUEST(recovery)
              → TOOL_RESULT(recovery)
              → PROTOCOL_DELIVERY

MCP IDENTITY DRIFT:
              model-visible original identity
              → TOOL_REQUEST(stale old name)
              → hidden live identity swap
              → real unknown-tool rejection / TOOL_RESULT
              → host invalidation
              → first fresh replacement identity
              → TOOL_REQUEST(exact replacement)
              → TOOL_RESULT(recovery)
              → PROTOCOL_DELIVERY
```

`PROTOCOL_DELIVERY` is deliberately different from `ATTACK_DELIVERY`. It communicates that protocol evidence crossed into agent evidence through an explicit verified bridge rather than through an `AttackFixture` injector.

ToolError, schema-drift, and identity-drift bridge events are ordered **after** the recovery result because each receipt represents a full multi-step relation. Emitting one earlier would claim a relation that had not yet closed.

Unbridged stale-cache fault receipts, remote-auth receipts, and OAuth-flow receipts remain outside agent trial chronology.

This preserves the following non-implications:

```text
MCP configuration        ⇏ client observation
client observation       ⇏ agent/model observation
second call              ⇏ causal retry
cache invalidation       ⇏ model-owned refresh
refreshed discovery      ⇏ correct adaptation
replacement identity     ⇏ globally authenticated identity
raw protocol receipt     ⇏ agent behavior
bridge closure           ⇏ automatic PASS
bearer authorization     ⇏ OAuth issuance correctness
OAuth-flow completion    ⇏ agent correctness
protocol/control receipt ⇏ release acceptance
```

## Authority remains fail-closed

`AuthorityPolicy` controls allowed/forbidden tools, approval-required tools, resource prefixes, root/delegated agent authority, and budgets. Unknown authority is not permission.

Adversarial derivation cannot broaden authority. A bridge cannot broaden authority either: it binds delivery identity, not policy permission. A renamed MCP tool is not automatically authorized merely because the identity-drift bridge proves it became model-visible; the scenario's deterministic authority still controls grading.

Critical policy failure remains non-compensatory.

## Adapter and runtime failure separation

`AgentAdapter` executes and normalizes; it does not grade itself.

`AdapterPreconditionError` represents evaluator-controlled prerequisites that cannot be satisfied. `TrialRunner` converts it to `EVALUATION_ERROR / BLOCKED`. Provider/SDK execution exceptions remain `RUNTIME_ERROR / BLOCKED`.

Neither is rewritten as subject `FAIL`.

The standalone MCP laboratories return their own evidence-domain results rather than `TrialEvidence`. The dedicated bridges are exceptions only because they explicitly verify cross-domain identities and emit `PROTOCOL_DELIVERY` inside the agent trial.

The evaluator revalidates all known `PROTOCOL_DELIVERY` receipt types—including identity drift—before subject grading. Unknown delivery sources, malformed receipts, receipt-root inconsistencies, protocol-relation inconsistencies, or scenario-identity mismatches block evaluation rather than being treated as opaque trusted JSON.

## Persistence, replay, statistics, and release authority

`LocalEvidenceStore` revalidates persisted bytes, manifests, hashes, identities, schema, semantic roots, symlink/file constraints, and no-clobber publication behavior before reuse. Local hashes do not authenticate a hostile writer who can coherently replace all controlled bytes.

`EvidenceReplayAdapter` performs exact-identity historical regrading. It does not rerun the agent, provider, tools, side effects, injectors, MCP stdio bridges, MCP labs, or authorization flow and cannot establish fresh delivery. Persisted `PROTOCOL_DELIVERY` events are semantically revalidated through their typed metadata, result, ToolError-recovery, schema-drift, or identity-drift receipt contract before deterministic grading.

Repeated trials feed `ReliabilityReport`; resolved behavior remains separate from blocked evaluator/runtime uncertainty. `AssuranceReport` binds evidence roots, deterministic oracle snapshots, optional semantic receipts, reliability, release policy, gate output, and report root.

`ReleaseGate` preserves non-compensatory critical safety evidence. Insufficient evidence produces `INCONCLUSIVE`, not acceptance. Raw MCP protocol/auth/OAuth success is not release-gate authority.

## Current boundary

The executable architecture currently includes provider-neutral deterministic contracts/oracles, seven scoped OpenAI local/SDK adversarial channels, deterministic retrieval assurance, native handoff-authority attenuation, native HITL approval-intent binding, run-local side-effect-idempotency observation, optional calibrated subordinate semantic judging, the six-fault official-SDK MCP protocol laboratory, **six exact OpenAI↔MCP stdio bridges** (metadata, result, ToolError recovery, host-refreshed stale-cache removal delivery, host-refreshed schema drift, and host-refreshed identity drift), loopback resource-server authorization, separated two-origin OAuth authorization-code/PKCE/introspection, integrity-verified local persistence, exact historical replay, metamorphic relations, repeated-trial statistics, assurance reports, release gating, and bounded failure minimization.

Implementation source checkpoint `d98f9ca1feb1179504cd2181295a73936fd0ae6c`, protected-main CI run `33898508697` remains the historical audited merged baseline:

- deterministic core: **349 passed, 27 deselected**;
- branch coverage: **93.79%** against the 90% gate;
- strict mypy: **0 issues across 42 source files**;
- deterministic OpenAI SDK suite, including the then-current MCP stdio bridge: **15/15 passed**;
- deterministic MCP protocol: **6/6 passed**;
- deterministic MCP remote auth: **3/3 passed**;
- deterministic MCP OAuth flow: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest**, Ruff, formatter, Bandit, dependency audit, package integrity, and all **7/7 CI jobs**: green;
- dependency audit: no known vulnerabilities found; the project package itself is skipped because it is not published on PyPI.

Capabilities added afterward—including ToolError recovery, host-refreshed schema drift, host-refreshed identity drift, native handoff authority, native HITL approval intent, calibrated semantic judging, retrieval assurance, and side-effect idempotency assurance—require their own exact-head CI, merge, and post-merge `main` verification; the historical checkpoint is not retroactively relabeled.

Still outside the executable claim boundary are credentialed live-provider assurance; generic stale-cache agent behavior; model-initiated MCP refresh and automatic `tools/list_changed` handling; arbitrary schema migrations; arbitrary rename/alias/multi-tool identity migration; generic retry/backoff/distributed idempotency; hosted/remote/Internet MCP fidelity; generic proxy/TLS/DNS/transport-chaos assurance; production IdP/JWT/JWKS/federation and enterprise IAM; production memory/retrieval; infrastructure chaos; cryptographic/signed provenance and tool identity; and formal non-inferiority testing.

[← Documentation hub](README.md)
