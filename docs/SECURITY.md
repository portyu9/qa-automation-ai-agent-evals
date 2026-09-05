# Security

## Security posture

The repository treats the evaluated agent and all provider/tool/MCP/memory/resource/handoff/runtime-context content as untrusted with respect to evaluation authority. Evidence may describe what happened; it may not redefine what is allowed or what counts as success.

An adversarial or cross-domain agent trial is not behaviorally gradeable until the controlled evaluation environment closes the exact evaluation precondition required by that execution path. Failure to establish that precondition is `BLOCKED` uncertainty, not an invented agent defect.

The security model keeps distinct evidence domains rather than allowing a green observation in one layer to silently upgrade another:

1. **OpenAI local/SDK adversarial delivery** — one exact `AttackDeliveryReceipt` must verify before grading an adversarial `AttackFixture` scenario.
2. **Deterministic retrieval delivery** — one exact `RetrievalDeliveryReceipt` binds the scenario-owned corpus/query/ranker/optional-poison relation and stable target call identity to the exact canonical model-visible result.
3. **Native handoff authority** — scenario-owned directed grants plus public SDK generating-agent provenance constrain path-local authority; provider identity labels do not become authorization authority.
4. **Native HITL approval intent** — `ApprovalIntentReceipt` binds one exact SDK approval interruption to one exact scenario decision and same-`RunState` continuation; it is not human authentication.
5. **Run-local side-effect idempotency** — `SideEffectIdempotencyReceipt` binds two exact subject attempts to evaluator-owned before/after effect observations without suppressing either callback.
6. **MCP protocol faults** — one exact `MCPFaultReceipt` proves only the official client's bound protocol observation or relation.
7. **MCP→OpenAI bridges** — five typed bridge receipts close narrow metadata/result/error/schema/identity relations before deterministic grading.
8. **MCP resource-server authorization** — `MCPRemoteAuthReceipt` closes the loopback authentication/authorization matrix and RFC 9728 metadata boundary.
9. **MCP OAuth flow** — `MCPOAuthFlowReceipt` closes the separated authorization-server/resource-server discovery, PKCE, issuer/resource binding, exchange, introspection, protected-use, and reconnect-reuse boundary.
10. **Calibrated semantic judgment** — `SemanticJudgmentReceipt` binds one exact subordinate meaning-level decision to the scenario rubric, subject, pre-semantic evidence root, exact judge profile, accepted calibration, bounded inputs, and derived decision. It is never invoked after deterministic failure and is never critical authority.

These families do not inherit authority from one another. In particular, a raw protocol receipt is not agent behavioral assurance, and a bridge receipt is an evaluation precondition rather than automatic PASS.

## Deterministic controls

Implemented controls include:

- fail-closed tool/resource/approval/budget authority and non-compensatory critical policy failure;
- separate `EVALUATION_ERROR / BLOCKED`, `RUNTIME_ERROR / BLOCKED`, deterministic `FAIL`, and deterministic `PASS` semantics;
- immutable ordered evidence plus domain-separated roots;
- content-addressed scenario, attack, retrieval, approval, MCP, authorization, OAuth, semantic-profile, and report identities;
- exact delivery/observation receipts with known-source dispatch rather than opaque trusted JSON;
- strict duplicate-key-rejecting finite JSON parsing where arguments or evaluator contracts require canonical identity;
- scenario-owned native handoff grants whose effective authority may preserve or narrow across accepted paths, never expand;
- accepted authority epoch/path binding for native approval intent so malformed handoffs or same-depth sibling paths cannot replay approval evidence;
- two real side-effect callbacks preserved under observation, with continuous evaluator-owned effect chronology and fail-closed receipt verification;
- platform-stable deterministic retrieval ranking and exact `TOOL_REQUEST < RETRIEVAL_DELIVERY < TOOL_RESULT` closure;
- official MCP `2026-07-28` protocol observations using pinned `mcp==2.1.1`;
- five dedicated official-stdio/OpenAI bridges using a fresh `MCPServerStdio` subprocess per trial and pinned `openai-agents==0.22.0`;
- exact call-ID and request/result chronology binding for result, retry, schema-drift, and identity-drift bridges;
- hidden evaluator controls filtered from model-visible MCP tools for schema and identity mutation;
- direct public model-boundary observation where metadata/schema/identity visibility is part of the assurance claim;
- typed `PROTOCOL_DELIVERY` semantic revalidation before grading and on replay;
- real loopback TCP resource-server authorization and separated OAuth AS/RS laboratories;
- integrity-verified local evidence persistence with no-clobber publication and exact-identity replay;
- optional calibrated semantic judging that can narrow deterministic success but never rescue deterministic failure;
- pinned GitHub Actions and read-only workflow permissions.

