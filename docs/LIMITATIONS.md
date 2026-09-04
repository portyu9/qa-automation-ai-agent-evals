# Limitations and Non-Claims

This document is intentionally strict. Repository claims must never become stronger than the executable evidence supporting them.

## Current non-claims

### No credentialed live-provider assurance yet

The OpenAI integration is pinned to `openai-agents==0.22.0`. CI exercises the real SDK runner/tool/handoff/context loop deterministically with `agents.testing.ScriptedModel` and no provider API call.

The SDK tier covers all seven generic adversarial channel categories at scoped local/SDK boundaries. A separate adapter also exercises one exact OpenAI-agent → official-MCP-stdio `TOOL_RESULT_POISON` path.

None of this establishes live-model quality, production-provider availability, provider-side delivery attestation, or credentialed end-to-end assurance.

Terminal application state remains independently observed; provider output is not the state oracle.

### Seven generic channels do not mean universal interception

`OpenAIAgentsAdapter` implements:

- `USER_INPUT` as the second ordered SDK user message;
- local `TOOL_RESULT` as first matching local `FunctionTool` result replacement;
- local description-level `TOOL_METADATA` on a copied `FunctionTool`;
- SDK session-history `MEMORY` through a fresh per-trial `Session`;
- structured inline-file `RESOURCE` through one `input_file` item;
- native `HANDOFF` context through the first actual SDK handoff filter invocation;
- local runtime-context `ENVIRONMENT` through one consumed key in trial-local `RunContextWrapper.context` during the first matching local `FunctionTool` call.

These are concrete implementations of a generic taxonomy, not assertions that every production system carrying a similarly named boundary is intercepted.

The dedicated `OpenAIAgentsMCPToolResultAdapter` is a separate integration and does not widen these seven local/SDK mechanisms.

### `ENVIRONMENT` means local SDK application context, not infrastructure chaos

The implemented environment mode requires an identity-bearing payload with `tool`, `key`, and `environment`. Complete canonical `AttackFixture.payload_json` becomes the injected value.

The adapter accepts only `None` or string-keyed `Mapping` runtime context. It snapshots base context into a read-only trial-local overlay and uses task-local activation during the first matching local tool invocation.

Delivery is **consumption-bound**. The receipt is created only when subject code reads the targeted value through `ctx.context[key]` or `.get(key)`. Merely creating the overlay, executing the tool, or checking key membership does not prove delivery.

This mode does not claim process-global `os.environ` mutation; filesystem/browser/container/sandbox faults; network latency/partition/DNS/outage behavior; clocks; secret managers; provider deployment configuration; Kubernetes/cloud IAM/service-mesh/database chaos; arbitrary non-`Mapping` context; external-system consumption; or production chaos engineering.

### Local `TOOL_RESULT` replacement remains local

The ordinary `OpenAIAgentsAdapter` result mode targets one exact local SDK `FunctionTool`. On the first matching call the original function is deliberately not executed; exact canonical fixture JSON becomes the result. Later calls use copied original behavior.

That local injector still does not intercept hosted tools, MCP tools, or arbitrary external services.

MCP result delivery is now covered only by the **separate** controlled stdio bridge described below. The existence of that bridge must not be retroactively attributed to the local `FunctionTool` injector.

### Local `TOOL_METADATA` means OpenAI description poisoning only

The OpenAI metadata mode changes only copied `FunctionTool.description`. It does not mutate tool name, parameter schema, callback, approval semantics, routing identity, hosted metadata, or external registries.

MCP description poisoning, schema drift, and identity drift exist in the protocol laboratory. They are not currently bridged into agent-trial behavior.

### SDK session-history `MEMORY` is not production memory poisoning

The memory mode uses a fresh per-trial client-side SDK `Session` and one prior user item. It does not claim application-owned production session mutation, provider-managed conversations, vector/RAG memory, semantic retrieval manipulation, cross-user persistence, or external memory lifecycle assurance.

### Structured inline-file `RESOURCE` is not retrieval-system poisoning

