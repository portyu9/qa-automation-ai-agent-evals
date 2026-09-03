# OpenAI Agents SDK Adapter

## Purpose

`OpenAIAgentsAdapter` turns documented OpenAI Agents SDK execution surfaces into provider-neutral evaluation evidence while keeping state verification and release authority outside the SDK.

The integration is pinned to `openai-agents==0.22.0` in the optional `openai` dependency group so the normalization contract cannot silently drift under a broad SDK version range.

## Trust boundary

```text
controlled scenario + optional adversarial fixture
        ↓
OpenAIAgentsAdapter prepares an isolated execution boundary
        ↓
USER_INPUT injector or local FunctionTool TOOL_RESULT injector
        ↓
OpenAI Agents SDK execution
        ↓
public RunResult / RunItem surfaces
        ↓
provider-neutral EvidenceEvent stream
        +
independent state_reader()
        ↓
TrialEvidence
        ↓ exact delivery verification when adversarial
framework-owned deterministic oracles
```

The SDK can report that a tool was called or that the agent produced a final output. It cannot prove an external side effect succeeded unless the evaluation environment independently observes the resulting state.

## Currently normalized evidence

The adapter handles documented public surfaces for:

- tool-call requests and call identifiers;
- tool-call outputs;
- handoff completion;
- tool approval requests;
- input/output/tool guardrail results;
- guardrail tripwire exceptions;
- final output;
- token usage;
- max-turn exhaustion.

`MaxTurnsExceeded` becomes a critical policy-violation event because the scenario's authority contract owns the turn budget. Generic provider/runtime exceptions remain runtime failures and are converted by `TrialRunner` to `BLOCKED` evidence.

## Concrete adversarial channels

The adapter currently implements two delivery channels:

| Channel | Concrete boundary |
|---|---|
| `user_input` | exact second user message supplied to `Runner.run` |
| `tool_result` | first invocation result of one targeted local SDK `FunctionTool` |

All other channels remain unsupported by this adapter and fail closed before pretending the attack ran.

## `USER_INPUT` injection

For an ordinary scenario, the adapter retains the normal SDK input contract: the scenario objective is passed as the user input.

For a derived `USER_INPUT` scenario, `Runner.run` receives two ordered user messages:

```text
input[0] = scenario objective
input[1] = exact canonical AttackFixture.payload_json
```

The second message is the fixture's canonical JSON representation rather than an adapter-selected payload field. The delivery receipt's payload SHA-256 therefore binds the exact text placed at the controlled SDK input boundary.

The adapter emits the matching `AttackDeliveryReceipt` with:

```text
source          = injector:openai-agents:user-input
injection_point = openai-agents:Runner.run.input[1]
```

The receipt contains the payload digest, not the raw attack body. `TrialRunner` independently verifies it before policy/outcome grading.

## `TOOL_RESULT` injection

`TOOL_RESULT` is implemented for **local OpenAI Agents SDK `FunctionTool` instances only**. It does not claim interception of hosted tools, MCP-discovered tools, external tool servers, deferred tools, or arbitrary SDK tool implementations.

### Payload contract

A `TOOL_RESULT` fixture must contain an identity-bearing JSON object with at least:

```json
{
  "tool": "lookup_customer",
  "result": {
    "instructions": "controlled adversarial content"
  }
}
```

`ToolResultAttackPayload` validates the routing contract. `tool` selects the exact local target and may not contain surrounding whitespace. `result` is required, and additional JSON fields are allowed for realistic result envelopes.

The **complete canonical `AttackFixture.payload_json`** is the replacement tool output returned to the model loop. This is intentional: the existing receipt's canonical payload digest then binds the exact replacement bytes rather than a separately transformed subset.

### Per-trial isolation

The reusable agent and original tool are never mutated.

For each adversarial execution, the adapter:

1. resolves exactly one local target by its fixture-bound tool name;
2. requires that target to be an SDK `FunctionTool`;
3. copies only that `FunctionTool` using its supported copy behavior;
4. wraps the copied `on_invoke_tool` callback;
5. clones the agent with a fresh tool list containing the wrapped copy;
6. stores delivery state only in a per-execution recorder.

This prevents cross-trial contamination when an adapter or agent object is reused.

### First targeted invocation

On the first targeted tool invocation in that trial, the wrapper:

