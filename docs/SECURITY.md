# Security

## Security posture

The repository treats the evaluated agent and all provider/tool/MCP/memory/resource/handoff/runtime-context content as untrusted with respect to evaluation authority. Evidence may describe what happened; it may not redefine what is allowed or what counts as success.

An adversarial agent trial is not behaviorally gradeable until the controlled evaluation environment closes the exact delivery precondition required by that execution path. Failure to establish that precondition is `BLOCKED` evaluation uncertainty, not an agent defect.

The security model distinguishes five evidence-domain relationships, with the MCP→OpenAI domain containing two explicit bridge contracts:

1. OpenAI local/SDK adversarial delivery — one exact `AttackDeliveryReceipt` must verify before grading an adversarial `AttackFixture` scenario.
2. MCP protocol faults — one exact `MCPFaultReceipt` proves only the official client's bound protocol observation or relation.
3. MCP→OpenAI bridges — `MCPAgentToolResultReceipt` binds a verified `TOOL_RESULT_POISON` observation to one exact agent call/result, while `MCPAgentToolErrorRecoveryReceipt` binds a verified `TOOL_ERROR` observation to one causal error → same-argument retry → recovery relation.
4. MCP resource-server authorization — `MCPRemoteAuthReceipt` closes the loopback authentication/authorization matrix and RFC 9728 metadata boundary.
5. MCP OAuth flow — `MCPOAuthFlowReceipt` closes the separated authorization-server/resource-server discovery, PKCE, exact issuer/resource binding, exchange, introspection, protected-use, and reconnect-reuse boundary.

These evidence families do not inherit authority from one another. In particular, a raw protocol receipt is not agent behavioral assurance, and a bridge receipt is a delivery precondition rather than an automatic PASS.

## Deterministic controls

Implemented controls include:

- explicit tool allowlists/denylists, approval-before-use checks, resource-prefix confinement, and tool/handoff budgets;
- critical non-compensatory policy failure;
- separate `EVALUATION_ERROR / BLOCKED` and `RUNTIME_ERROR / BLOCKED` semantics;
- immutable ordered agent evidence and domain-separated roots;
- content-addressed adversarial fixtures/campaigns with authority-preserving derivation;
- exact OpenAI delivery receipts binding scenario, attack, channel, injection point, and canonical payload digest;
- fail-closed handling of missing, duplicate, malformed, mismatched, or never-produced delivery evidence;
- seven tested OpenAI channel categories at narrow SDK/local boundaries;
- per-trial copied-tool/cloned-agent isolation for local OpenAI tool attacks;
- fresh SDK session isolation for memory attacks;
- ephemeral structured run input for resources;
- fresh one-shot handoff-filter isolation;
- read-only trial-local runtime-context overlay with task-local activation for environment attacks;
- exact call-ID binding for local tool-result and environment-consumption receipts;
- content-addressed `MCPFaultSpec` independent from OpenAI attack fixtures;
- official `mcp==2.1.1` protocol execution pinned to `2026-07-28`;
- exact MCP observation for description poison, result poison, model-visible `ToolError`, stale removal cache, tool-schema drift, and tool-identity drift;
- relational MCP receipts requiring stale discovery plus refreshed server truth, and for drift faults call-time failure/recovery as well;
- `MCPFaultReceipt` binding fault-material and exact canonical-observation digests without storing raw malicious text;
- fresh-server/fresh-cache isolation and second-call benign recovery where applicable;
- fresh official `MCPServerStdio` subprocess per bridged trial;
- rejection of preconfigured MCP servers, prefixed target naming, and local target-name collisions when they would make provenance ambiguous;
- negotiated MCP protocol verification from the connected session;
- dedicated `OpenAIAgentsMCPToolResultAdapter` for one exact `TOOL_RESULT_POISON` same-call bridge;
- exactly-one behavioral target-call requirement for that result bridge;
- exact OpenAI request/result call-ID pairing and logical output equivalence;
- `MCPAgentToolResultReceipt` binding scenario, protocol receipt, agent tool name, call ID, and model-visible output;
- `PROTOCOL_DELIVERY` ordered immediately before the matching result-bridge `TOOL_RESULT`;
- same-argument benign recovery through the same live MCP session only **after** the result-bridge behavioral run;
- dedicated `OpenAIAgentsMCPToolErrorRecoveryAdapter` for one exact `TOOL_ERROR` behavioral retry/recovery bridge;
- exactly-two behavioral target-call requirement for ToolError recovery;
- distinct stable first/retry OpenAI call IDs;
- canonical same-argument enforcement across error and retry calls;
- exact agent-visible ToolError observation bound to the verified protocol observation digest;
- exact expected/observed benign recovery binding;
- strict retry chronology `request₁ < result₁ < request₂ < result₂`, rejecting pre-issued or parallel second calls as unverified causality;
- `MCPAgentToolErrorRecoveryReceipt` binding scenario, protocol receipt, fault identity, call identities, argument digest, error observation, recovery observation, and a domain-separated root without serializing raw controlled content;
- ToolError `PROTOCOL_DELIVERY` ordered only after the recovery `TOOL_RESULT` because the full relation does not exist earlier;
- semantic revalidation of known `PROTOCOL_DELIVERY` receipt types before subject grading;
- separate content-addressed `MCPRemoteAuthPolicy` and `MCPRemoteAuthReceipt` domains;
- real pre-bound loopback TCP, Uvicorn, Streamable HTTP, and official-client execution for resource-server authorization;
- deterministic verifier-owned exact issuer/resource binding;
- MCP SDK bearer authentication/expiry and required-scope enforcement observed as real HTTP 401/403 responses;
- RFC 9728 protected-resource metadata fetched and verified over HTTP;
- bearer values excluded from remote-auth result/receipt serialization;
- separate content-addressed `MCPOAuthFlowPolicy` and `MCPOAuthFlowReceipt` domains;
- independent authorization-server and resource-server loopback origins;
- official OAuth client metadata discovery;
- Dynamic Client Registration only as compatibility fallback when no client registration is stored;
- OAuth `state`, PKCE `S256`, exact RFC 9207 authorization-response issuer validation, and RFC 8707 resource binding;
- authenticated HTTP token introspection from resource server to authorization server rather than direct shared-token-state verification;
- fail-closed introspection checks for activity, issuer, resource, client identity, expiration, and subject shape;
- protected `tools/list` and `tools/call` through the introspection-backed resource server;
- reconnect proof that stored authorization is reused without a second registration, authorization, or token exchange;
- credential exclusion from OAuth probe/receipt serialization;
- separate MCP protocol, resource-server auth, and OAuth-flow CI jobs;
- integrity-verified local evidence persistence and exact historical replay;
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