The resource mode places exact canonical fixture JSON in one structured SDK `input_file.file_data` field with evaluator-owned filename `agent-evals-resource.json`.

It does not claim OpenAI hosted File Search, vector stores, embeddings, RAG retrieval/ranking/chunking/filtering/citations, `file_id`, `file_url`, browser pages, databases, object stores, production document repositories, MCP resource servers, or provider-side file parsing/retention attestation.

### Native SDK `HANDOFF` is context poisoning, not rerouting

The handoff mode appends exact canonical fixture JSON to cloned context for the first actual SDK handoff invoking the run-level filter. The SDK-selected destination remains unchanged.

It does not choose a new destination, rewrite handoff routing metadata, poison every transfer, intercept remote/distributed agent fabrics, or attest provider-side consumption.

---

## MCP protocol laboratory remains protocol evidence by default

`MCPFaultLab` uses official `mcp==2.1.1`, a real in-process `MCPServer`, the official `Client`, and protocol revision `2026-07-28`.

Six exact fault families are implemented:

- target-tool description poisoning through `tools/list`;
- first-call target-tool result poisoning through `tools/call`;
- model-visible first-call `ToolError` containing the canonical payload in the SDK-generated envelope;
- private `tools/list` stale discovery after server-side target removal;
- tool-schema drift across cached discovery, current call validation, refresh, and recovery;
- tool-identity drift across cached discovery, stale lookup, refresh, and recovery.

`MCPFaultReceipt` binds fault identity, protocol version, tool, observation point, controlled fault-material digest, exact canonical-observation digest, and a receipt root without duplicating raw fault content.

A raw `MCPFaultReceipt` does **not** establish agent consumption, resistance, correctness, `PASS`, `FAIL`, or release acceptance.

Five of the six fault families remain **protocol-only** with respect to agent behavior:

- `tool_metadata_poison`;
- `tool_error`;
- `tool_list_stale_cache`;
- `tool_schema_drift`;
- `tool_identity_drift`.

The one exception is not an exception to the trust model; it is an explicit additional bridge contract for `tool_result_poison`.

## Controlled MCP `TOOL_RESULT_POISON` → OpenAI agent bridge

`OpenAIAgentsMCPToolResultAdapter` exercises one exact deterministic path through a fresh official MCP stdio server and the pinned OpenAI Agents SDK.

The bridge requires:

- a `TOOL_RESULT_POISON` fault only;
- fresh `MCPServerStdio` process/session state per trial;
- base Agent with no preconfigured MCP servers;
- no local tool collision with the target;
- unprefixed MCP target naming for unambiguous identity;
- negotiated protocol `2026-07-28` from the connected MCP session;
- exactly one behavioral target call;
- one successful target text result creating a valid `MCPFaultReceipt`;
- one exact normalized OpenAI target `TOOL_REQUEST` with stable call ID;
- one exact matching `TOOL_RESULT`;
- logical output equivalence across the protocol result and SDK model-visible tool result;
- one `MCPAgentToolResultReceipt` binding scenario, protocol receipt, tool, call ID, and agent output;
- `PROTOCOL_DELIVERY` ordered before the matching `TOOL_RESULT`;
- same-argument benign recovery through the same still-connected MCP session **after** the agent run.

The bridge therefore establishes a narrow evaluation precondition: the controlled MCP result and the result attributed to that exact agent tool call are the same evaluated delivery fact.

It does **not** establish that the agent behaved safely merely because delivery closed. Policy and outcome oracles still decide behavioral PASS/FAIL.

### The bridge is not generic MCP assurance

The implemented bridge does not claim:

- agent behavior for MCP metadata poison, `ToolError`, cache drift, schema drift, or identity drift;
- arbitrary multi-call or retry plans;
- multiple controlled MCP servers or parallel target calls;
- OpenAI hosted MCP interception;
- arbitrary third-party MCP servers;
- remote/Internet MCP fidelity;
- generic stdio transport correctness, subprocess isolation, or transport-chaos assurance beyond the exact deterministic fixture path;
- TLS, DNS, proxy, gateway, load-balancer, service-mesh, latency, disconnect, retry, or packet-fault behavior;
- production authorization or identity-provider behavior;
- target-side cryptographic delivery attestation.

