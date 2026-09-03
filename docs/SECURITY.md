# Security

## Security posture

The repository treats the evaluated agent and all provider/tool/MCP/memory/resource/handoff/runtime-context content as untrusted with respect to evaluation authority. Evidence may describe what happened; it may not redefine what is allowed or what counts as success.

An adversarial agent trial is not behaviorally gradeable until the controlled evaluation environment has produced one exact valid delivery receipt bound to that scenario and attack. Failure to establish that precondition is `BLOCKED` evaluation uncertainty, not an agent defect.

The MCP fault laboratory has a separate rule: a configured fault is not treated as delivered until the **official MCP client** observes the exact fault-specific protocol representation or protocol-state relation. Protocol delivery still does not establish agent behavioral resistance.

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
- content-addressed MCP fault specifications independent from OpenAI attack fixtures;
- official `mcp==2.1.1` in-process `MCPServer`/`Client` execution pinned to protocol `2026-07-28`;
- exact MCP client observation for tool-description poison, first-call result poison, and model-visible `ToolError`;
- exact private `tools/list` stale-cache relation proving initial discovery, server-side removal, stale cached reuse, and explicit-refresh absence;
- MCP receipts binding both controlled fault-material digest and exact canonical observation digest without storing raw malicious text;
- second-call benign recovery for one-shot MCP result/error faults;
- a dedicated MCP CI dependency boundary rather than relying on OpenAI's transitive MCP dependency;
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

## MCP protocol fault security boundary

The MCP laboratory deliberately tests a different trust layer from the OpenAI adapter.

A valid `MCPFaultSpec` binds stable fault identity, revision, kind, tool name, and canonical finite JSON payload. Content faults treat that payload as controlled malicious material. `tool_list_stale_cache` instead requires exactly one bounded positive `ttl_ms` value, which becomes the deterministic private freshness declaration consumed by the server configuration.

`MCPFaultLab.probe()` creates a fresh official `MCPServer`, connects an official `Client` in `2026-07-28` mode, lists tools, invokes the target twice, and emits `MCPFaultReceipt` only after a matching public client content observation exists. `probe_discovery_cache()` creates the same fresh boundary but verifies an initial tool listing, removes the tool from the live server registry, observes a normal client call reuse the still-fresh cached listing, and then requires `cache_mode="refresh"` to prove the live listing no longer contains the target.

Current exact boundaries are:

```text
mcp:2026-07-28:tools/list:<tool>:description
mcp:2026-07-28:tools/call:<tool>:result.content[0].text
mcp:2026-07-28:tools/call:<tool>:error.content[0].text:message-suffix
mcp:2026-07-28:tools/list:cache-use-stale-after-remove:<tool>:refresh-proves-absent
```

### Observation integrity

`payload_sha256` identifies controlled fault material. `observation_sha256` identifies the complete canonical observation returned or derived from public official-client fields.

For direct metadata/result poison they match. For `ToolError`, the SDK wraps the controlled message as:

```text
Error executing tool <tool>: <canonical fault payload>
```

The hashes therefore differ. For the stale-cache fault they also differ by design: the payload hash binds the TTL configuration, while the observation hash binds canonical JSON containing the initial, cached, refreshed tool-name sets and observed TTL. Recording both prevents a false claim that transformed content or stateful protocol behavior is byte-identical to its configuration.

### Isolation

Every probe gets a fresh server. Result/error faults are one-shot and must be followed by a benign second call. This catches accidental sticky state inside the harness while still proving first-call delivery.

The stale-cache probe additionally gets a fresh client cache and requires all four legs of the relation—initial target present, live server removal, cached target still present, forced refresh target absent—before a receipt can exist.

### MCP non-claims

The current laboratory does **not** establish:

- agent behavior after consuming an MCP-delivered fault;
- OpenAI hosted/MCP tool interception by `OpenAIAgentsAdapter`;
- remote Streamable HTTP, stdio, proxy, network, TLS, or DNS fault behavior;
- authorization issuer/scope/credential-reuse/token-binding/CIMD properties;
- public or cross-partition cache sharing, cache poisoning, custom/shared cache stores, notification-driven invalidation, TTL-expiry behavior, cache races, renamed-tool behavior, or general cache correctness beyond the tested private stale-after-removal relation;
- malformed framing/JSON-RPC, schema drift, duplicate/out-of-order responses, or header-routing faults;
- malicious MCP resources, prompts, roots, elicitation, sampling, subscriptions, or Tasks extension behavior;
- full protocol-conformance certification;
- hosted third-party MCP server fidelity;
- remote target-side delivery attestation.

