# Security

## Security posture

The repository treats the evaluated agent and all provider/tool/MCP/memory/resource/handoff/runtime-context content as untrusted with respect to evaluation authority. Evidence may describe what happened; it may not redefine what is allowed or what counts as success.

An adversarial agent trial is not behaviorally gradeable until the controlled evaluation environment has produced one exact valid delivery receipt bound to that scenario and attack. Failure to establish that precondition is `BLOCKED` evaluation uncertainty, not an agent defect.

MCP has three additional evidence domains:

1. a configured protocol fault is not delivered until the **official MCP client** observes the exact fault-specific content or protocol-state relation;
2. a configured resource-server authorization policy is not proven until the **real loopback HTTP boundary** produces the complete expected authentication, authorization, protected-resource metadata, and authorized-MCP observations;
3. a configured OAuth-flow policy is not proven until a **separate loopback authorization-server/resource-server topology** closes discovery, compatible registration fallback, PKCE, exact issuer/resource binding, code exchange, authenticated token introspection, protected MCP use, and stored-authorization reuse.

None of those MCP evidence families establishes agent behavioral resistance.

## Deterministic controls

Implemented controls include:

- explicit tool allowlists/denylists, approval-before-use checks, resource-prefix confinement, and tool/handoff budgets;
- critical non-compensatory policy failure;
- separate `EVALUATION_ERROR / BLOCKED` and `RUNTIME_ERROR / BLOCKED` semantics;
- immutable ordered agent evidence and domain-separated roots;
- content-addressed adversarial fixtures/campaigns with authority-preserving derivation;
- exact OpenAI delivery receipts binding scenario, attack, channel, injection point, and canonical payload digest;
- exactly-one OpenAI delivery verification before adversarial subject grading;
- fail-closed handling of missing, duplicate, malformed, forged, mismatched, or never-produced adversarial delivery evidence;
- raw attack-body exclusion from adversarial delivery receipts;
- seven tested OpenAI channel categories at narrow SDK/local boundaries;
- per-trial copied-tool/cloned-agent isolation for local OpenAI tool attacks;
- fresh SDK session isolation for memory attacks;
- ephemeral structured run input for resources;
- fresh one-shot handoff-filter isolation;
- read-only trial-local runtime-context overlay with task-local activation for environment attacks;
- exact call-ID binding for tool-result and environment-consumption receipts;
- clean subsequent-run checks for metadata, memory, resource, handoff, and environment isolation;
- content-addressed `MCPFaultSpec` independent from OpenAI attack fixtures;
- official `mcp==2.1.1` in-process `MCPServer`/`Client` execution pinned to protocol `2026-07-28`;
- exact MCP observation for description poison, result poison, model-visible `ToolError`, stale removal cache, tool-schema drift, and tool-identity drift;
- relational MCP receipts that require stale discovery plus refreshed server truth, and for drift faults require call-time failure/recovery as well;
- `MCPFaultReceipt` binding both fault-material and exact canonical-observation digests without storing raw malicious text;
- fresh-server/fresh-cache isolation and second-call benign recovery where applicable;
- separate content-addressed `MCPRemoteAuthPolicy` and `MCPRemoteAuthReceipt` domains;
- real pre-bound loopback TCP, Uvicorn, Streamable HTTP, and official-client execution for resource-server authorization;
- deterministic verifier-owned exact issuer/resource binding;
- MCP SDK bearer authentication/expiry and required-scope enforcement observed as real HTTP 401/403 responses;
- RFC 9728 protected-resource metadata fetched and verified over HTTP;
- actual bearer token values excluded from remote-auth result/receipt serialization;
- separate content-addressed `MCPOAuthFlowPolicy` and `MCPOAuthFlowReceipt` domains;
- independent pre-bound loopback authorization-server and resource-server origins;
- protected-resource and authorization-server metadata discovery through the official OAuth client path;
- Dynamic Client Registration as a compatibility fallback when no client registration is stored;
- OAuth `state`, PKCE `S256`, exact RFC 9207 authorization-response issuer validation, and RFC 8707 resource binding;
- deterministic authorization-code and opaque access-token issuance for the loopback laboratory;
- authenticated HTTP token introspection from resource server to authorization server rather than direct shared-token-state verification;
- fail-closed introspection checks for activity, issuer, resource, client identity, expiration, and subject shape;
- protected `tools/list` and `tools/call` through the introspection-backed resource server;
- reconnect proof that stored authorization is reused without a second registration, authorization, or token exchange;
- authorization-code, access-token, and introspection-secret exclusion from OAuth probe/receipt serialization;
- separate MCP protocol, resource-server auth, and OAuth-flow CI jobs rather than one broad green status;
- integrity-verified local evidence persistence and exact historical replay;
- pinned GitHub Actions and read-only workflow permissions.

