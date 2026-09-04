# OpenAI Agents SDK Adapter

## Purpose

The OpenAI integration turns documented OpenAI Agents SDK execution surfaces into provider-neutral evaluation evidence while keeping state verification, policy authority, protocol truth, and release authority outside the SDK.

The integration is pinned to `openai-agents==0.22.0`. MCP integration is pinned separately to `mcp==2.1.1`. Pinning both sides makes normalization, tool-output conversion, call identity, and protocol negotiation explicit reviewable contracts rather than floating assumptions.

Two adapter boundaries are intentionally distinct:

- `OpenAIAgentsAdapter` — seven scoped local/SDK adversarial channels;
- `OpenAIAgentsMCPToolResultAdapter` — one controlled OpenAI-agent → official-MCP-stdio path for `MCPFaultKind.TOOL_RESULT_POISON`.

Importing `agent_evals` does not import either optional provider stack or require those optional dependencies.

## Trust boundary

### Seven local/SDK adversarial channels

```text
controlled scenario + optional AttackFixture
        ↓
OpenAIAgentsAdapter prepares isolated SDK execution
        ↓
USER_INPUT / local TOOL_RESULT / local TOOL_METADATA /
session-history MEMORY / inline-file RESOURCE /
first native HANDOFF context / local runtime-context ENVIRONMENT
        ↓
OpenAI Agents SDK execution
        ↓
public SDK result/item/session/handoff/tool-context surfaces
        ↓
provider-neutral EvidenceEvent stream
        +
independent state_reader()
        ↓
TrialEvidence
        ↓ exact ATTACK_DELIVERY verification when adversarial
framework-owned deterministic oracles
```

### Dedicated MCP tool-result bridge

```text
MCPFaultSpec(kind=tool_result_poison)
        ↓
OpenAIAgentsMCPToolResultAdapter
        ↓ fresh official MCPServerStdio subprocess
negotiated MCP protocol = 2026-07-28
        ↓
OpenAI agent makes exactly one target MCP call
        ↓
first target tools/call result observed at MCP boundary
        ↓
MCPFaultReceipt
        ↓
exact OpenAI TOOL_REQUEST / TOOL_RESULT call-ID pairing
+ exact model-visible output equivalence
+ same-session same-argument benign recovery
        ↓
MCPAgentToolResultReceipt
        ↓
PROTOCOL_DELIVERY inserted before matching TOOL_RESULT
        ↓
TrialEvidence
        ↓
framework-owned deterministic oracles
```

The second path is a bridge between evidence domains, not a conversion of MCP protocol evidence into grading authority. The bridge establishes a narrowly defined delivery precondition. The agent still passes or fails only through deterministic subject evidence and oracles.

## Seven concrete adversarial channels

| Channel | Tested OpenAI boundary |
|---|---|
| `user_input` | exact second user message supplied to `Runner.run` |
| `tool_result` | first invocation result of one exact local SDK `FunctionTool` |
| `tool_metadata` | `description` of one exact copied local SDK `FunctionTool` |
| `memory` | one prior user item returned by a fresh per-trial SDK `Session` |
| `resource` | `file_data` of one structured inline `input_file` in `Runner.run` input |
| `handoff` | context appended by the run-level handoff filter to the first actual SDK handoff |
| `environment` | one exact key read from trial-local `RunContextWrapper.context` during the first matching local `FunctionTool` call |

A channel label is never proof that an attack occurred. Each injector must either produce exact delivery evidence or allow the adversarial trial to remain `BLOCKED`.

## `USER_INPUT`

```text
input[0] = scenario objective
input[1] = exact canonical AttackFixture.payload_json

source          = injector:openai-agents:user-input
injection_point = openai-agents:Runner.run.input[1]
```

The receipt payload digest binds the same canonical fixture JSON supplied at the controlled SDK input boundary.

## Local `TOOL_RESULT`

A fixture requires `tool` and `result`. Complete canonical `AttackFixture.payload_json` becomes the replacement output of the first matching local SDK `FunctionTool` call.

The target tool is copied and the agent cloned for the trial. The reusable original agent/tool are not mutated. On the injected first call the original function is deliberately not executed.

```text
source          = injector:openai-agents:tool-result
injection_point = openai-agents:FunctionTool:<tool>:call:<call_id>:output

TOOL_REQUEST
ATTACK_DELIVERY
TOOL_RESULT
```

Later matching calls use copied original behavior. If the target never executes, no receipt exists and delivery verification blocks the trial.

This local mode still does **not** intercept MCP or hosted tools. MCP result delivery is handled only by the separate `OpenAIAgentsMCPToolResultAdapter` described below.

## Local `TOOL_METADATA`