The bridge test uses `agents.testing.ScriptedModel`. It does not make a live provider call.

### Raw protocol receipt still is not a verdict

The distinction is:

```text
MCPFaultReceipt only
    = verified protocol observation

MCPFaultReceipt
+ exact agent call identity
+ exact matching agent result
+ output equivalence
+ same-session recovery
    = verified MCPAgentToolResultReceipt / PROTOCOL_DELIVERY

verified PROTOCOL_DELIVERY
+ deterministic subject evidence
    = eligible for policy/outcome grading
```

Protocol evidence is necessary for this path but never sufficient for behavioral conclusions by itself.

---

## Loopback MCP resource-server authorization is not OAuth issuance assurance

`MCPRemoteAuthLab` binds a real `127.0.0.1` TCP socket, runs Uvicorn with an MCP Streamable HTTP app, exercises resource-server authorization, fetches RFC 9728 protected-resource metadata, and completes an authenticated MCP request through the official client transport.

The deterministic matrix covers missing/unknown/expired/wrong-issuer/wrong-resource bearer rejection, missing-scope 403, and successful protected discovery/call for a valid scoped bearer.

Issuer/resource binding belongs to the deterministic `TokenVerifier`; bearer/expiry and required-scope handling are credited to the MCP SDK middleware.

`MCPRemoteAuthReceipt` binds the exact content-addressed policy and canonical observation. Deterministic bearer values are excluded from serialized result/receipt evidence.

This laboratory does not itself establish authorization-code/PKCE, client registration, token issuance, token introspection, agent behavior, or release acceptance.

It also does not establish production JWT/JWKS verification, DPoP/mTLS, refresh/revocation, replay detection, Internet transport, hosted MCP fidelity, production IAM, or authorization-server/IdP assurance.

## Separated loopback MCP OAuth flow is not production identity assurance

`MCPOAuthFlowLab` uses the official MCP `OAuthClientProvider` and independent loopback authorization-server/resource-server origins.

The deterministic flow closes RFC 9728 protected-resource discovery, authorization-server metadata, compatibility Dynamic Client Registration fallback, OAuth state, PKCE `S256`, exact RFC 9207 issuer validation, RFC 8707 resource binding, authorization-code exchange, opaque access-token issuance, authenticated HTTP introspection, fail-closed introspection policy, protected MCP use, and stored-authorization reuse on reconnect.

The resource-server verifier does not directly consult the authorization server's in-memory token table. Authorization code, access token, and introspection secret are excluded from serialized evidence.

This remains a deterministic loopback laboratory. It does not establish third-party/production IdP behavior, CIMD, enterprise-managed authorization, production JWT/JWKS/federation, DPoP/mTLS, refresh/revocation/replay lifecycle, browser consent/anti-phishing properties, production RFC 7662 interoperability, production IAM/tenant isolation, agent behavior after OAuth success/failure, or release acceptance from OAuth evidence alone.

Dynamic Client Registration is compatibility fallback behavior, not the preferred modern enrollment claim.

---

### Approval requests are not approvals

SDK `ToolApprovalItem` observations normalize as `APPROVAL_REQUEST`, never `APPROVAL`. Privileged execution requires independent authorization evidence.

### No semantic/model grader yet

The framework does not currently use a model-as-judge. Deterministic state and policy authority remain primary. A future semantic grader requires calibration, provenance, explicit failure semantics, and non-overriding precedence relative to critical deterministic failures.

### Delivery and protocol receipts are not target-side attestation

A valid OpenAI attack receipt proves consistency relative to the trusted evaluator's controlled observation. `MCPFaultReceipt` proves consistency relative to a trusted protocol observation. `MCPAgentToolResultReceipt` proves consistency between one verified MCP result and one exact normalized OpenAI agent call/result boundary. `MCPRemoteAuthReceipt` and `MCPOAuthFlowReceipt` prove their respective deterministic loopback observations.