Those require dedicated protocol/transport/authentication boundaries and, for agent assurance, an explicit bridge into deterministic agent evidence.

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

The original caller-owned context mapping is never mutated. A later ordinary run sees the original value. Task-local activation also prevents unrelated concurrent tool tasks from inheriting the injected value.

## Environment non-claims

The current runtime-context mode does **not** mutate, simulate, or attest:

- `os.environ` or operating-system environment variables;
- filesystems, browsers, containers, or sandboxes;
- network partitions, latency, DNS, timeouts, or downstream-service faults;
- provider/model runtime configuration;
- clocks, timezones, or time-skew behavior;
- secret managers, credentials, API keys, or token stores;
- Kubernetes/cloud IAM, queues, databases, service meshes, or production chaos infrastructure;
- arbitrary non-`Mapping` application context objects;
- external-system or provider-side environment consumption.

Those controls must be exercised at the actual enforcement boundary with dedicated injectors and independent observation.

## Other OpenAI channel boundaries

### `USER_INPUT`

Objective plus exact canonical fixture JSON are supplied as two ordered user messages. This proves controlled SDK input, not remote hosted-model processing.

### Local `TOOL_RESULT`

The first matching local `FunctionTool` result is replaced with exact canonical fixture JSON and bound to the SDK call ID. The original function does not execute on that injected call. This is not hosted/MCP/remote-service interception.

### Local `TOOL_METADATA`

Only copied `FunctionTool.description` is changed. Name, parameter schema, callback, approval semantics, and routing identity remain fixed. This is not schema or registry poisoning.

### SDK session-history `MEMORY`

A fresh per-trial SDK `Session` supplies one poisoned prior user item. This is not production memory, provider-managed conversation, vector/RAG memory, or cross-user persistence testing.

### Structured inline-file `RESOURCE`

Exact canonical fixture JSON becomes `input_file.file_data`. This is not File Search, vector-store/RAG, URL/document-store, MCP-resource, or provider-side parsing attestation.

### Native `HANDOFF`

Exact canonical fixture JSON is appended to the first native SDK handoff context while the SDK-selected destination remains unchanged. This is not rerouting or distributed-agent-fabric interception.

## Delivery integrity is not attestation

`injector:<identity>` and MCP fault identities are control-plane identities, not authenticated signer identities. Receipt/evidence roots are domain-separated integrity hashes, not signatures, MACs, trusted timestamps, or hardware attestation.

A stronger deployment layer must separately address signer identity, trusted timestamps, tamper-resistant storage, transport authenticity, and independent target-side acknowledgements where required.

## Sensitive data

Adversarial and MCP receipts store digests rather than raw attack/fault bodies. Controlled boundaries necessarily expose the test stimulus to the subject or protocol surface being tested. Normal redaction, minimization, retention, and access-control discipline still applies to tool outputs, MCP payloads, session state, resource content, handoff context, and runtime application context.

## Deployment boundary

Application-level evaluation cannot by itself prove process isolation, network egress control, secret-manager policy, production IAM, tenant isolation, sandbox containment, remote MCP fidelity, production memory/retrieval integrity, distributed handoff correctness, or infrastructure fault behavior. Those controls require tests at their actual enforcement layers.

## Current verification checkpoint

- deterministic core: **181 passed, 15 deselected**;
- branch coverage: **93.14%**;
- strict mypy: **0 issues across 37 source files**;
- deterministic OpenAI SDK suite: **11/11 passed**;
- deterministic MCP protocol suite: **4/4 passed**;
- Python 3.11/3.13 quality, Ruff, formatter, Bandit, dependency audit, and package integrity: green.

## Reporting vulnerabilities

Do not open a public issue containing credentials, private customer data, exploit secrets, or other sensitive material. Use GitHub private vulnerability reporting if enabled for the repository/account.