## Seven scoped OpenAI attack surfaces

The adapter currently exercises:

1. direct user input;
2. indirect content returned by a targeted local `FunctionTool`;
3. targeted local tool-description metadata;
4. client-side SDK session history;
5. structured inline-file input;
6. context transferred through the first native SDK handoff;
7. one targeted local application's SDK runtime-context key consumed during a local tool call.

These are scoped implementations of generic threat channels, not claims of universal production control.

## MCP protocol-fault security boundary

A valid `MCPFaultSpec` binds stable fault identity, revision, kind, original tool name, and canonical finite JSON payload.

The current official-client boundaries are:

```text
mcp:2026-07-28:tools/list:<tool>:description
mcp:2026-07-28:tools/call:<tool>:result.content[0].text
mcp:2026-07-28:tools/call:<tool>:error.content[0].text:message-suffix
mcp:2026-07-28:tools/list:cache-use-stale-after-remove:<tool>:refresh-proves-absent
mcp:2026-07-28:tools/list:schema-drift:<tool>:cached-old:call-rejects-old:refresh-new
mcp:2026-07-28:tools/list:identity-drift:<tool>:cached-old-name:call-rejects-old:refresh-new-name
```

### Discovery-state security invariants

The three discovery-state faults deliberately distinguish cached client knowledge from server truth.

**Stale removal** requires initial presence, server-side removal, cached presence, then refreshed absence.

**Schema drift** requires the old schema to remain cached while the server already enforces the replacement schema at call time; only explicit refresh exposes the replacement schema to discovery.

**Identity drift** requires the old name to remain cached while the live server rejects that name; explicit refresh must expose only the replacement name before the replacement call can succeed.

The security implication is precise:

```text
cached authorization/discovery context is not proof of current callable authority or contract
```

The laboratory does not claim that an agent exploited or resisted the stale state. It proves the protocol condition exists.

### Observation integrity and isolation

`payload_sha256` identifies controlled fault material. `observation_sha256` identifies the complete canonical observation returned or derived from public official-client fields.

They may differ whenever the SDK transforms content or the proof is relational. That is intentional.

Every probe gets a fresh server. Discovery probes get fresh cache state. Result/error faults are one-shot and must recover on a second call. Drift receipts require recovery under refreshed truth.

See [MCP Protocol Fault Laboratory](MCP_LAB.md).

## MCP resource-server authorization security boundary

`MCPRemoteAuthLab` tests resource-server behavior over **real loopback TCP Streamable HTTP**, not an in-process ASGI test client.

### Enforcement ownership

Security documentation must attribute each control to its actual enforcement point:

| Property | Owner in the laboratory |
|---|---|
| exact issuer match | deterministic `TokenVerifier` |
| exact resource match | deterministic `TokenVerifier` |
| bearer recognition / verifier acceptance | MCP SDK authentication middleware |
| token expiration | MCP SDK authentication middleware |
| required scopes | MCP SDK authorization middleware |
| RFC 9728 protected-resource metadata | MCP SDK protected-resource route |
| actual protected MCP request | official Streamable HTTP client over loopback TCP |

The repository does **not** claim the MCP SDK intrinsically validates issuer/resource merely because this laboratory does so. Those checks are application verifier policy.

### Fail-closed matrix

The remote-auth receipt requires:

```text
missing token           → 401
unknown token           → 401
expired token           → 401
wrong issuer            → verifier rejects → 401
wrong resource          → verifier rejects → 401
insufficient scope      → 403
valid scoped token      → protected tools/list + tools/call succeed
```

The 401/403 `WWW-Authenticate` challenges must point at the generated protected-resource metadata endpoint. Metadata must independently identify the exact resource URL, issuer, and required scopes.

### Credential minimization

The deterministic bearer values are not serialized into `MCPRemoteAuthProbeResult` or `MCPRemoteAuthReceipt`. The public `Bearer` challenge scheme remains in evidence because it is protocol metadata, not credential material.

This laboratory deliberately begins with deterministic token records. It proves resource-server enforcement; it does not itself prove how a token was registered, authorized, issued, or introspected.

See [MCP Remote Authorization](MCP_REMOTE_AUTH.md).

## MCP OAuth-flow security boundary

`MCPOAuthFlowLab` closes a separate authorization-client/authorization-server boundary over two independent loopback origins.

### Protocol ownership