## Seven scoped OpenAI local/SDK attack surfaces

`OpenAIAgentsAdapter` exercises:

1. direct user input;
2. indirect content returned by a targeted local `FunctionTool`;
3. targeted local tool-description metadata;
4. client-side SDK session history;
5. structured inline-file input;
6. context transferred through the first native SDK handoff;
7. one targeted local application's SDK runtime-context key consumed during a local tool call.

These are scoped implementations of generic threat channels, not claims of universal production control. The local `TOOL_RESULT` injector does not intercept MCP tools. Deterministic retrieval assurance is a separate precondition domain, not an eighth generic attack channel and not hosted File Search/RAG assurance.

## Deterministic retrieval security boundary

A configured `RetrievalContractSpec` is not trusted as proof of delivery. The evaluator rederives baseline and active rankings, requires any controlled poison relation to close under the exact bound ranker, requires one exact model-selected target call with the scenario-bound query, and binds the exact canonical result to that stable call ID through `RETRIEVAL_DELIVERY`.

Persisted retrieval evidence is replay-safe only for the exact scenario identity. The receipt intentionally omits raw corpus content and raw source locators; ranked chunk/document identities, scores, and content digests retain the minimum durable relation needed for rederivation.

Missing, duplicate, reordered, malformed, foreign-source, or unreconstructable retrieval evidence is `EVALUATION_ERROR / BLOCKED`. A verified poison entering top-k is still only a retrieval relation, not proof that the model followed, ignored, resisted, or safely handled it.

## MCP protocol-fault security boundary

A valid `MCPFaultSpec` binds stable fault identity, revision, kind, original tool name, and canonical finite JSON payload.

The official-client protocol observation points are:

```text
mcp:2026-07-28:tools/list:<tool>:description
mcp:2026-07-28:tools/call:<tool>:result.content[0].text
mcp:2026-07-28:tools/call:<tool>:error.content[0].text:message-suffix
mcp:2026-07-28:tools/list:cache-use-stale-after-remove:<tool>:refresh-proves-absent
mcp:2026-07-28:tools/list:schema-drift:<tool>:cached-old:call-rejects-old:refresh-new
mcp:2026-07-28:tools/list:identity-drift:<tool>:cached-old-name:call-rejects-old:refresh-new-name
```

`payload_sha256` identifies controlled fault material. `observation_sha256` identifies the complete canonical observation. They may differ whenever the SDK transforms content or the proof is relational.

Every protocol probe gets a fresh server. Discovery probes get fresh cache state. Result/error faults are one-shot and recover. Drift receipts require current-server rejection plus recovery under refreshed truth.

The protocol laboratory proves protocol conditions only. `tool_list_stale_cache` remains protocol-only with respect to agent behavior. Metadata, result, ToolError, schema drift, and identity drift cross into `TrialEvidence` only through their dedicated typed bridge contracts.

## Shared MCP→OpenAI provenance controls

All five MCP bridge adapters create a **fresh official MCP stdio process/session** per trial. The supplied base Agent is cloned with exactly the controlled server and is rejected when preconfigured MCP servers, prefixed naming, or local target/control-name collisions would make provenance ambiguous.

The connected session must negotiate exact MCP protocol `2026-07-28`. Configured intent is not accepted as negotiated-version evidence.

