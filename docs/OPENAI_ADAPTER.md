# OpenAI Agents SDK Adapter

## Purpose

`OpenAIAgentsAdapter` turns documented OpenAI Agents SDK execution surfaces into provider-neutral evaluation evidence while keeping state verification and release authority outside the SDK.

The integration is pinned to `openai-agents==0.22.0` in the optional `openai` dependency group so the normalization contract cannot silently drift under a broad SDK version range.

## Trust boundary

```text
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

## Deterministic SDK test

The repository uses `agents.testing.ScriptedModel` to drive the real Agents SDK runner and tool loop without a provider API call. The test proves the adapter can observe a real SDK tool execution while the independent state reader remains the only source of terminal application state.

This does **not** establish live-model quality, provider reliability, or production safety. Those remain separate evaluation tiers.
