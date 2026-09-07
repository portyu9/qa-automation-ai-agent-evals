# Turn-Budget Authority

## Purpose

`AuthorityPolicy.max_turns` is scenario-owned, behavior-bearing execution authority. Its enforcement boundary is intentionally different from `max_tool_calls` and `max_handoffs`.

The provider-neutral core can independently count normalized `TOOL_REQUEST` and `HANDOFF` evidence, so `PolicyOracle` can rederive those two budgets without trusting a provider's private execution counter. There is deliberately no provider-neutral `TURN` event because a runtime turn is an orchestration-specific execution concept rather than a stable cross-provider observation.

The result is an explicit split of responsibility: **the runtime adapter enforces the turn bound; the deterministic policy oracle grades a runtime-confirmed violation.**

## Adapter contract

Any `AgentAdapter` that owns a multi-turn execution loop must satisfy all of the following:

1. Bind the exact `scenario.authority.max_turns` value to the runtime's real turn limiter before execution.
2. If the runtime integration cannot establish or enforce a compatible turn bound, fail closed rather than return gradeable evidence that implies the bound was honored. `AdapterPreconditionError` is the normal controlled-evaluation path when this is knowable before or during adapter setup.
3. When the runtime positively reports that the bound was exhausted, normalize that resolved condition as critical `POLICY_VIOLATION` evidence. Do not preserve raw provider exception detail in durable evidence.
4. Do not substitute message count, tool-call count, handoff count, model-response count, or another locally convenient proxy for the runtime's documented turn counter unless that quantity is the runtime's actual turn-limit contract.
5. Do not manufacture a synthetic provider-neutral turn event merely to duplicate a runtime-owned counter.

A custom adapter that ignores `max_turns` is therefore non-conforming even if every other normalized event is structurally valid.

## Deterministic grading boundary

The budget paths are deliberately asymmetric:

```text
TOOL_REQUEST events ──counted by core──> max_tool_calls
HANDOFF events      ──counted by core──> max_handoffs

scenario.max_turns
        ↓ exact bound
runtime-owned turn limiter
        ↓ confirmed exhaustion
critical POLICY_VIOLATION
        ↓
PolicyOracle
        ↓
critical FAIL
```

`PolicyOracle` independently rederives tool-call and handoff budgets from normalized evidence. For turn exhaustion, it consumes the adapter's explicit critical policy-violation observation. This does not grant the adapter grading authority: the adapter reports the runtime condition; the framework still owns deterministic grading and the final trial verdict.

The distinction between **failure** and **uncertainty** remains important. A runtime-confirmed budget exhaustion is resolved subject behavior and is eligible for deterministic critical `FAIL`. Inability to establish the configured runtime bound is evaluator uncertainty and must fail closed as `BLOCKED`. Other unresolved evaluation preconditions can also retain their normal fail-closed precedence; a known turn violation does not fabricate missing delivery, approval, protocol, retrieval, or observation evidence.

## Pinned OpenAI Agents SDK boundary

The repository pins `openai-agents==0.22.0`.

`OpenAIAgentsAdapter` passes the exact scenario value as `Runner.run(..., max_turns=scenario.authority.max_turns)`. The pinned SDK's `MaxTurnsExceeded` signal is converted to a critical `POLICY_VIOLATION` carrying the configured bound, after which `PolicyOracle` resolves the trial as a critical policy failure when the remaining evaluation preconditions are closed.

Adapters that inherit the base OpenAI execution path inherit this enforcement. Specialized integrations that delegate their behavioral run to that base path retain the same bound. Integrations that own additional runtime calls remain responsible for applying the same scenario-owned bound to every multi-turn loop they own; an incomplete specialized evaluation relation is not reclassified merely to force a `FAIL`.

`OpenAIAgentsHITLApprovalAdapter` owns two direct SDK run phases: the initial run that can produce a native approval interruption and the continuation of the same `RunState` after the evaluator applies the scenario decision. Both phases retain the scenario-owned SDK turn limit. The adapter also installs the pinned SDK's public `max_turns` error handler as an observation tap only: it snapshots the accumulated public run items and usage supplied to that handler, returns no fallback result, and therefore allows the SDK to raise its real `MaxTurnsExceeded` signal unchanged. The framework never turns budget exhaustion into a synthetic successful model output.

When exhaustion occurs after a native approval decision and the SDK exposes the accumulated resumed run relation, the adapter first reconstructs the same exact approval request → evaluator decision → approved/rejected continuation evidence that ordinary HITL verification requires, then appends the critical turn-budget `POLICY_VIOLATION`. This preserves both facts: the approval relation was resolved, and the subject nevertheless exhausted its authoritative turn budget. Deterministic policy grading can therefore return critical `FAIL` instead of downgrading the confirmed violation to generic runtime uncertainty.

If the SDK cannot expose enough accumulated evidence to close a stronger HITL relation, the adapter does not fabricate that relation. The confirmed policy-violation event may still be retained, but normal approval verification keeps the trial `BLOCKED` because evaluator uncertainty remains unresolved. This is the same non-compensatory precedence described above.

Deterministic integration coverage uses the real pinned SDK runner with `agents.testing.ScriptedModel` and no provider API call. The base regression intentionally requires more model turns than the scenario permits. The native-HITL regression separately proves the resumed approval path: the protected tool executes exactly once after the evaluator decision, the SDK stops before another model turn, the exact approval lifecycle remains verifiable, the adapter emits the same critical turn-budget policy fact, `OutcomeOracle` can still confirm the observed terminal state, and the final evaluator verdict is `FAIL` rather than `PASS` or `BLOCKED`.

## Replay and assurance

Replay regrades the recorded evidence. It does not rerun the provider/runtime loop and cannot reconstruct a hidden historical turn count that was never recorded as an authoritative runtime condition. A historical critical turn-budget `POLICY_VIOLATION` remains gradeable because it is already normalized evidence; absence of such evidence is not retroactively interpreted as proof that an unobserved runtime honored the limit.

Assurance artifacts therefore remain evidence-bound rather than provider-counter reconstructions.

## Non-claims

This boundary does **not** claim:

- that the provider-neutral core can infer hidden provider or orchestration turn counts from ordinary events;
- that a tool call, handoff, message, or output is universally equivalent to one runtime turn;
- that replay can recover an unrecorded runtime counter;
- that the pinned deterministic SDK test proves live-provider availability or live-model behavior;
- that arbitrary custom adapters enforce the contract merely because they satisfy the Python protocol structurally;
- that a critical turn-budget event can override an otherwise unresolved evaluator-owned precondition;
- that the SDK error-handler snapshot is provider attestation, a signature, or an independent turn counter;
- or that a new `TURN` evidence kind is required or desirable.

The claim is narrower: **a runtime integration that owns turns must enforce the exact scenario-owned turn limit or fail closed, and a runtime-confirmed exhaustion is normalized into deterministic policy evidence rather than treated as successful execution.**
