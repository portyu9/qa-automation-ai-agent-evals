# OpenAI Agents SDK Adapter

## Purpose

The OpenAI integration turns documented OpenAI Agents SDK execution surfaces into provider-neutral evaluation evidence while keeping state verification, policy authority, protocol truth, and release authority outside the SDK.

The integration is pinned to `openai-agents==0.22.0`. MCP integration is pinned separately to `mcp==2.1.1`. Pinning both sides makes normalization, tool-output conversion, call identity, protocol negotiation, retry chronology, and tool-discovery semantics explicit reviewable contracts rather than floating assumptions.

Four adapter boundaries are intentionally distinct:

- `OpenAIAgentsAdapter` — seven scoped local/SDK adversarial channels;
- `OpenAIAgentsMCPToolResultAdapter` — one controlled OpenAI-agent → official-MCP-stdio path for `MCPFaultKind.TOOL_RESULT_POISON`;
- `OpenAIAgentsMCPToolErrorRecoveryAdapter` — one controlled OpenAI-agent → official-MCP-stdio resilience path for `MCPFaultKind.TOOL_ERROR`, requiring a causal same-argument retry and exact benign recovery;
- `OpenAIAgentsMCPToolSchemaDriftAdapter` — one controlled OpenAI-agent → official-MCP-stdio schema-adaptation path for `MCPFaultKind.TOOL_SCHEMA_DRIFT`, requiring a real stale-call rejection, evaluator-owned cache invalidation, first fresh v2 discovery, and one exact corrected behavioral call.

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

### Dedicated MCP result bridge

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
+ same-session same-argument benign recovery after the run
        ↓
MCPAgentToolResultReceipt
        ↓
PROTOCOL_DELIVERY inserted before matching TOOL_RESULT
        ↓
TrialEvidence
        ↓
framework-owned deterministic oracles
```

### Dedicated MCP ToolError retry/recovery bridge

```text
MCPFaultSpec(kind=tool_error)
        ↓
OpenAIAgentsMCPToolErrorRecoveryAdapter
        ↓ fresh official MCPServerStdio subprocess
negotiated MCP protocol = 2026-07-28
        ↓
TOOL_REQUEST(error_call_id)
        ↓
real MCP ToolError → MCPFaultReceipt
        ↓ exact model-visible error equivalence
TOOL_RESULT(error_call_id)
        ↓ strict causal chronology
TOOL_REQUEST(retry_call_id; same canonical arguments)
        ↓ same live MCP session
TOOL_RESULT(retry_call_id; exact benign recovery)
        ↓
MCPAgentToolErrorRecoveryReceipt
        ↓
PROTOCOL_DELIVERY inserted after the recovery result
        ↓
TrialEvidence
        ↓
framework-owned deterministic oracles
```

### Dedicated MCP schema-drift adaptation bridge

```text
MCPFaultSpec(kind=tool_schema_drift)
        ↓
OpenAIAgentsMCPToolSchemaDriftAdapter
        ↓ fresh official MCPServerStdio subprocess
negotiated MCP protocol = 2026-07-28
        ↓
model receives v1 tool contract
        ↓
TOOL_REQUEST(stale_call_id; v1 arguments)
        ↓
evaluator-only hidden live schema swap to v2
        ↓
real MCP v2 validation rejects stale v1 arguments
        ↓
TOOL_RESULT(stale_call_id; exact model-visible rejection)
        ↓
host adapter invalidates MCP tool cache once
        ↓
first fresh post-invalidation tools/list exposes v2
        ↓
model receives v2 contract + stale rejection
        ↓
TOOL_REQUEST(recovery_call_id; exact v2 arguments)
        ↓ same live MCP session
TOOL_RESULT(recovery_call_id; exact replacement result)
        ↓
MCPAgentToolSchemaDriftReceipt
        ↓
PROTOCOL_DELIVERY inserted after the recovery result
        ↓
TrialEvidence
        ↓