Complete canonical fixture JSON replaces only the copied `FunctionTool.description`.

```text
source          = injector:openai-agents:tool-metadata
injection_point = openai-agents:FunctionTool:<tool>:description
```

Tool name, parameter schema, callback, approval behavior, and routing identity remain unchanged. MCP description poisoning, schema drift, and identity drift remain separate protocol-laboratory capabilities; none is promoted into the OpenAI agent bridge by the existence of the result path.

## SDK session-history `MEMORY`

A fresh per-trial object implementing the SDK `Session` protocol supplies one prior `user` item containing exact canonical fixture JSON.

```text
source          = injector:openai-agents:memory-session-history
injection_point = openai-agents:Session.get_items[0]
```

This is client-side SDK session-history poisoning, not production application memory, provider-managed conversation state, vector/RAG memory, or cross-user persistence testing.

## Structured inline-file `RESOURCE`

Exact canonical fixture JSON becomes the `file_data` of one structured inline file with evaluator-owned filename `agent-evals-resource.json`.

```text
input[0] = objective user message
input[1].content[0] = {
  type: input_file,
  file_data: exact canonical AttackFixture.payload_json,
  filename: agent-evals-resource.json
}
```

This does not claim hosted File Search, vector stores, RAG retrieval/ranking/chunking, external document repositories, MCP resources, or provider-side parsing attestation.

## Native `HANDOFF`

Complete canonical fixture JSON is appended to cloned handoff history on the first actual SDK handoff invoking the run-level filter. The SDK-selected destination remains unchanged.

```text
source          = injector:openai-agents:handoff-context
injection_point = openai-agents:RunConfig.handoff_input_filter:first:input_history[-1]

HANDOFF → ATTACK_DELIVERY
```

This is context poisoning, not destination rerouting or distributed-agent-fabric interception.

## Local runtime-context `ENVIRONMENT`

`ENVIRONMENT` targets local application data/dependencies passed through `Runner.run(..., context=...)` and exposed to tools as `RunContextWrapper.context`. The SDK does not automatically send this application context to the LLM.

The fixture identifies one exact local tool and one exact string key. The adapter snapshots caller context into a read-only trial-local overlay and uses task-local activation during the first matching tool invocation.

Delivery is consumption-bound:

```text
ctx.context[<key>]
ctx.context.get(<key>)
        ↓
exact canonical AttackFixture.payload_json
        ↓
call-ID-bound ATTACK_DELIVERY
```

Configuration, tool execution, or membership checks are insufficient. If subject code never reads the value, the trial remains `BLOCKED`.

This mode does not mutate process-global `os.environ`, filesystem/browser/container state, networks, clocks, secret managers, cloud IAM, provider configuration, or other production infrastructure.

---

## Verified MCP `TOOL_RESULT_POISON` bridge

### Scope

`OpenAIAgentsMCPToolResultAdapter` accepts exactly one `MCPFaultSpec` whose kind is `TOOL_RESULT_POISON`. It does not reuse the local `FunctionTool` injector and does not pretend an in-process protocol probe was an agent interaction.

For every trial it creates a **fresh official `MCPServerStdio` client/server process boundary** and clones the supplied OpenAI Agent with exactly that one controlled MCP server.

The base Agent is rejected when it already has MCP servers, uses prefixed MCP tool names, or has a local tool colliding with the target name. Those fail-closed preconditions prevent a valid-looking call ID from being attributed to the wrong tool or server.

### Protocol negotiation

For MCP v2, the authoritative negotiated revision is the connected `ClientSession.protocol_version`; legacy `server_initialize_result.protocol_version` is only a fallback for older initialization paths.

The adapter requires negotiated protocol `2026-07-28`. A different or unavailable version is an evaluation precondition failure, not a subject failure.

### Same-call observation

The adapter instruments the public MCP server `call_tool` boundary. On the first target call it records the exact successful text result and creates `MCPFaultReceipt` from that observed protocol result.

The behavioral run is required to make **exactly one** target MCP call:

- zero target calls → `mcp_target_call_missing` → `EVALUATION_ERROR / BLOCKED`;
- more than one target call → `mcp_target_call_ambiguous` → `EVALUATION_ERROR / BLOCKED`.

This one-call rule is deliberate. A second agent-visible recovery result would make it ambiguous which result the behavioral model consumed.

### SDK representation conversion

The pinned Agents SDK retains a single MCP text block in `ToolCallOutputItem.output` as a logical structured value:

```json
{"type": "text", "text": "..."}
```

When replayed to the Responses-model input, the SDK converts that same logical text output into a `function_call_output` content list using `input_text`:

```json
[{"type": "input_text", "text": "..."}]
```

