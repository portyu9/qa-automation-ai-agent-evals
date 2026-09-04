# Limitations and Non-Claims

This document is intentionally strict. The repository should never become more impressive in prose than it is in executable evidence.

## Current non-claims

### No credentialed live-provider assurance yet

A first-class OpenAI Agents SDK adapter is pinned to `openai-agents==0.22.0`, and CI exercises the real SDK runner/tool/handoff/context loop deterministically with `agents.testing.ScriptedModel` and no provider API call.

The SDK tier covers all seven generic adversarial channel categories at scoped local/SDK boundaries. It does **not** establish live-model quality, production-provider availability, provider-side delivery attestation, or credentialed end-to-end assurance.

Terminal application state remains independently observed; provider output is not the state oracle.

### Seven generic channels do not mean universal interception

`OpenAIAgentsAdapter` currently implements:

- `USER_INPUT` as the second ordered SDK user message;
- local `TOOL_RESULT` as first matching local `FunctionTool` result replacement;
- local description-level `TOOL_METADATA` on a copied `FunctionTool`;
- SDK session-history `MEMORY` through a fresh per-trial `Session`;
- structured inline-file `RESOURCE` through one `input_file` item;
- native `HANDOFF` context through the first actual SDK handoff filter invocation;
- local runtime-context `ENVIRONMENT` through one consumed key in trial-local `RunContextWrapper.context` during the first matching local `FunctionTool` call.

These are concrete implementations of a generic taxonomy, not assertions that every production system carrying a similarly named boundary is intercepted.

### `ENVIRONMENT` means local SDK application context, not infrastructure chaos

The implemented environment mode requires an identity-bearing payload with `tool`, `key`, and `environment`. Complete canonical `AttackFixture.payload_json` becomes the injected value.

The adapter accepts only `None` or string-keyed `Mapping` runtime context for this mode. It snapshots base context into a read-only trial-local overlay and uses task-local `ContextVar` activation during the first matching local tool invocation.

Delivery is **consumption-bound**. The receipt is created only when subject code reads the targeted value through `ctx.context[key]` or `.get(key)`. Merely creating the overlay, executing the tool, or checking key membership does not prove delivery. A target tool that never reads the key leaves the adversarial trial `BLOCKED`.

This mode does **not** claim process-global `os.environ` mutation; filesystem/browser/container/sandbox faults; network latency/partition/DNS/outage behavior; clocks; secret managers; provider deployment configuration; Kubernetes/cloud IAM/service-mesh/database chaos; arbitrary non-`Mapping` context; external-system consumption; or production chaos engineering.

### Local `TOOL_RESULT` replacement is not hosted/MCP interception

The current OpenAI result mode targets one exact local SDK `FunctionTool`. On the first matching call the original function is deliberately not executed; exact canonical fixture JSON becomes the result. Later calls use copied original behavior.

It does not claim hosted/MCP/external-server interception, generic support for every SDK tool type, preservation of original first-call side effects, or execute-then-perturb semantics.

The separate MCP laboratories exercise protocol surfaces directly; they do not turn this OpenAI local-tool mode into MCP interception.

### Local `TOOL_METADATA` means OpenAI description poisoning only

The OpenAI metadata mode changes only copied `FunctionTool.description`. It does not mutate OpenAI tool name, parameter schema, callback, approval semantics, routing identity, hosted metadata, or external registries.

MCP description poisoning, schema drift, and identity drift exist only in the separate MCP protocol laboratory and do not imply equivalent OpenAI adapter capability.

### SDK session-history `MEMORY` is not production memory poisoning

The memory mode uses a fresh per-trial client-side SDK `Session` and one prior user item. It does not claim application-owned production session mutation, provider-managed conversations, vector/RAG memory, semantic retrieval manipulation, cross-user persistence, or external memory lifecycle assurance.

### Structured inline-file `RESOURCE` is not retrieval-system poisoning

The resource mode places exact canonical fixture JSON in one structured SDK `input_file.file_data` field with evaluator-owned filename `agent-evals-resource.json`.

It does not claim OpenAI hosted File Search, vector stores, embeddings, RAG retrieval/ranking/chunking/filtering/citations, `file_id`, `file_url`, browser pages, databases, object stores, production document repositories, MCP resource servers, or provider-side file parsing/retention attestation.

The separate `resource_resolver(tool_name, arguments)` callback is only a deterministic policy resource-identity normalizer.