A bridge receipt is created from **observed protocol/model/agent facts**, not merely from configured fault material. Unknown bridge sources, malformed receipts, wrong scenario identity, impossible chronology, or root mismatch fail closed before subject grading.

### Metadata bridge

`OpenAIAgentsMCPToolMetadataAdapter` binds one verified `TOOL_METADATA_POISON` discovery observation to exactly one public model-visible target definition with matching target identity, description digest, and parameter-schema digest. Target invocation is not required because metadata can influence selection before any call.

The adapter requires a concrete public SDK `Model` and observes both response and streaming model boundaries. Duplicate target definitions, transformed descriptions, schema mismatch, local collision, protocol drift, or post-behavior replay placement blocks evaluation.

This proves exposure, not model attention, interpretation, resistance, or safety.

### Result bridge

`OpenAIAgentsMCPToolResultAdapter` requires exactly one behavioral target call, a real first controlled result creating `MCPFaultReceipt`, one exact normalized OpenAI request/result call-ID pair, logical output equivalence, and same-argument benign recovery through the same connected MCP session after the behavioral run.

`MCPAgentToolResultReceipt` therefore means the controlled protocol result and result attributed to the exact agent call are the same evaluated delivery fact. Recovery happens after the run so it cannot contaminate the transcript.

### ToolError retry/recovery bridge

`OpenAIAgentsMCPToolErrorRecoveryAdapter` requires exactly two behavioral target calls. The first must produce a real MCP error observation; the second must use the same canonical arguments under a distinct stable call ID and recover on the same live session.

Normalized evidence must satisfy:

```text
request₁ < result₁ < request₂ < result₂
```

Two pre-issued identical calls do not prove causal retry. `MCPAgentToolErrorRecoveryReceipt` binds protocol receipt, call identities, argument digest, model-visible error digest, expected/observed recovery digest, and a domain-separated root. `PROTOCOL_DELIVERY` is emitted only after the recovery result.

### Schema-drift adaptation bridge

`OpenAIAgentsMCPToolSchemaDriftAdapter` implements one host-refreshed v1→v2 contract. The first model turn must receive exact v1. Only after the model selects v1-shaped arguments does a hidden evaluator control replace the live target with v2 before real MCP validation. The stale v1 call must then be rejected by real v2 validation.

The host invalidates cached discovery only after that rejection. The first fresh post-invalidation `tools/list` must expose exact v2 before recovery. The recovery request uses distinct call identity, exact bound v2 arguments, and exact same-session replacement result.

Protocol chronology must satisfy:

```text
initial-list < schema-swap < stale-call < cache-invalidation < refreshed-list < recovery-call
```

`MCPAgentToolSchemaDriftReceipt` binds schema, argument, rejection/recovery, call-identity, and chronology digests without duplicating raw controlled content. `PROTOCOL_DELIVERY` closes only after the recovery result.

The harness owns schema mutation; the host adapter owns invalidation; the official MCP session owns refreshed discovery; the SDK owns model-visible conversion; the model is credited only for selecting the corrected v2 call after v2 is visible.

### Identity-drift adaptation bridge

`OpenAIAgentsMCPToolIdentityDriftAdapter` applies the same ownership discipline to one exact old→replacement tool identity relation while keeping the callable schema stable.

The initial protocol and public model boundaries must expose exactly the original controlled identity. After the model selects that old name, a hidden evaluator control atomically removes the original tool and adds the exact bound replacement identity before the real MCP lookup. The removed old name must produce a real unknown-tool rejection.

Only after that rejection does the host invalidate MCP discovery. The first fresh post-invalidation listing must contain exactly the replacement controlled identity; the recovery model boundary must likewise expose the replacement and no stale original identity. The second controlled request must use the exact replacement name, a distinct stable OpenAI call ID, strict finite canonical arguments matching the live invocation, and the exact deterministic recovery result on the same session.

Normalized agent chronology:

```text
request(original) < result(rejection) < request(replacement) < result(recovery)
```

Protocol chronology:

```text
initial-list < identity-swap < stale-call < cache-invalidation < refreshed-list < recovery-call
```