These are scoped implementations of generic threat channels, not claims of universal production control. The local `TOOL_RESULT` injector does not intercept MCP tools.

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

Every protocol probe gets a fresh server. Discovery probes get fresh cache state. Result/error faults are one-shot and recover. Drift receipts require recovery under refreshed truth.

The protocol laboratory proves protocol conditions. It does not infer agent behavior from them.

## MCP→OpenAI result security boundary

`OpenAIAgentsMCPToolResultAdapter` implements one specific verified result bridge, not an implicit promotion of protocol evidence.

### Provenance controls

The base Agent must have no preconfigured MCP servers. The target name must not collide with a local tool, and server-in-tool-name prefixing is rejected for this v1 path. The cloned trial Agent receives exactly one controlled MCP server.

These restrictions are security properties: they prevent the evaluator from correlating a valid call ID with the wrong tool/server provenance.

### Negotiation and behavioral-call controls

The connected MCP session must expose negotiated protocol `2026-07-28`. Configured protocol intent is not accepted as negotiated protocol evidence.

The agent must make exactly one target MCP call. Zero calls do not prove consumption. Multiple calls make result attribution ambiguous. Both conditions block grading.

The first target result must be one successful text content block matching the controlled fault. The protocol receipt is created from that actual result observation, not from fixture configuration.

### Bridge and recovery controls

After the run, normalized evidence must contain one exact target `TOOL_REQUEST`, a stable call ID, and one matching `TOOL_RESULT`.

`MCPAgentToolResultReceipt` binds the protocol receipt to the exact scenario/tool/call/output tuple. `PROTOCOL_DELIVERY` is inserted immediately before that matching result only after validation succeeds.

Recovery is then invoked using the same target, arguments, and still-connected MCP session. The result must equal the configured benign value. This ordering prevents a second benign result from contaminating the behavioral transcript while still checking that the fault is one-shot rather than sticky.

A result-bridge receipt therefore means: **the controlled protocol result and the result attributed to this agent call are the same evaluated delivery fact**. It does not mean the agent handled the content safely.

## MCP→OpenAI ToolError retry/recovery security boundary

`OpenAIAgentsMCPToolErrorRecoveryAdapter` implements one distinct behavioral resilience contract. Both target calls occur inside the agent run; the evaluator does not create the retry afterward.