### Native SDK `HANDOFF` is context poisoning, not rerouting

The handoff mode appends exact canonical fixture JSON to cloned context for the first actual SDK handoff invoking the run-level filter. The SDK-selected destination remains unchanged.

It does not choose a new destination, rewrite handoff routing metadata, poison every transfer, intercept remote/distributed agent fabrics, or attest provider-side consumption.

## MCP protocol fault laboratory is protocol evidence, not agent assurance

The repository includes a deterministic MCP protocol fault laboratory using official `mcp==2.1.1`, a real in-process `MCPServer`, the official `Client`, and protocol revision `2026-07-28`.

Six exact fault families are implemented:

- target-tool description poisoning through `tools/list`;
- first-call target-tool result poisoning through `tools/call`;
- model-visible first-call `ToolError` containing the canonical payload in the SDK-generated envelope;
- private `tools/list` stale discovery after server-side target removal, closed only by initial-present → cached-present → refreshed-absent evidence;
- tool-schema drift, closed only by initial old schema → cached old schema → old-argument call rejection under current server truth → refreshed new schema → successful new-schema call;
- tool-identity drift, closed only by initial old name → cached old name → stale-name call rejection → refreshed replacement name → successful replacement call.

Every probe uses a fresh server. Discovery-state probes use fresh client cache state. Result/error faults require benign recovery, while drift faults require successful operation after refresh.

`MCPFaultReceipt` binds fault identity, protocol version, tool, observation point, controlled fault-material digest, exact canonical-observation digest, and a receipt root without duplicating raw fault content.

That implementation does **not** establish:

- an autonomous agent receiving, interpreting, exploiting, or resisting the MCP condition;
- OpenAI `ATTACK_DELIVERY` semantics for MCP;
- public/cross-partition cache sharing, cache poisoning, custom/shared cache stores, notification invalidation, TTL-expiry races, or general cache correctness outside the exact implemented relations;
- arbitrary schema migration beyond the bound v1 before/after schema pair;
- arbitrary registry churn beyond the single bound replacement-name relation;
- malformed JSON-RPC/framing, duplicate/out-of-order responses, or `Mcp-Method`/`Mcp-Name` routing faults;
- malicious resources, resource templates, prompts, roots, elicitation, sampling, subscriptions, or Tasks-extension behavior;
- hosted third-party MCP fidelity or complete protocol-conformance certification;
- target-side delivery attestation.

Protocol observation is therefore not promoted to agent `PASS`, `FAIL`, release `ACCEPT`, or any equivalent behavioral conclusion.

See [MCP Protocol Fault Laboratory](MCP_LAB.md).

## Loopback MCP remote authorization is not production identity assurance

The repository also includes a separate `MCPRemoteAuthLab` that binds a real `127.0.0.1` TCP socket, runs Uvicorn with an MCP Streamable HTTP app, exercises HTTP authorization, fetches RFC 9728 protected-resource metadata, and completes an authenticated MCP request through the official client transport.

The deterministic matrix covers:

- missing token → 401;
- unknown token → 401;
- expired token → 401;
- wrong issuer → deterministic verifier rejects → 401;
- wrong resource → deterministic verifier rejects → 401;
- authenticated token missing a required scope → MCP SDK authorization middleware returns 403;
- valid scoped bearer → protected `tools/list` and `tools/call` succeed.

The laboratory deliberately separates control ownership: issuer/resource binding belongs to its deterministic `TokenVerifier`; bearer/expiry and required-scope handling belong to the MCP SDK middleware. RFC 9728 metadata is fetched over HTTP rather than inferred from configuration.

`MCPRemoteAuthReceipt` binds the exact content-addressed policy and complete canonical observation. Actual deterministic bearer values are excluded from serialized result/receipt evidence.

This implementation does **not** establish:

- a real authorization server issuing access tokens;
- authorization-code/PKCE, Dynamic Client Registration, CIMD, SEP-990, or other complete OAuth flow assurance;
- real JWT signature/JWKS verification, token introspection, federation, or production IdP behavior;
- issuer compromise resistance or arbitrary issuer-discovery semantics;
- DPoP, mTLS, certificate binding, hardware-backed keys, proof-of-possession, refresh/revocation lifecycle, or replay detection;
- production credential rotation/storage or distributed token caches;
- cross-service credential-reuse resistance beyond the exact deterministic resource binding tested by the fixture;
- TLS, DNS, reverse proxies, load balancers, gateways, service meshes, cross-host routing, Internet transport, or hosted MCP fidelity;
- malformed HTTP, disconnect, timeout, retry, rate-limit, packet, or transport-chaos coverage;
- production IAM or authorization-server/IdP assurance;
- agent behavior after auth success or rejection.