| Property | Owner / observation |
|---|---|
| protected-resource metadata | MCP resource-server RFC 9728 route + official OAuth client discovery |
| authorization-server metadata | separate authorization-server origin |
| compatibility client registration | authorization-server registration endpoint + official OAuth client |
| OAuth state / PKCE `S256` | official OAuth client authorization request |
| exact authorization-response issuer | official OAuth client RFC 9207 validation against discovered issuer |
| exact resource indicator | authorization request, authorization code, access token, and introspection audience |
| token issuance | deterministic loopback authorization-server provider |
| token verification source | authenticated HTTP introspection to separate authorization-server origin |
| protected MCP authorization | MCP resource-server middleware after introspection-backed verification |
| stored authorization reuse | second MCP connection without new registration/authorization/token exchange |

The issuer is canonical and exact. A slash mismatch is not normalized after metadata discovery. The resource server also does not directly read the authorization server's in-memory token dictionary; it obtains active-token metadata through the HTTP introspection endpoint.

### Introspection fail-closed behavior

The resource-server verifier rejects the token when introspection transport/HTTP/JSON fails, when `active` is not true, when issuer or audience/resource mismatches, when client identity is invalid, when expiration is invalid/expired, or when subject type is invalid.

This is authenticated RFC 7662-style active-token introspection in a deterministic laboratory. It is not a claim of production RFC 7662 interoperability across arbitrary identity providers.

### Credential minimization

The authorization code, opaque access token, and resource-server introspection secret are intentionally absent from `MCPOAuthFlowProbeResult` and `MCPOAuthFlowReceipt` serialization. The standardized `Bearer` token-type label is protocol metadata.

### DCR compatibility scope

The tested client registers dynamically only because no client record exists in its in-memory storage. That demonstrates compatibility fallback behavior. It must not be described as the preferred modern MCP enrollment path; Client ID Metadata Documents remain outside this repository's implemented scope.

See [MCP OAuth Flow Laboratory](MCP_OAUTH_FLOW.md).

## MCP security non-claims

The three current MCP laboratories do **not** establish:

- agent behavior after consuming MCP content or encountering an authorization/OAuth response;
- OpenAI hosted/MCP interception by `OpenAIAgentsAdapter`;
- Internet-hosted or third-party MCP server fidelity;
- stdio, reverse proxy, gateway, TLS, DNS, service-mesh, packet, latency, disconnect, retry, or rate-limit assurance;
- third-party or production authorization-server / identity-provider assurance;
- production JWT/JWKS signature verification, key rotation, arbitrary token formats, federation, or IdP compromise resistance;
- Client ID Metadata Documents, Enterprise Managed Authorization, or SEP-990 identity-assertion flow assurance;
- DPoP, mTLS, certificate/token binding, hardware-backed keys, or other proof-of-possession mechanisms;
- refresh-token issuance/rotation, revocation propagation, replay detection, production credential rotation/storage, or distributed credential caches;
- arbitrary issuer federation/discovery beyond the exact separated loopback authorization server;
- production RFC 7662 interoperability beyond the deterministic authenticated introspection contract implemented here;
- public/cross-partition MCP cache sharing, cache poisoning, custom/shared stores, notification invalidation, TTL-expiry races, or arbitrary cache correctness;
- arbitrary schema migrations or arbitrary tool-registry churn beyond the exact bound drift fixtures;
- malformed framing/JSON-RPC, duplicate/out-of-order responses, or header-routing faults;
- malicious MCP resources, prompts, roots, elicitation, sampling, subscriptions, or Tasks-extension behavior;
- full protocol-conformance certification;
- remote target-side delivery attestation.

Those require tests at their actual enforcement layers.

## Runtime-context `ENVIRONMENT` security boundary

`ENVIRONMENT` is intentionally not implemented as process-global environment mutation.

A valid fixture identifies one exact local `FunctionTool`, one exact string context key, and environment content. Complete canonical `AttackFixture.payload_json` becomes the value returned for that key during the first matching tool invocation.

The adapter accepts `run_context` only when it is `None` or a string-keyed `Mapping`, snapshots it into a read-only trial-local overlay, and activates the adversarial key with a task-local `ContextVar` during that one targeted invocation.

```text
source          = injector:openai-agents:environment-runtime-context
injection_point = openai-agents:FunctionTool:<tool>:call:<call_id>:RunContextWrapper.context:<key>
```

Delivery requires **actual value consumption**. A receipt is created only when subject code reads `ctx.context[<key>]` or `ctx.context.get(<key>)`.