### First-error provenance

The first target call must produce a real MCP error result with exactly one text block. `MCPFaultReceipt` is created from that actual observation and must identify `TOOL_ERROR`, protocol `2026-07-28`, the exact target tool, expected observation point, controlled payload digest, and SDK-generated error-envelope observation digest.

### Retry identity

The agent must make exactly two target calls. The normalized requests require stable, non-empty, distinct OpenAI call IDs. Each call ID must map to exactly one normalized result.

The original and retry arguments are canonicalized as finite JSON and must be identical. Changed arguments do not satisfy this exact recovery contract.

### Retry causality

The normalized evidence must satisfy:

```text
request₁ < result₁ < request₂ < result₂
```

This requirement prevents the evaluator from mislabeling two pre-issued identical calls as “error then retry.” A second call earns retry semantics only when the first agent-visible result precedes the second request in the trusted normalized chronology.

Failure of that relation becomes `mcp_error_retry_causality_unverified / EVALUATION_ERROR / BLOCKED`.

### Error/recovery binding

`MCPAgentToolErrorRecoveryReceipt` binds the verified protocol receipt, fault/tool identity, distinct call IDs, same-argument digest, agent-visible error digest, expected and observed recovery digests, and its own domain-separated root.

The receipt does not serialize raw controlled error content, raw retry arguments, or benign recovery text.

`PROTOCOL_DELIVERY` appears only after the second `TOOL_RESULT`. This is a security property: the receipt represents a four-event relation and cannot close before recovery is actually observed.

### Failure semantics

Missing first call, missing retry, extra target calls, changed retry arguments, reused/missing call IDs, ambiguous result identity, protocol drift, malformed error shape, model-visible error mismatch, recovery mismatch, malformed receipt, or non-causal ordering all remain evaluator uncertainty and block grading. They are not rewritten as subject failure.

## MCP resource-server authorization security boundary

`MCPRemoteAuthLab` tests resource-server behavior over **real loopback TCP Streamable HTTP**, not an in-process ASGI test client.

| Property | Owner in the laboratory |
|---|---|
| exact issuer match | deterministic `TokenVerifier` |
| exact resource match | deterministic `TokenVerifier` |
| bearer recognition / verifier acceptance | MCP SDK authentication middleware |
| token expiration | MCP SDK authentication middleware |
| required scopes | MCP SDK authorization middleware |
| RFC 9728 protected-resource metadata | MCP SDK protected-resource route |
| actual protected MCP request | official Streamable HTTP client over loopback TCP |

The matrix requires 401 for missing, unknown, expired, wrong-issuer, and wrong-resource credentials; 403 for an authenticated token missing required scope; correct protected-resource metadata; and successful protected tool discovery/call with a valid scoped bearer.

This proves resource-server enforcement only. It is not bridged into agent verdict evidence.

## MCP OAuth-flow security boundary

`MCPOAuthFlowLab` closes a separate authorization-client/authorization-server boundary over two independent loopback origins.

It verifies protected-resource and authorization-server metadata, compatibility registration fallback, state, PKCE `S256`, exact authorization-response issuer, resource indicators, code exchange, authenticated HTTP introspection, protected MCP use, and stored-authorization reuse.

The resource server does not directly read the authorization server's in-memory token dictionary. Introspection transport/HTTP/JSON failure, inactive token, issuer/resource/client mismatch, invalid expiration, or invalid subject fails closed.

Authorization code, access token, and introspection secret are omitted from serialized evidence. DCR is a compatibility fallback; CIMD is outside current scope.

## MCP security non-claims

Current MCP coverage does **not** establish:

- agent behavior for metadata poison, stale cache, schema drift, or identity drift;
- arbitrary MCP result or error behavior beyond the two exact controlled bridge contracts;
- generic retry/backoff/idempotency safety beyond one same-argument ToolError retry;
- arbitrary parallel target plans or multiple controlled MCP servers;
- OpenAI hosted MCP interception or third-party hosted MCP fidelity;
- remote/Internet MCP behavior or general stdio robustness beyond the exact deterministic subprocess paths;
- reverse proxy, gateway, TLS, DNS, service-mesh, packet, latency, disconnect, retry, or rate-limit assurance;
- third-party or production authorization-server / identity-provider assurance;
- production JWT/JWKS signature verification, key rotation, arbitrary token formats, federation, or IdP compromise resistance;
- Client ID Metadata Documents, Enterprise Managed Authorization, or SEP-990 identity-assertion assurance;
- DPoP, mTLS, certificate/token binding, hardware-backed keys, or other proof-of-possession mechanisms;
- refresh-token rotation, revocation propagation, replay detection, production credential storage/rotation, or distributed credential caches;
- public/cross-partition MCP cache sharing, arbitrary cache poisoning, notification invalidation, or TTL-expiry races;
- arbitrary schema migrations or arbitrary tool-registry churn beyond the exact fixtures;
- malformed framing/JSON-RPC, duplicate/out-of-order protocol responses, or header-routing faults;
- malicious MCP resources, prompts, roots, elicitation, sampling, subscriptions, or Tasks-extension behavior;
- full protocol-conformance certification;
- cryptographic target-side delivery attestation;
- release acceptance from any protocol/control-plane receipt alone.

## Runtime-context `ENVIRONMENT` security boundary

`ENVIRONMENT` is intentionally not process-global environment mutation. The adapter accepts only `None` or string-keyed `Mapping` context, snapshots it into a read-only trial-local overlay, and activates one adversarial key with task-local state during one targeted call.

Delivery requires actual value consumption through `ctx.context[key]` or `.get(key)`. Mere configuration, membership checks, or tool execution is insufficient.

The original caller mapping is not mutated. Later ordinary execution sees the original value.

This does not claim filesystem, browser, container, network, DNS, clock, secret-manager, credential, provider-config, cloud-IAM, database, service-mesh, or production-chaos coverage.

## Other OpenAI channel boundaries

- `USER_INPUT` proves controlled SDK input, not remote hosted-model processing.
- local `TOOL_RESULT` proves local copied-`FunctionTool` replacement, not MCP interception.
- local `TOOL_METADATA` changes description only, not schema/name/routing identity.
- SDK `MEMORY` is per-trial session history, not production memory or cross-user persistence.
- `RESOURCE` is inline structured file input, not File Search/RAG/MCP-resource assurance.
- `HANDOFF` poisons transferred context without rerouting the destination.

## Integrity is not attestation

`injector:<identity>`, MCP fault identities, bridge identities, remote-auth policy identities, and OAuth-flow policy identities are control-plane/content identities, not authenticated signer identities. Receipt/evidence roots are domain-separated integrity hashes, not signatures, MACs, trusted timestamps, or hardware attestation.

The public `MCPRemoteAuthProbeResult` and `MCPOAuthFlowProbeResult` models are diagnostic envelopes. Their embedded receipt identities are validated, but outer diagnostic fields are not independently cryptographically re-bound to those receipts.

A stronger deployment layer must separately address signer identity, trusted timestamps, tamper-resistant storage, transport authenticity, and independent target-side acknowledgements where required.

## Sensitive data

Adversarial, MCP, bridge, auth, and OAuth receipts minimize raw controlled content and credential material. Controlled boundaries necessarily expose the test stimulus or credential to the exact surface being tested. Normal redaction, minimization, retention, and access-control discipline still applies to tool outputs, protocol payloads, HTTP logs, OAuth client state, sessions, resource content, handoff context, and runtime application context.

## Deployment boundary

Application-level evaluation and deterministic loopback/stdio testing cannot by themselves prove process isolation, Internet transport security, secret-manager policy, production IAM, tenant isolation, sandbox containment, hosted MCP fidelity, production memory/retrieval integrity, distributed handoff correctness, third-party authorization-server security, or infrastructure fault behavior.

## Verified implementation checkpoint

Implementation source checkpoint `d98f9ca1feb1179504cd2181295a73936fd0ae6c`, protected-main CI run `33898508697`:

- deterministic core: **349 passed, 27 deselected**;
- branch coverage: **93.79%** against the 90% gate;
- strict mypy: **0 issues across 42 source files**;
- deterministic OpenAI SDK suite, including the original MCP stdio result bridge: **15/15 passed**;
- deterministic MCP protocol: **6/6 passed**;
- deterministic MCP remote auth: **3/3 passed**;
- deterministic MCP OAuth flow: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest**, Ruff, formatter, Bandit, dependency audit, package integrity, and all **7/7 CI jobs**: green;
- dependency audit: **no known vulnerabilities found**; the project package itself is skipped because it is not published on PyPI.

This checkpoint remains the historical audited merged implementation baseline. The ToolError-recovery bridge is accepted only after its own exact-head CI, merge, and post-merge `main` verification.

[← Documentation hub](README.md)
