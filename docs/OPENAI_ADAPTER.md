# OpenAI Agents SDK Adapter

## Purpose

`OpenAIAgentsAdapter` turns documented OpenAI Agents SDK execution surfaces into provider-neutral evaluation evidence while keeping state verification and release authority outside the SDK.

The integration is pinned to `openai-agents==0.22.0` in the optional `openai` dependency group so the normalization contract cannot silently drift under a broad SDK version range.

## Trust boundary

```text
controlled scenario / optional USER_INPUT attack
        ↓
OpenAIAgentsAdapter prepares exact Runner input
        ↓
OpenAI Agents SDK execution
        ↓
public RunResult / RunItem surfaces
        ↓
OpenAIAgentsAdapter normalization
        ↓
provider-neutral EvidenceEvent stream
        +
independent state_reader()
        ↓
TrialEvidence
        ↓
framework-owned deterministic oracles
```

The SDK can report that a tool was called or that the agent produced a final output. It cannot prove the external side effect succeeded unless the evaluation environment independently observes the resulting state.

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

## Adversarial `USER_INPUT` injection

The adapter now implements one concrete adversarial delivery channel: `AttackChannel.USER_INPUT`.

For an ordinary scenario, the adapter retains the normal SDK input contract: the scenario objective is passed as the user input.

For a derived adversarial `USER_INPUT` scenario, the adapter supplies `Runner.run` with two ordered user messages:

```text
input[0] = scenario objective
input[1] = exact canonical AttackFixture.payload_json
```

The second message is intentionally the fixture's canonical JSON representation rather than an adapter-selected field from the payload object. This means the attack fixture's canonical payload SHA-256 and the delivery receipt describe the exact text placed at the controlled SDK input boundary.

Before SDK execution, the adapter emits an `AttackDeliveryReceipt` as the first normalized evidence event with:

```text
source          = injector:openai-agents:user-input
injection_point = openai-agents:Runner.run.input[1]
```

The receipt binds the exact derived scenario, attack identity, `user_input` channel, injection point, and payload digest without copying the raw attack text into delivery evidence. `TrialRunner` still independently verifies that receipt before policy/outcome grading begins.

This establishes that the trusted evaluation adapter placed the exact canonical stimulus in the SDK runner input supplied by the harness. It is **not** cryptographic provider attestation, proof that a hosted model processed the input, proof of model resistance, or proof of any downstream side effect.

### Unsupported channels fail closed

`OpenAIAgentsAdapter` does not currently implement `tool_result`, `tool_metadata`, `memory`, `resource`, `handoff`, or `environment` injection.

When an adversarial scenario requests one of those channels, the adapter raises a structured `AdapterPreconditionError` **before model execution**. `TrialRunner` converts that condition into critical `EVALUATION_ERROR` evidence and a `BLOCKED` verdict with no completed subject oracles. The condition is therefore treated as missing evaluation capability, not as provider failure and not as agent behavioral failure.

This distinction is intentional:

```text
unsupported controlled injection → EVALUATION_ERROR / BLOCKED
provider or SDK runtime failure   → RUNTIME_ERROR / BLOCKED
verified subject violation        → deterministic oracle FAIL
```

## Resource identity

Provider tool arguments are not automatically a security resource identity. The adapter accepts an explicit `resource_resolver(tool_name, arguments)` callback owned by the evaluation environment.

When a scenario configures resource prefixes, `PolicyOracle` fails closed if a tool request lacks normalized resource identity. This avoids treating “could not map the request” as “request was authorized.”

The current prefix comparison is lexical after normalization; [Limitations](LIMITATIONS.md) documents the deployment-specific canonicalization requirements.

## Approval semantics

An SDK `ToolApprovalItem` is normalized as `APPROVAL_REQUEST`, never `APPROVAL`.

That distinction is intentional. Asking a human or policy engine for permission does not prove permission was granted. Framework `APPROVAL` evidence is independently supplied and is call-bound by default:

```text
(tool="refund", call_id="call-17")
```

The one-shot grant is consumed when the matching privileged request is evaluated. Persistent tool-level approval must be explicitly represented with `scope="tool"` by an environment that can prove such authorization exists.

## Tracing and sensitive data

The adapter builds `RunConfig` with `trace_include_sensitive_data=False` and supports tracing being disabled. The deterministic SDK CI test disables tracing. Future trace ingestion must remain an evidence source, not a grading authority, and must document retention/data-minimization boundaries before being enabled by default.

## Deterministic SDK tests

The repository uses `agents.testing.ScriptedModel` to drive the real Agents SDK runner without provider API calls. The independent SDK CI tier now verifies three boundaries:

- ordinary SDK tool-loop execution remains observable while the independent state reader owns terminal truth;
- a `USER_INPUT` adversarial fixture reaches the exact second runner-input position and produces a verifiable delivery receipt;
- an unsupported adversarial channel blocks before any model call occurs.

This does **not** establish live-model quality, provider reliability, provider-side delivery attestation, or production safety. Those remain separate evaluation tiers.