None is independent cryptographic proof that an arbitrary remote target consumed content, a production issuer minted a token correctly, or a deployed agent respected policy.

Control-plane identities are labels/content identities, not authenticated signer identities. Receipt roots are SHA-256 integrity values, not signatures, MACs, trusted timestamps, or hardware attestation.

The public `MCPRemoteAuthProbeResult` and `MCPOAuthFlowProbeResult` envelopes are diagnostic result models, not persisted authenticated evidence envelopes. Their embedded receipt identities are validated, but independently changing an outer diagnostic field does not cryptographically re-bind that field to the receipt.

### Local persistence is not hostile-writer authentication

`LocalEvidenceStore` revalidates manifests, payload hashes, identities, evidence schema, semantic roots, symlink/file constraints, and no-clobber publication behavior. It does not authenticate a writer who can coherently replace all controlled files and recompute ordinary hashes.

The repository does not claim signatures/MACs, key management, trusted timestamps, remote attestation, WORM/object-lock storage, transparency-log anchoring, or cross-host durable retention.

### Replay is historical regrading, not re-execution

`EvidenceReplayAdapter` requires exact trial/subject/scenario identity and can reapply deterministic grading to recorded evidence. It does not rerun providers, tools, sessions, resources, handoffs, environment injectors, the MCP stdio bridge, protocol probes, authorization probes, OAuth flows, or external state readers and cannot establish fresh delivery or fresh authorization.

### Assurance-report validation is not signed attestation

`AssuranceReport` rederives verdict consistency, reliability, critical-violation counts, release-gate output, and report root. The report root is integrity, not authenticated writer identity.

### No formal non-inferiority test

Paired comparison uses an exact McNemar/binomial test for directional improvement/regression. Failure to detect significant regression is **not** formal non-inferiority.

### `pass@k` / `pass^k` are empirical approximations

Current formulas use observed resolved success proportion and an independent-attempt interpretation. Correlated, adaptive, or non-stationary trials can violate that approximation. `BLOCKED` and `INCONCLUSIVE` remain separate uncertainty.

### Resource-prefix policy is lexical

Resource scope uses string-prefix matching after adapter normalization. Real deployments must canonicalize aliases, traversal, case, URL forms, and alternate identifiers before lexical prefix comparison can represent the intended security boundary.

### No sandbox-isolation claim

The repository currently executes only controlled deterministic fixture subprocesses; it does not claim containment for arbitrary target-controlled code. Any future arbitrary-code executor must separately validate process, filesystem, and network isolation.

## Audited implementation checkpoint

Audited merged implementation source checkpoint `d98f9ca1feb1179504cd2181295a73936fd0ae6c`, CI run `33898508697`:

- deterministic core: **349 passed, 27 deselected**;
- branch coverage: **93.79%** against the 90% gate;
- strict mypy: **0 issues across 42 source files**;
- deterministic OpenAI SDK suite, including controlled MCP stdio bridge coverage: **15/15 passed**;
- deterministic MCP protocol suite: **6/6 passed**;
- deterministic MCP remote-auth suite: **3/3 passed**;
- deterministic MCP OAuth-flow suite: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest** quality jobs, Ruff, formatter, Bandit, dependency audit, package integrity, and all **7/7 CI jobs**: green;
- dependency audit reported **no known vulnerabilities**; the project package itself is skipped because it is not published on PyPI.

This checkpoint identifies the audited merged implementation revision before this documentation-only synchronization. The documentation change must pass its own full PR CI; it does not retroactively relabel implementation evidence.

## Why these boundaries matter

Agent evaluation is unusually vulnerable to false confidence because outputs can look persuasive while surrounding state, authority, evaluator preconditions, protocol discovery, authorization boundaries, identity-flow assumptions, or cross-domain correlation are wrong.

The same discipline applies to this framework: documentation, badges, hashes, attack labels, protocol receipts, bridge receipts, HTTP statuses, OAuth responses, and traces are not substitutes for the exact control they describe.

Capabilities move out of this document only after implementation, deterministic evidence, and documentation review make the stronger claim true.