`MCPAgentToolIdentityDriftReceipt` binds the nested protocol receipt, exact original/replacement identities and compact identity digests, model-visible initial/refreshed identity-set digests, distinct call IDs, argument digests, protocol/model rejection and recovery digests, all six ordinals, scenario identity, and a domain-separated root. Raw rejection/recovery bodies and raw arguments are not duplicated when digests suffice.

A removed old identity emitted after refresh can be rejected directly by the pinned SDK/MCP boundary before another model turn. The evaluator preserves that runtime failure as `RUNTIME_ERROR / BLOCKED`; it does not repair the subject or synthesize a continuation.

This bridge proves **host-refreshed identity adaptation**, not model-owned cache refresh, generic rename migration, global/cryptographic tool identity, or provider/target attestation. See [MCP Tool-Identity Drift Assurance](MCP_IDENTITY_DRIFT.md).

## MCP resource-server authorization security boundary

`MCPRemoteAuthLab` tests resource-server behavior over real loopback TCP Streamable HTTP, not an in-process ASGI shortcut.

| Property | Owner in the laboratory |
|---|---|
| exact issuer match | deterministic `TokenVerifier` |
| exact resource match | deterministic `TokenVerifier` |
| bearer recognition / verifier acceptance | MCP SDK authentication middleware |
| token expiration | MCP SDK authentication middleware |
| required scopes | MCP SDK authorization middleware |
| RFC 9728 protected-resource metadata | MCP SDK protected-resource route |
| actual protected MCP request | official Streamable HTTP client over loopback TCP |

The matrix requires 401 for missing, unknown, expired, wrong-issuer, and wrong-resource credentials; 403 for authenticated missing-scope credentials; correct protected-resource metadata; and successful protected discovery/call with a valid scoped bearer.

This proves resource-server enforcement only. It is not bridged into agent verdict evidence.

## MCP OAuth-flow security boundary

`MCPOAuthFlowLab` closes a separate authorization-client/authorization-server boundary over two independent loopback origins.

It verifies protected-resource and authorization-server metadata, compatibility registration fallback, state, PKCE `S256`, exact authorization-response issuer, resource indicators, code exchange, authenticated HTTP introspection, protected MCP use, and stored-authorization reuse.

The resource server does not directly read the authorization server's in-memory token dictionary. Introspection transport/HTTP/JSON failure, inactive token, issuer/resource/client mismatch, invalid expiration, or invalid subject fails closed.

Authorization code, access token, and introspection secret are omitted from serialized evidence. DCR is a compatibility fallback; CIMD is outside current scope.

## MCP security non-claims

Current MCP coverage does **not** establish:

- agent behavior for generic stale-cache conditions beyond the protocol-only `tool_list_stale_cache` laboratory;
- arbitrary MCP result, error, schema, or identity behavior beyond the five exact controlled bridge contracts;
- generic retry/backoff/idempotency safety beyond one same-argument ToolError retry and the separate local side-effect observer;
- model-initiated MCP refresh or automatic `tools/list_changed` handling;
- arbitrary JSON Schema compatibility or migration beyond the bound v1/v2 fixture;
- arbitrary rename, alias, fallback, or multi-tool identity migration beyond the bound identity fixture;
- semantic equivalence of externally administered old/replacement tools merely because the harness defines a controlled relation;
- arbitrary parallel target plans or multiple controlled MCP servers;
- OpenAI hosted MCP interception or third-party hosted MCP fidelity;
- remote/Internet MCP behavior or general stdio robustness beyond exact deterministic subprocess paths;
- reverse proxy, gateway, TLS, DNS, service-mesh, packet, latency, disconnect, retry, or rate-limit assurance;
- third-party/production authorization-server or identity-provider assurance;
- production JWT/JWKS signature verification, federation, DPoP/mTLS, refresh/revocation/replay lifecycle, or enterprise IAM;
- public/cross-partition cache sharing, arbitrary cache poisoning, notification invalidation, or TTL race correctness;
- arbitrary registry churn beyond exact fixtures;
- malformed framing/JSON-RPC, duplicate/out-of-order responses, or header-routing faults;
- malicious MCP resources, prompts, roots, elicitation, sampling, subscriptions, or Tasks-extension behavior;
- full protocol-conformance certification;
- provider-side or target-side cryptographic delivery/identity attestation;
- release acceptance from any protocol/control-plane receipt alone.