framework-owned deterministic oracles
```

All three MCP paths are bridges between evidence domains, not conversions of MCP protocol evidence into grading authority. A bridge establishes a narrowly defined delivery/recovery/adaptation precondition. The agent still passes or fails only through deterministic subject evidence and oracles.

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

This local mode still does **not** intercept MCP or hosted tools. MCP result, ToolError-recovery, and host-refreshed schema-drift assurance are handled only by the separate stdio adapters described below.

## Local `TOOL_METADATA`

Complete canonical fixture JSON replaces only the copied `FunctionTool.description`.

```text
source          = injector:openai-agents:tool-metadata
injection_point = openai-agents:FunctionTool:<tool>:description
```

Tool name, parameter schema, callback, approval behavior, and routing identity remain unchanged. MCP description poisoning and identity drift remain separate protocol-laboratory capabilities. MCP schema drift has its own narrowly bounded host-refreshed bridge; that does not turn local `TOOL_METADATA` replacement into an MCP capability or establish arbitrary schema-migration behavior.

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

## Shared MCP stdio provenance controls

All three MCP adapters create a **fresh official `MCPServerStdio` client/server process boundary** per trial and clone the supplied OpenAI Agent with exactly that one controlled MCP server.

The base Agent is rejected when it already has MCP servers, uses prefixed MCP tool names, or has a local tool colliding with the target name. The schema-drift adapter additionally reserves an evaluator-only control-tool identity and filters that control from the agent-visible MCP tool list. Those fail-closed preconditions prevent a valid-looking call ID or control action from being attributed to the wrong tool or server.

For MCP v2, the authoritative negotiated revision is the connected `ClientSession.protocol_version`; legacy `server_initialize_result.protocol_version` is only a fallback for older initialization paths.

All three adapters require negotiated protocol `2026-07-28`. A different or unavailable version is an evaluation precondition failure, not a subject failure.

---

## Verified MCP `TOOL_RESULT_POISON` bridge

### Scope

`OpenAIAgentsMCPToolResultAdapter` accepts exactly one `MCPFaultSpec` whose kind is `TOOL_RESULT_POISON`. It does not reuse the local `FunctionTool` injector and does not pretend an in-process protocol probe was an agent interaction.

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

### What the result bridge proves

The deterministic test proves that, inside the controlled harness:

1. the official MCP stdio session negotiated the required protocol revision;
2. the first target MCP call returned the bound poisoned result;
3. the same target result crossed the OpenAI Agents SDK MCP tool boundary;
4. the deterministic model received that same logical result for the exact agent call ID;
5. the normalized evidence pairs request and result identity exactly;
6. the same connected MCP session recovered to benign behavior on the next same-argument evaluator-owned call after the run;
7. only after those facts close can the trial proceed to deterministic policy/outcome grading.

---

## Verified MCP `TOOL_ERROR` causal retry/recovery bridge

### Scope

`OpenAIAgentsMCPToolErrorRecoveryAdapter` accepts exactly one `MCPFaultSpec` whose kind is `TOOL_ERROR` plus one exact expected benign recovery text. Unlike the result bridge, **both calls are behavioral agent calls**. The evaluator does not manufacture the retry after the run.

The intended relation is:

```text
first target request
→ real MCP ToolError
→ exact model-visible error result
→ one same-argument agent retry
→ exact benign recovery on the same live MCP session
```

### First-call protocol observation

The first target `server.call_tool` result must be an error result with exactly one text block. The adapter creates `MCPFaultReceipt` from that actual observation using the exact `TOOL_ERROR` observation point and required protocol revision.

The receipt is not inferred from configured fault material. Protocol observation remains a separate evidence fact.

### Exactly one behavioral retry

The controlled target must be called **exactly twice** during the agent run:

- zero calls → target missing → `EVALUATION_ERROR / BLOCKED`;
- one call → retry missing → `EVALUATION_ERROR / BLOCKED`;
- more than two calls → retry relation ambiguous → `EVALUATION_ERROR / BLOCKED`.

The first and second call arguments are canonicalized as finite JSON and must be exactly equal. A changed retry becomes `mcp_error_retry_arguments_changed / EVALUATION_ERROR / BLOCKED`.

### Call identity and causal chronology

Normalized OpenAI evidence must contain exactly two target `TOOL_REQUEST` events with stable, non-empty, **distinct** call IDs and exactly one matching `TOOL_RESULT` per call.

The bridge then requires strict normalized chronology:

```text
request₁ < result₁ < request₂ < result₂
```

This is the causality boundary. Two identical target calls pre-issued before the first result may be sequential at the MCP server, but they do not prove that the second call was a retry **in response to** the model-visible error. Such evidence fails closed as:

```text
mcp_error_retry_causality_unverified → EVALUATION_ERROR / BLOCKED
```

The regression suite explicitly exercises the invalid chronology:

```text
request₁ → request₂ → result₁ → result₂
```

and requires it to block.

### Error and recovery equivalence

`MCPAgentToolErrorRecoveryReceipt.create(...)` revalidates the embedded protocol receipt and binds:

- scenario identity;
- exact `TOOL_ERROR` fault identity, tool name, kind, protocol revision, and observation point;
- exact controlled payload digest;
- exact SDK-generated expected error-envelope digest;
- distinct error and retry OpenAI call IDs;
- canonical original/retry argument digest equality;
- agent-visible error digest equal to the verified MCP observation digest;
- expected benign recovery digest equal to the agent-visible recovery digest;
- a domain-separated receipt root.

Raw controlled error content, raw retry arguments, and benign recovery text are not duplicated into the receipt.

### Bridge chronology

`PROTOCOL_DELIVERY` is emitted only **after** the second `TOOL_RESULT`:

```text
TOOL_REQUEST(error)
TOOL_RESULT(error)
TOOL_REQUEST(retry)
TOOL_RESULT(recovery)
PROTOCOL_DELIVERY
```

That placement is intentional. The receipt represents the full error → retry → recovery relation and cannot truthfully exist before recovery is observed.

### What the ToolError bridge proves

Inside the deterministic harness it proves:

1. the connected official MCP stdio session negotiated protocol `2026-07-28`;
2. the first target call returned the bound real `ToolError` observation;
3. the pinned Agents SDK exposed the exact expected logical error result to the deterministic model path;
4. the agent produced a distinct second target call only after the first result in normalized chronology;
5. the retry used the same canonical arguments;
6. the retry recovered to the exact configured benign value on the same live session;
7. only then did the evaluator close `MCPAgentToolErrorRecoveryReceipt` / `PROTOCOL_DELIVERY` and allow deterministic grading.

### What the ToolError bridge does not prove

It does not establish generic retry policy correctness, exponential backoff, jitter, idempotency semantics, retry safety for side-effecting tools, arbitrary error classes, more than one retry, arbitrary parallel plans, multiple MCP servers, hosted/remote MCP behavior, live-model behavior, provider availability, or production fault tolerance.

---

## Verified MCP `TOOL_SCHEMA_DRIFT` host-refreshed adaptation bridge

### Scope and ownership

`OpenAIAgentsMCPToolSchemaDriftAdapter` accepts exactly one `MCPFaultSpec` whose kind is `TOOL_SCHEMA_DRIFT` and whose controlled payload binds the repository's narrow v1/v2 scalar-required contracts plus a positive TTL. It does not claim arbitrary JSON Schema migration.

Ownership is intentionally split:

- the controlled harness owns the hidden live schema replacement;
- the evaluator/host adapter owns one MCP tool-cache invalidation after the stale rejection;
- the official MCP session owns the first fresh post-invalidation `tools/list` observation;
- the pinned Agents SDK owns conversion of refreshed MCP schema into next-turn model tool definitions and may reuse that v2 cache later;
- the agent/model is credited only for changing the second target call after v2 is model-visible.

The adapter does **not** claim model-initiated refresh or automatic `tools/list_changed` handling.

### Hidden swap without control leakage

The controlled stdio fixture exposes an evaluator-only schema-swap tool at the server boundary. `MCPServerStdio` is constructed with a static tool filter that blocks this control identity from the agent-visible tool list. If the control identity ever appears in observed model-visible discovery, the relation fails closed.

The first target call captures the still-cached v1 contract. Inside that intercepted call, the adapter invokes the hidden control so the server replaces v1 with v2 **after** the model selected the v1 call but **before** the stale call reaches real MCP validation. This ordering is what makes the stale-call rejection meaningful rather than simulated.

### Real stale rejection and host refresh

The stale v1 call is allowed to reach the actual v2 server validator. It must return a real error result with one model-visible text observation. Only after that rejection does the host adapter invalidate its tool cache.

The first subsequent fresh `tools/list` must expose the exact bound v2 contract before a recovery call occurs. Later SDK turns may read the already-refreshed v2 cache; those reads do not constitute extra refreshes. The assurance invariant is:

```text
one host invalidation
→ first fresh post-invalidation v2 discovery
→ corrected behavioral call
```

not “exactly one later list_tools() invocation.”

### Exact corrected call

The behavioral run must make exactly two target calls. The first uses the bound stale v1 arguments; the second must use the exact bound v2 replacement arguments and return the exact replacement result on the same live MCP session.

Zero target calls, no corrected call, more than two target calls, corrected call before refreshed discovery, repeated stale arguments, wrong replacement arguments, or wrong replacement result becomes `EVALUATION_ERROR / BLOCKED`.

### Protocol chronology and receipt closure

`MCPAgentToolSchemaDriftReceipt` binds:

- scenario identity and the revalidated `MCPFaultReceipt`;
- exact tool identity and distinct stale/recovery OpenAI call IDs;
- positive bound TTL;
- initial, cached, and refreshed schema digests;
- stale and recovery argument digests;
- protocol and agent-visible stale-rejection digests;
- expected, protocol-observed, and agent-visible recovery digests;
- strict protocol ordinals;
- a domain-separated receipt root.

The required protocol chronology is:

```text
initial-list
< hidden schema swap
< stale call
< host cache invalidation
< first refreshed v2 list
< recovery call
```

Normalized agent evidence independently requires the stale request/result to precede the recovery request/result. `PROTOCOL_DELIVERY` is emitted only after the recovery `TOOL_RESULT`, because the receipt represents the complete adaptation relation.

Raw stale error text, raw recovery text, and raw call arguments are not duplicated into the bridge receipt.

### What the schema-drift bridge proves

Inside the deterministic harness it proves:

1. the official stdio session negotiated MCP `2026-07-28`;
2. the first model turn received the bound v1 target schema and not the evaluator control tool;
3. the model selected the bound v1-shaped call;
4. the live server changed to v2 before that call reached real validation;
5. real v2 validation rejected the stale v1 arguments and the pinned SDK made that rejection model-visible;
6. the host invalidated cached discovery once and the first fresh post-invalidation listing exposed the bound v2 contract;
7. only after v2 became model-visible did the agent issue the distinct exact v2-shaped recovery call;
8. that call returned the bound replacement result on the same session;
9. only then could `MCPAgentToolSchemaDriftReceipt` / `PROTOCOL_DELIVERY` close and deterministic grading proceed.

### What the schema-drift bridge does not prove

It does not establish model-owned refresh, notification-driven `tools/list_changed` behavior, arbitrary schema compatibility, optional/default/coercion semantics beyond the bound fixture, tool rename handling, identity drift handling, generic cache policy correctness, multiple simultaneous schema migrations, multiple MCP servers, hosted/remote MCP behavior, live-model behavior, provider availability, authorization, or production deployment behavior.

---

## What the MCP bridges do not prove

None of the three bridges establishes:

- live OpenAI model behavior or provider availability;
- hosted OpenAI MCP, third-party MCP, remote MCP, Internet MCP, TLS/DNS/proxy/gateway fidelity, or arbitrary stdio transport robustness;
- MCP metadata poison, generic stale-cache behavior, or identity-drift behavior inside an agent trial;
- arbitrary schema migrations beyond the one controlled host-refreshed schema-drift contract;
- arbitrary multi-call or parallel plans;
- production authorization, OAuth, identity-provider, or credential lifecycle behavior;
- target-side cryptographic attestation;
- release acceptance from protocol evidence alone.

A bridge closure is an evaluation precondition. It is not a behavioral verdict.

---

## Fail-closed preconditions

Malformed attack payloads, missing or ambiguous local targets, unsupported target types, unusable call identities, unsupported environment context, MCP server ambiguity, protocol-version mismatch, missing protocol evidence, mismatched agent evidence, changed retry arguments, non-causal retry chronology, schema-control leakage, incomplete schema chronology, recovery before refreshed discovery, wrong replacement contracts/arguments/results, or failed recovery raise `AdapterPreconditionError`.

`TrialRunner` converts these into `EVALUATION_ERROR / BLOCKED` with no completed subject oracles. Provider/runtime failures remain `RUNTIME_ERROR / BLOCKED`.

The evaluator also revalidates known `PROTOCOL_DELIVERY` receipt types before subject grading. Unknown delivery sources, malformed bridge receipts, invalid semantic roots, or scenario-identity mismatch block evaluation rather than becoming trusted opaque JSON.

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
- deterministic OpenAI SDK suite, including the original MCP stdio result bridge: **15/15 passed**;
- deterministic MCP protocol suite: **6/6 passed**;
- deterministic MCP remote-auth suite: **3/3 passed**;
- deterministic MCP OAuth-flow suite: **3/3 passed**;
- Python **3.11 minimum / 3.14 latest**, Ruff, formatter, Bandit, dependency audit, package integrity, and all **7/7 CI jobs**: green;
- dependency audit: **no known vulnerabilities found**; the project package itself is skipped because it is not published on PyPI.

This checkpoint remains the historical audited merged implementation baseline. Capabilities added after that checkpoint, including the ToolError-recovery and host-refreshed schema-drift bridges described above, are accepted only after their own exact-head CI, merge, and post-merge `main` verification; documentation does not retroactively redefine the older implementation evidence.