Calling this boundary `streamable-http-loopback` is intentional. It must not be described as Internet or production remote-auth assurance.

See [MCP Remote Authorization](MCP_REMOTE_AUTH.md).

### Approval requests are not approvals

SDK `ToolApprovalItem` observations normalize as `APPROVAL_REQUEST`, never `APPROVAL`. Privileged execution requires independent authorization evidence.

### No semantic/model grader yet

The current framework does not use a model-as-judge. Deterministic state and policy authority remain primary. A future semantic grader requires calibration, provenance, explicit failure semantics, and non-overriding precedence relative to critical deterministic failures.

### Delivery receipts are not target-side attestation

A valid OpenAI attack receipt proves consistency relative to the trusted evaluator's controlled observation. `MCPFaultReceipt` proves consistency relative to the official-client protocol observation. `MCPRemoteAuthReceipt` proves consistency relative to the trusted loopback HTTP/MCP observation.

None is independent cryptographic proof that an arbitrary remote target consumed content, a production issuer minted a token correctly, or a deployed agent respected policy.

Control-plane identities are labels/content identities, not authenticated signer identities. Receipt roots are SHA-256 integrity values, not signatures, MACs, trusted timestamps, or hardware attestation.

### Local persistence is not hostile-writer authentication

`LocalEvidenceStore` revalidates manifests, payload hashes, identities, evidence schema, semantic roots, symlink/file constraints, and no-clobber publication behavior. It does not authenticate a writer who can coherently replace all controlled files and recompute ordinary hashes.

The repository does not claim signatures/MACs, key management, trusted timestamps, remote attestation, WORM/object-lock storage, transparency-log anchoring, or cross-host durable retention.

### Replay is historical regrading, not re-execution

`EvidenceReplayAdapter` requires exact trial/subject/scenario identity and can reapply deterministic grading to recorded evidence. It does not rerun providers, tools, sessions, resources, handoffs, environment injectors, MCP protocol probes, remote-auth probes, or external state readers and cannot establish fresh delivery.

### Assurance-report validation is not signed attestation

`AssuranceReport` rederives verdict consistency, reliability, critical-violation counts, release-gate output, and report root. The report root is integrity, not authenticated writer identity.

### No formal non-inferiority test

Paired comparison uses an exact McNemar/binomial test for directional improvement/regression. Failure to detect significant regression is **not** formal non-inferiority.

### `pass@k` / `pass^k` are empirical approximations

Current formulas use observed resolved success proportion and an independent-attempt interpretation. Correlated, adaptive, or non-stationary trials can violate that approximation. `BLOCKED` and `INCONCLUSIVE` remain separate uncertainty.

### Resource-prefix policy is lexical

Resource scope uses string-prefix matching after adapter normalization. Real deployments must canonicalize aliases, traversal, case, URL forms, and alternate identifiers before lexical prefix comparison can represent the intended security boundary.

### No sandbox-isolation claim

The repository currently executes no target-controlled arbitrary shell/code as an environment fault. Any future executor that does must implement and validate process, filesystem, and network containment separately.

## Current verification checkpoint

- deterministic core: **183 passed, 20 deselected**;
- branch coverage: **93.04%**;
- strict mypy: **0 issues across 38 source files**;
- deterministic OpenAI SDK suite: **11/11 passed**;
- deterministic MCP protocol suite: **6/6 passed**;
- deterministic MCP remote-auth suite: **3/3 passed**;
- Python 3.11/3.13 quality, Ruff, formatter, Bandit, dependency audit, and package integrity: green.

## Why these boundaries matter

Agent evaluation is unusually vulnerable to false confidence because outputs can look persuasive while surrounding state, authority, evaluator preconditions, protocol discovery, or authorization boundaries are wrong. The same discipline applies to this framework: documentation, badges, hashes, attack labels, receipts, protocol observations, HTTP statuses, and traces are not substitutes for the control they describe.

Capabilities move out of this document only after implementation, deterministic evidence, and documentation review make the stronger claim true.