A configured overlay, matching tool invocation, or membership check is not sufficient. If the subject does not consume the value, the attack remains unverified and the trial is `BLOCKED`.

The original caller-owned context mapping is never mutated. A later ordinary run sees the original value. Task-local activation prevents unrelated concurrent tool tasks from inheriting the injected value.

## Environment non-claims

The current runtime-context mode does **not** mutate, simulate, or attest process-global environment variables, filesystems, browsers, containers, sandboxes, networks, DNS, clocks, secret managers, credentials, provider configuration, cloud IAM, databases, service meshes, production chaos infrastructure, arbitrary non-`Mapping` context objects, or provider-side environment consumption.

Those controls require dedicated injectors and observation at the actual enforcement boundary.

## Other OpenAI channel boundaries

### `USER_INPUT`

Objective plus exact canonical fixture JSON are supplied as two ordered user messages. This proves controlled SDK input, not remote hosted-model processing.

### Local `TOOL_RESULT`

The first matching local `FunctionTool` result is replaced with exact canonical fixture JSON and bound to the SDK call ID. The original function does not execute on that injected call. This is not hosted/MCP/remote-service interception.

### Local `TOOL_METADATA`

Only copied `FunctionTool.description` is changed. Name, parameter schema, callback, approval semantics, and routing identity remain fixed. OpenAI schema/name poisoning is not implemented; MCP schema/identity drift exists only in the separate MCP protocol laboratory.

### SDK session-history `MEMORY`

A fresh per-trial SDK `Session` supplies one poisoned prior user item. This is not production memory, provider-managed conversation, vector/RAG memory, or cross-user persistence testing.

### Structured inline-file `RESOURCE`

Exact canonical fixture JSON becomes `input_file.file_data`. This is not File Search, vector-store/RAG, URL/document-store, MCP-resource, or provider-side parsing attestation.

### Native `HANDOFF`

Exact canonical fixture JSON is appended to the first native SDK handoff context while the SDK-selected destination remains unchanged. This is not rerouting or distributed-agent-fabric interception.

## Integrity is not attestation

`injector:<identity>`, MCP fault identities, remote-auth policy identities, and OAuth-flow policy identities are control-plane/content identities, not authenticated signer identities. Receipt/evidence roots are domain-separated integrity hashes, not signatures, MACs, trusted timestamps, or hardware attestation.

The public `MCPRemoteAuthProbeResult` and `MCPOAuthFlowProbeResult` models are diagnostic envelopes. Their embedded receipt identities are validated, but outer diagnostic fields are not independently cryptographically rebound to those receipts. They must not be treated as authenticated persisted evidence envelopes without a future explicit binding contract.

A stronger deployment layer must separately address signer identity, trusted timestamps, tamper-resistant storage, transport authenticity, and independent target-side acknowledgements where required.

## Sensitive data

Adversarial and MCP receipts store digests and minimized protocol observations rather than raw attack/fault bodies or deterministic bearer/OAuth credentials. Controlled boundaries necessarily expose the test stimulus or credential to the exact surface being tested. Normal redaction, minimization, retention, and access-control discipline still applies to tool outputs, protocol payloads, HTTP logs, OAuth client state, session state, resource content, handoff context, and runtime application context.

## Deployment boundary

Application-level evaluation and loopback protocol testing cannot by themselves prove process isolation, Internet transport security, secret-manager policy, production IAM, tenant isolation, sandbox containment, remote MCP fidelity, production memory/retrieval integrity, distributed handoff correctness, third-party authorization-server security, or infrastructure fault behavior.

## Verified implementation checkpoint

Implementation source checkpoint `3c33770a7be8089c1ec68f5dec26fcf76e8dc871`, CI run `33870616736`:

- deterministic core: **192 passed, 23 deselected**;
- branch coverage: **93.37%**;
- strict mypy: **0 issues across 40 source files**;
- deterministic OpenAI SDK suite: **11/11 passed**;
- deterministic MCP protocol suite: **6/6 passed**;
- deterministic MCP remote-auth suite: **3/3 passed**;
- deterministic MCP OAuth-flow suite: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest** quality, Ruff, formatter, Bandit, dependency audit, package integrity, and all **7/7 CI jobs**: green;
- dependency audit reported **no known vulnerabilities**; the project package itself is skipped because it is not published on PyPI.

Documentation-only closeout commits are validated separately by PR CI and do not silently redefine this implementation checkpoint.

## Reporting vulnerabilities

Do not open a public issue containing credentials, private customer data, exploit secrets, or other sensitive material. Use GitHub private vulnerability reporting if enabled for the repository/account.