## Runtime-context `ENVIRONMENT` security boundary

`ENVIRONMENT` is intentionally not process-global environment mutation. The adapter accepts only `None` or string-keyed `Mapping` context, snapshots it into a read-only trial-local overlay, and activates one adversarial key with task-local state during one targeted call.

Delivery requires actual value consumption through `ctx.context[key]` or `.get(key)`. Mere configuration, membership checks, or tool execution is insufficient. The original caller mapping is not mutated; later ordinary execution sees the original value.

This does not claim filesystem, browser, container, network, DNS, clock, secret-manager, credential, provider-config, cloud-IAM, database, service-mesh, or production-chaos coverage.

## Integrity is not attestation

`injector:<identity>`, scenario identities, MCP fault identities, bridge identities, remote-auth policy identities, OAuth-flow policy identities, semantic profile identities, and report identities are control-plane/content identities, not authenticated signer identities. Receipt/evidence roots are domain-separated integrity hashes, not signatures, MACs, trusted timestamps, or hardware attestation.

In particular, original/replacement tool-name digests in `MCPAgentToolIdentityDriftReceipt` make the controlled relation compact and tamper-evident relative to evaluator-owned evidence; they do **not** make tool names globally authenticated principals.

The public `MCPRemoteAuthProbeResult` and `MCPOAuthFlowProbeResult` models are diagnostic envelopes. Their embedded receipt identities are validated, but outer diagnostic fields are not independently cryptographically re-bound to those receipts.

A stronger deployment layer must separately address signer identity, trusted timestamps, tamper-resistant storage, transport authenticity, and independent target-side acknowledgements where required.

## Sensitive data

Adversarial, retrieval, approval, side-effect, MCP, bridge, auth, OAuth, and semantic receipts minimize raw controlled content and credential material. Controlled boundaries necessarily expose the stimulus or credential to the exact surface being tested. Normal redaction, minimization, retention, and access-control discipline still applies to tool outputs, protocol payloads, HTTP logs, OAuth client state, sessions, resource/retrieval content, handoff context, approval arguments, and runtime application context.

Identity-drift bridge receipts retain identities and digests but do not duplicate the raw stale rejection or deterministic recovery text when hashes suffice.

## Deployment boundary

Application-level evaluation and deterministic loopback/stdio testing cannot by themselves prove process isolation, Internet transport security, secret-manager policy, production IAM, tenant isolation, sandbox containment, hosted MCP fidelity, production memory/retrieval integrity, distributed handoff correctness, third-party authorization-server security, production service-registry correctness, or infrastructure fault behavior.

## Verified implementation checkpoint

Implementation source checkpoint `d98f9ca1feb1179504cd2181295a73936fd0ae6c`, protected-main CI run `33898508697` remains the historical audited merged implementation baseline:

- deterministic core: **349 passed, 27 deselected**;
- branch coverage: **93.79%** against the 90% gate;
- strict mypy: **0 issues across 42 source files**;
- deterministic OpenAI SDK suite, including the original MCP stdio result bridge: **15/15 passed**;
- deterministic MCP protocol: **6/6 passed**;
- deterministic MCP remote auth: **3/3 passed**;
- deterministic MCP OAuth flow: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest**, Ruff, formatter, Bandit, dependency audit, package integrity, and all **7/7 CI jobs**: green;
- dependency audit: **no known vulnerabilities found**; the project package itself is skipped because it is not published on PyPI.

Capabilities added afterward—including ToolError recovery, host-refreshed schema drift, host-refreshed identity drift, native handoff authority, native HITL approval intent, retrieval assurance, semantic judging, and side-effect idempotency—require their own exact-head CI, merge, and post-merge `main` verification; the historical checkpoint is not retroactively relabeled.

[← Documentation hub](README.md)