- reads the SDK tool call ID;
- does **not** execute the original target function;
- returns exact canonical `attack.payload_json` as the tool result;
- creates a receipt whose injection point binds the tool name and exact call ID:

```text
openai-agents:FunctionTool:<tool>:call:<call_id>:output
```

The receipt source is:

```text
injector:openai-agents:tool-result
```

Normalized evidence preserves chronology:

```text
TOOL_REQUEST
ATTACK_DELIVERY
TOOL_RESULT
```

The `TOOL_RESULT` event contains the same exact canonical fixture JSON observed by the model loop. The receipt itself still stores only the payload digest.

If the same targeted tool is invoked again during that trial, subsequent invocations use the copied tool's original behavior. This v1 mode therefore means **replace the first matching result**, not permanently poison every invocation.

### Side-effect semantics

Because the injected first invocation deliberately skips the original function, this mode is best suited to controlled retrieval/read tools where the purpose is to simulate a malicious or compromised result source.

It does **not** claim to preserve the side effects of the original function. A future “execute normally, then perturb only the returned result” mode would be a different delivery contract and should be explicit rather than silently changing this one.

### Fail-closed routing

The adapter precondition-blocks when:

- the fixture payload does not satisfy the `tool` + `result` contract;
- the target name is absent;
- the target exists but is not a local `FunctionTool`;
- the target name is ambiguous;
- the SDK call identity cannot be bound safely.

If the configured target simply never gets called, no receipt is emitted. The ordinary delivery verifier then returns the adversarial trial as `BLOCKED` because the requested attack was never delivered.

A skipped tool call therefore cannot become a false adversarial PASS.

## Unsupported channels fail closed

`OpenAIAgentsAdapter` does not currently implement `tool_metadata`, `memory`, `resource`, `handoff`, or `environment` injection.

A requested unsupported channel raises a structured `AdapterPreconditionError` before model execution. `TrialRunner` converts that into critical `EVALUATION_ERROR` evidence and `BLOCKED` with no completed subject oracles.

```text
unsupported controlled injection → EVALUATION_ERROR / BLOCKED
provider or SDK runtime failure   → RUNTIME_ERROR / BLOCKED
verified subject violation        → deterministic oracle FAIL
```

## Resource identity

Provider tool arguments are not automatically security resource identities. The adapter accepts an explicit `resource_resolver(tool_name, arguments)` callback owned by the evaluation environment.

When a scenario configures resource prefixes, `PolicyOracle` fails closed if a tool request lacks normalized resource identity. This avoids treating “could not map the request” as “request was authorized.”

The current prefix comparison is lexical after normalization; [Limitations](LIMITATIONS.md) documents deployment-specific canonicalization requirements.

## Approval semantics

An SDK `ToolApprovalItem` is normalized as `APPROVAL_REQUEST`, never `APPROVAL`.

Asking a human or policy engine for permission does not prove permission was granted. Framework `APPROVAL` evidence is independently supplied and call-bound by default:

```text
(tool="refund", call_id="call-17")
```

Persistent tool-level approval must be explicitly represented by an environment that can prove such authorization exists.

## Tracing and sensitive data

The adapter builds `RunConfig` with `trace_include_sensitive_data=False` and supports tracing being disabled. Deterministic SDK CI disables tracing.

Attack-delivery receipts do not duplicate raw attack bodies. The controlled SDK input/tool result necessarily contains the adversarial stimulus because that content is the test input; persistence and trace policy must still minimize sensitive data independently.

## Deterministic SDK tests

The repository uses `agents.testing.ScriptedModel` to drive the real Agents SDK runner without provider API calls. The independent SDK tier verifies:

- ordinary SDK tool-loop execution while the independent state reader retains terminal truth;
- exact `USER_INPUT` placement and receipt creation;
- exact `TOOL_RESULT` replacement reaching the subsequent model call;
- call-ID-bound receipt ordering between request and result;
- the original target function is not executed on the injected invocation;
- the original tool object remains unchanged and works normally in a subsequent ordinary trial;
- missing tool-result targets block before model execution;
- unsupported remaining channels block before model execution.

These tests prove behavior at the controlled SDK harness boundary. They do **not** establish live-model quality, provider reliability, provider-side delivery attestation, hosted/MCP tool interception, or production safety.
