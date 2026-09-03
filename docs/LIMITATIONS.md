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

The repository therefore does **not** claim this mode mutates, attacks, validates, or attests:

- process-global `os.environ` or operating-system environment variables;
- filesystems, browser state, containers, VMs, or sandboxes;
- network latency, partitions, DNS, timeouts, or dependency outages;
- provider/model runtime or deployment configuration;
- clocks, timezones, or time-skew behavior;
- secret managers, credentials, API keys, certificates, or token stores;
- Kubernetes, cloud IAM, service meshes, queues, databases, or other production infrastructure;
- arbitrary non-`Mapping` application context objects;
- external-system or provider-side environment consumption;
- production chaos-engineering coverage.

Those require separate environment-specific adapters/injectors at the actual enforcement boundary.

### Local `TOOL_RESULT` replacement is not hosted/MCP interception

The current OpenAI result mode targets one exact local SDK `FunctionTool`. On the first matching call the original function is deliberately not executed; exact canonical fixture JSON becomes the result. Later calls use copied original behavior.

It does not claim hosted/MCP/external-server interception, generic support for every SDK tool type, preservation of original first-call side effects, or execute-then-perturb semantics.

The separate MCP fault laboratory exercises MCP protocol surfaces directly; it does not turn this OpenAI local-tool mode into MCP interception.

### Local `TOOL_METADATA` means description poisoning

The OpenAI metadata mode changes only copied `FunctionTool.description`. It does not mutate tool name, parameter schema, invocation callback, approval semantics, routing identity, hosted metadata, MCP discovery metadata, or external registries.

MCP description poisoning exists only in the separate protocol laboratory's `tools/list` boundary.

### SDK session-history `MEMORY` is not production memory poisoning

The memory mode uses a fresh per-trial client-side SDK `Session` and one prior user item. It does not claim application-owned production session mutation, provider-managed conversations, vector/RAG memory, semantic retrieval manipulation, cross-user persistence, or external memory lifecycle assurance.

### Structured inline-file `RESOURCE` is not retrieval-system poisoning

The resource mode places exact canonical fixture JSON in one structured SDK `input_file.file_data` field with evaluator-owned filename `agent-evals-resource.json`.

It does not claim OpenAI hosted File Search, vector stores, embeddings, RAG retrieval/ranking/chunking/filtering/citations, `file_id`, `file_url`, browser pages, databases, object stores, production document repositories, MCP resource servers, or provider-side file parsing/retention attestation.

The separate `resource_resolver(tool_name, arguments)` callback is only a deterministic policy resource-identity normalizer.

### Native SDK `HANDOFF` is context poisoning, not rerouting

The handoff mode appends exact canonical fixture JSON to cloned context for the first actual SDK handoff invoking the run-level filter. The SDK-selected destination remains unchanged.

It does not choose a new destination, rewrite handoff routing metadata, poison every transfer, intercept remote/distributed agent fabrics, or attest provider-side consumption.

### MCP fault laboratory is protocol evidence, not agent assurance

The repository now includes a deterministic MCP fault laboratory using official `mcp==2.1.1`, a real in-process `MCPServer`, the official `Client`, and protocol revision `2026-07-28`.

Current implemented fault families are narrow:

- exact target-tool description poisoning observed through `tools/list`;
- exact first-call target-tool result poisoning observed through `tools/call`;
- model-visible first-call `ToolError` carrying the canonical payload inside the SDK-generated error envelope.

Every probe uses a fresh server. Result/error faults require a benign second call, proving one-shot recovery. `MCPFaultReceipt` binds fault identity, protocol version, tool, injection point, controlled payload digest, exact observed-text digest, and a receipt root without duplicating raw fault content.

That implementation does **not** establish:

- an autonomous agent receiving or resisting the MCP fault;
- OpenAI `ATTACK_DELIVERY` semantics for MCP;
- remote Streamable HTTP, stdio, proxy, network, TLS, or DNS behavior;
- MCP authorization issuer, scope, credential reuse, token-binding, or CIMD behavior;
- cache poisoning/staleness/invalidation or disappearing/renamed tools;
- malformed JSON-RPC, invalid schemas, schema drift, duplicate/out-of-order responses, or `Mcp-Method`/`Mcp-Name` routing faults;
- malicious resources, resource templates, prompts, roots, elicitation, sampling, subscriptions, or Tasks extension behavior;
- hosted third-party MCP server fidelity;
- complete protocol-conformance certification;
- target-side or remote delivery attestation.

Protocol observation is therefore not promoted to agent `PASS`, `FAIL`, release `ACCEPT`, or any equivalent behavioral conclusion.

### Approval requests are not approvals

SDK `ToolApprovalItem` observations normalize as `APPROVAL_REQUEST`, never `APPROVAL`. Privileged execution requires independent authorization evidence.

### No semantic/model grader yet

The current framework does not use a model-as-judge. Deterministic state and policy authority remain primary. A future semantic grader requires calibration, provenance, explicit failure semantics, and non-overriding precedence relative to critical deterministic failures.

### Delivery receipts are not target-side attestation

A valid OpenAI attack receipt proves consistency relative to the trusted evaluator's controlled observation. An `MCPFaultReceipt` similarly proves consistency relative to the trusted official-client observation. Neither is independent cryptographic proof that an arbitrary remote target consumed the stimulus.

Control-plane identities are labels/content identities, not authenticated signer identities. Receipt roots are SHA-256 integrity values, not signatures, MACs, trusted timestamps, or hardware attestation.

### Local persistence is not hostile-writer authentication

`LocalEvidenceStore` revalidates manifests, payload hashes, identities, evidence schema, semantic roots, symlink/file constraints, and no-clobber publication behavior. It does not authenticate a writer who can coherently replace all controlled files and recompute ordinary hashes.

The repository does not claim signatures/MACs, key management, trusted timestamps, remote attestation, WORM/object-lock storage, transparency-log anchoring, or cross-host durable retention.

### Replay is historical regrading, not re-execution

`EvidenceReplayAdapter` requires exact trial/subject/scenario identity and can reapply deterministic grading to recorded evidence. It does not rerun providers, tools, sessions, resources, handoffs, environment injectors, MCP protocol probes, or external state readers and cannot establish fresh delivery.

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

- deterministic core: **180 passed, 14 deselected**;
- branch coverage: **93.21%**;
- strict mypy: **0 issues across 37 source files**;
- deterministic OpenAI SDK suite: **11/11 passed**;
- deterministic MCP protocol suite: **3/3 passed**;
- Python 3.11/3.13 quality, Ruff, formatter, Bandit, dependency audit, and package integrity: green.

## Why these boundaries matter

Agent evaluation is unusually vulnerable to false confidence because outputs can look persuasive while surrounding state, authority, evaluator preconditions, or protocol delivery are wrong. The same discipline applies to this framework: documentation, badges, hashes, attack labels, receipts, protocol observations, and traces are not substitutes for the control they describe.

Capabilities move out of this document only after implementation, deterministic evidence, and documentation review make the stronger claim true.