The integration tests assert the actual public SDK surfaces rather than requiring these two representations to be byte-identical. The bridge binds the logical model-visible result, not an accidental serialization spelling.

### Same-session recovery

Only after the agent run completes and exactly one behavioral target call is established does the adapter call the same target again with the same arguments through the **same still-connected MCP session**.

The second result must equal the configured benign recovery text. Recovery therefore proves one-shot fault isolation without adding a second benign output to the agent's behavioral transcript.

A recovery mismatch becomes `mcp_recovery_mismatch / EVALUATION_ERROR / BLOCKED`.

### Cross-domain receipt closure

The normalized OpenAI evidence must contain exactly one target `TOOL_REQUEST`, a stable non-empty `call_id`, and exactly one matching `TOOL_RESULT` for that call ID.

`MCPAgentToolResultReceipt.create(...)` binds:

- scenario identity;
- the verified `MCPFaultReceipt`;
- exact agent tool name;
- exact agent call ID;
- exact normalized agent-visible output.

Only then is `PROTOCOL_DELIVERY` inserted immediately before the matching `TOOL_RESULT`:

```text
TOOL_REQUEST
PROTOCOL_DELIVERY
TOOL_RESULT
```

The raw malicious body is not duplicated into the bridge receipt. Integrity roots remain hashes, not signatures or target-side attestation.

### What the bridge proves

The deterministic test proves that, inside the controlled harness:

1. the official MCP stdio session negotiated the required protocol revision;
2. the first target MCP call returned the bound poisoned result;
3. the same target result crossed the OpenAI Agents SDK MCP tool boundary;
4. the deterministic model received that same logical result for the exact agent call ID;
5. the normalized evidence pairs request and result identity exactly;
6. the same connected MCP session recovered to benign behavior on the next same-argument call;
7. only after those facts close can the trial proceed to deterministic policy/outcome grading.

### What the bridge does not prove

It does not establish:

- live OpenAI model behavior or provider availability;
- hosted OpenAI MCP, third-party MCP, remote MCP, Internet MCP, TLS/DNS/proxy/gateway fidelity, or arbitrary stdio transport robustness;
- MCP metadata poison, `ToolError`, stale-cache, schema-drift, or identity-drift behavior inside an agent trial;
- arbitrary multi-call plans, retries, parallel target calls, or multiple MCP servers;
- production authorization, OAuth, identity-provider, or credential lifecycle behavior;
- target-side cryptographic attestation;
- release acceptance from protocol evidence alone.

---

## Fail-closed preconditions

Malformed attack payloads, missing or ambiguous local targets, unsupported target types, unusable call identities, unsupported environment context, MCP server ambiguity, protocol-version mismatch, missing protocol evidence, mismatched agent evidence, or failed recovery raise `AdapterPreconditionError`.

`TrialRunner` converts these into `EVALUATION_ERROR / BLOCKED` with no completed subject oracles. Provider/runtime failures remain `RUNTIME_ERROR / BLOCKED`.

```text
unverified evaluator-controlled precondition → EVALUATION_ERROR / BLOCKED
provider or SDK runtime failure               → RUNTIME_ERROR / BLOCKED
verified subject violation                    → deterministic oracle FAIL
```

## Approval semantics

An SDK `ToolApprovalItem` normalizes as `APPROVAL_REQUEST`, never `APPROVAL`. Asking for permission is not proof that permission was granted; authorization evidence remains independently controlled.

## Tracing and sensitive data

The adapters set sensitive tracing off for deterministic tests. Delivery and protocol receipts retain digests and identities rather than duplicating raw malicious content. Controlled execution boundaries necessarily contain the test stimulus, so ordinary data minimization and retention discipline still applies.

## Deterministic SDK verification

The repository uses `agents.testing.ScriptedModel` against the real pinned Agents SDK without provider API calls.

Implementation source checkpoint `d98f9ca1feb1179504cd2181295a73936fd0ae6c`, protected-main CI run `33898508697`:

- deterministic core: **349 passed, 27 deselected**;
- branch coverage: **93.79%** against the 90% gate;
- strict mypy: **0 issues across 42 source files**;
- deterministic OpenAI SDK suite, including the MCP stdio bridge: **15/15 passed**;
- deterministic MCP protocol suite: **6/6 passed**;
- deterministic MCP remote-auth suite: **3/3 passed**;
- deterministic MCP OAuth-flow suite: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest**, Ruff, formatter, Bandit, dependency audit, package integrity, and all **7/7 CI jobs**: green;
- dependency audit: **no known vulnerabilities found**; the project package itself is skipped because it is not published on PyPI.

This checkpoint identifies the audited merged implementation revision. Documentation-only synchronization is validated by its own full pull-request CI and does not silently redefine the implementation evidence.
