# Security

## Security posture

The repository treats the evaluated agent and all provider/tool/MCP/memory/resource/handoff/runtime-context content as untrusted with respect to evaluation authority. Evidence may describe what happened; it may not redefine what is allowed or what counts as success.

An adversarial trial is not behaviorally gradeable until the controlled evaluation environment has produced one exact valid delivery receipt bound to that scenario and attack. Failure to establish that precondition is `BLOCKED` evaluation uncertainty, not an agent defect.

## Deterministic controls

Implemented controls include:

- explicit tool allowlists/denylists, approval-before-use checks, resource-prefix confinement, and tool/handoff budgets;
- critical non-compensatory policy failure;
- separate `EVALUATION_ERROR / BLOCKED` and `RUNTIME_ERROR / BLOCKED` semantics;
- immutable ordered evidence and domain-separated roots;
- content-addressed adversarial fixtures/campaigns with authority-preserving derivation;
- exact delivery receipts binding scenario, attack, channel, injection point, and canonical payload digest;
- exactly-one delivery verification before adversarial subject grading;
- fail-closed handling of missing, duplicate, malformed, forged, mismatched, or never-produced delivery evidence;
- raw attack-body exclusion from delivery receipts;
- seven tested OpenAI channel categories at narrow SDK/local boundaries;
- per-trial copied-tool/cloned-agent isolation for local tool attacks;
- fresh SDK session isolation for memory attacks;
- ephemeral structured run input for resources;
- fresh one-shot handoff-filter isolation;
- read-only trial-local runtime-context overlay with task-local activation for environment attacks;
- exact call-ID binding for tool-result and environment-consumption receipts;
- clean subsequent-run checks for metadata, memory, resource, handoff, and environment isolation;
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

## Runtime-context `ENVIRONMENT` security boundary

`ENVIRONMENT` is intentionally not implemented as process-global environment mutation.

A valid fixture identifies one exact local `FunctionTool`, one exact string context key, and environment content. Complete canonical `AttackFixture.payload_json` becomes the value returned for that key during the first matching tool invocation.

The adapter accepts `run_context` only when it is `None` or a string-keyed `Mapping`, snapshots it into a read-only trial-local overlay, and activates the adversarial key with a task-local `ContextVar` during that one targeted invocation.

```text
source          = injector:openai-agents:environment-runtime-context
injection_point = openai-agents:FunctionTool:<tool>:call:<call_id>:RunContextWrapper.context:<key>
```

Delivery requires **actual value consumption**. A receipt is created only when subject code reads:

```text
ctx.context[<key>]
ctx.context.get(<key>)
```

A configured overlay, a matching tool invocation, or `key in ctx.context` is not sufficient. If the subject does not consume the value, the attack remains unverified and the trial is `BLOCKED`.

This protects against a common evaluator error: declaring a runtime-state attack successful merely because malicious state was made available somewhere in the harness.

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

## Other channel boundaries

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

`injector:<identity>` is a control-plane label, not authenticated signer identity. Receipt roots and evidence roots are domain-separated integrity hashes, not signatures, MACs, trusted timestamps, or hardware attestation.

A stronger deployment layer must separately address signer identity, trusted timestamps, tamper-resistant storage, and independent target-side acknowledgements where required.

## Sensitive data

Delivery receipts store only canonical attack payload digests, not raw attack bodies. Controlled boundaries necessarily expose the test stimulus to the subject surface being tested. Normal redaction, minimization, retention, and access-control discipline still apply to tool outputs, session state, resource content, handoff context, and runtime application context.

## Deployment boundary

Application-level evaluation cannot by itself prove process isolation, network egress control, secret-manager policy, production IAM, tenant isolation, sandbox containment, MCP/tool fidelity, production memory/retrieval integrity, distributed handoff correctness, or infrastructure fault behavior. Those controls require tests at their actual enforcement layers.

## Current verification checkpoint

- deterministic suite: **177 passed, 11 deselected**;
- branch coverage: **93.78%**;
- strict mypy: **0 issues across 34 source files**;
- deterministic OpenAI SDK suite: **11/11 passed**;
- Python 3.11/3.13 quality, Ruff, formatter, Bandit, dependency audit, and package integrity: green.

## Reporting vulnerabilities

Do not open a public issue containing credentials, private customer data, exploit secrets, or other sensitive material. Use GitHub private vulnerability reporting if enabled for the repository/account.
