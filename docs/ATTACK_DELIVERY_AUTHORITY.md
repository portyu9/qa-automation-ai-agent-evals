# Attack delivery authority

Adversarial evaluation distinguishes two independent questions:

1. **Does the recorded receipt exactly match the scenario-bound attack contract?**
2. **Was a fresh live receipt produced by a runtime path that actually owns controlled injection?**

Both must hold before live adversarial evidence can become gradeable.

## Semantic receipt verification

`AttackDeliveryReceipt` binds the scenario identity, attack identity, channel, injection point, and hash of the canonical attack payload. `verify_attack_delivery()` revalidates those commitments and rejects missing, duplicate, malformed, foreign-scenario, or non-`injector:` evidence.

That validation is necessary for replay, but it is not sufficient to grant live producer authority. The scenario itself contains enough material to reconstruct an internally valid receipt, and the receipt's `injection_point` is an observed claim rather than an independently authenticated capability. Likewise, an `injector:<identity>` source string is a durable evidence role, not a security token.

## Fresh live producer boundary

Before pre-grading closure, `TrialRunner` reserves live `ATTACK_DELIVERY` evidence for exact framework-controlled OpenAI adapter types whose execution paths own the repository's adversarial injection machinery.

The allowed producer set covers:

- `OpenAIAgentsAdapter`;
- `OpenAIAgentsHandoffAuthorityAdapter`;
- `OpenAIAgentsHITLApprovalAdapter`;
- `OpenAIAgentsRetrievalAdapter`;
- `OpenAIAgentsSideEffectIdempotencyAdapter`;
- the six controlled MCP bridge adapters for tool result, tool metadata, ToolError recovery, identity drift, schema drift, and stale cache.

Specialized retrieval, side-effect, and MCP adapters are included because they delegate subject execution through the shared controlled OpenAI execution path and preserve the resulting attack-delivery evidence. Handoff-aware execution uses the stronger attribution adapter without changing who owns attack injection.

The boundary uses exact type equality. A subclass cannot inherit producer authority merely by inheriting a class name or method implementation.

If any other live adapter returns `ATTACK_DELIVERY`, the trial receives a critical evaluator error with code `attack_delivery_live_injection` and terminates `BLOCKED` before deterministic grading.

## Exact replay

`EvidenceReplayAdapter` is deliberately exempt from the live producer check. Replay does not claim to perform a fresh attack. It re-establishes a previously recorded evidence envelope and then re-runs semantic receipt verification, pre-grading closure, deterministic grading, and any other replay-valid checks against that history.

This means a historically valid attack receipt can remain reproducible without pretending that replay itself injected the attack again.

## Cross-feature composition

Producer authority does not imply that every cross-feature combination is supported. A controlled adapter must still return the exact delivery evidence required by the scenario. If a specialized path cannot establish an attack receipt, ordinary `verify_attack_delivery()` keeps the trial `BLOCKED`.

Native HITL execution preserves both static and recorder-driven adversarial delivery without changing their evidence meaning. Static prepared receipts for `USER_INPUT`, `TOOL_METADATA`, `MEMORY`, and `RESOURCE` are retained exactly once before normalized SDK run items, so a later approval interruption and resume cannot erase the fact that the attack was already delivered. Recorder-driven `TOOL_RESULT`, `HANDOFF`, and `ENVIRONMENT` receipts remain emitted at their actual invocation or consumption boundary; because those channels do not populate the static prepared tuple, the shared HITL normalization path does not duplicate them.

The resulting chronology is evidence-driven rather than feature-priority-driven. A static attack delivered before model execution appears before the native approval request; the evaluator decision follows that approval request; approved execution and its result follow the decision. Approval stitching rederives its request sequence and authority-path commitment from the shifted normalized history, so adding the attack receipt does not reuse stale sequence numbers or weaken approval verification.

The same prepared-evidence normalization is used for ordinary completion, native approval resume, initial turn-budget exhaustion, and resumed turn-budget exhaustion. Stronger relations remain non-compensatory: preserving attack delivery does not manufacture missing approval, protocol, retrieval, side-effect, authority, or runtime evidence, and any unresolved relation still keeps the trial fail-closed.

## Trust boundary

This control prevents an ordinary live adapter from converting scenario-readable data into a false adversarial PASS by manufacturing a structurally valid receipt. It does not provide cryptographic attestation of the runtime, authenticate repository code at execution time, or prove that external infrastructure is uncompromised. Those are separate deployment and provenance concerns.

No evidence schema change is introduced by this boundary.
