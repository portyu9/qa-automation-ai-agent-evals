# OpenAI cross-feature composition

This document defines the execution-strength contract used when an evaluator-owned OpenAI bridge is combined with delegated handoff authority.

## Why composition needs an explicit rule

`OpenAIAgentsAdapter` normalizes ordinary OpenAI Agents SDK execution. It intentionally does not claim that every tool request, tool result, or approval request has been bound to the public SDK run-item generating-agent identity. Direct callers that need delegated handoff authority must therefore use `OpenAIAgentsHandoffAuthorityAdapter`; the framework does not silently reinterpret a direct base-adapter run as stronger evidence.

Specialized evaluator-owned bridges are different. Retrieval, side-effect, and controlled MCP integrations wrap or instrument subject execution in order to establish an additional evaluator-owned relation. If one of those bridges were to delegate internally through the weaker base adapter while the same scenario enabled handoff authority, the specialized relation could close while the agent provenance required for delegated-authority grading was absent. Treating that absence as a subject policy violation would confuse evaluator uncertainty with subject behavior.

The composition invariant is therefore:

> A specialized OpenAI subject-execution bridge must normalize the subject run at the strongest provenance level required by the scenario before it adds its specialized receipt.

## Scenario-aware execution

Specialized bridges delegate through `execute_composed_openai()` in `agent_evals.adapters.openai_composed`.

- When `scenario.authority.has_handoff_authority` is false, the helper uses `OpenAIAgentsAdapter` and preserves ordinary OpenAI normalization.
- When `scenario.authority.has_handoff_authority` is true, the helper uses `OpenAIAgentsHandoffAuthorityAdapter` so normalized tool requests, tool results, and approval requests carry the public SDK run-item generating-agent identity and native handoffs preserve their source/target attribution checks.
- The public behavior of direct `OpenAIAgentsAdapter` use does not change. A direct caller does not receive stronger provenance implicitly.
- `OpenAIAgentsHITLApprovalAdapter` already subclasses the handoff-authority adapter and therefore does not require the composition helper.
- Semantic judging is evaluator-owned grading after subject execution rather than a specialized subject-runtime bridge, so it is outside this routing rule.

## Specialized bridge matrix

The scenario-aware execution rule applies to every evaluator-owned OpenAI bridge that runs the subject while establishing one of the following relations:

| Bridge | Specialized relation retained after subject normalization |
| --- | --- |
| `OpenAIAgentsRetrievalAdapter` | exact evaluator-ranked retrieval delivery |
| `OpenAIAgentsSideEffectIdempotencyAdapter` | run-local physical side-effect observation and idempotency |
| `OpenAIAgentsMCPToolResultAdapter` | same-call controlled MCP tool-result delivery |
| `OpenAIAgentsMCPToolMetadataAdapter` | exact model-visible MCP metadata delivery |
| `OpenAIAgentsMCPToolErrorRecoveryAdapter` | MCP ToolError retry-and-recovery relation |
| `OpenAIAgentsMCPToolIdentityDriftAdapter` | host-refreshed MCP tool-identity adaptation |
| `OpenAIAgentsMCPToolSchemaDriftAdapter` | host-refreshed MCP schema adaptation |
| `OpenAIAgentsMCPToolStaleCacheAdapter` | host-refreshed stale-tool removal delivery |

The specialized bridge still owns only its existing observation/receipt contract. Scenario-aware routing does not broaden the receipt, invent additional subject behavior, or change provider-neutral evidence schemas.

## `bad != unknown` pre-grading boundary

The runtime pre-grading closure independently protects the classification boundary. When handoff authority is combined with a specialized retrieval, side-effect, or verified protocol/MCP relation, tool request/result/approval-request evidence must contain a stable generating-agent identity, and native handoff evidence must contain stable source and target identities.

If that provenance is unavailable, pre-grading raises `handoff_provenance_unverified` from `evaluator:handoff-provenance`. `TrialRunner` records evaluator-owned blocking evidence and the trial is `BLOCKED`; the deterministic policy oracle is not allowed to convert missing evaluator provenance into a critical subject `FAIL`.

This safeguard is deliberately narrower than handoff authority itself. An ordinary direct run through the weaker base adapter retains the existing deterministic policy contract instead of being silently upgraded or reclassified.

## Ordering with other evaluation contracts

The shared pre-grading closure remains conjunctive and behavior-bearing. Its relevant order is:

1. adversarial attack delivery;
2. protocol/MCP delivery;
3. retrieval delivery;
4. side-effect observation;
5. composed handoff provenance;
6. approval intent;
7. deterministic policy/outcome/side-effect grading;
8. semantic grading, when configured and deterministic grading permits it.

A successful specialized receipt cannot mask a later unresolved provenance or approval relation. Conversely, provenance attribution does not validate retrieval, side-effect, or MCP delivery by itself; each specialized verifier still closes its own exact relation.

## Replay and assurance reports

No replay exception is introduced. Exact evidence replay preserves the original normalized events and specialized receipts. The same pre-grading closure is re-applied before resolved replay evidence can be graded.

`AssuranceReport.from_session()` also invokes the shared pre-grading closure for non-blocked trials before it rederives deterministic oracle results from the exact scenario and evidence. A resolved report therefore cannot be constructed from specialized handoff evidence that would have been blocked by the runtime composition boundary.

The assurance report remains a bound summary rather than a replacement for event-level replay; historical re-establishment of these relations still requires the exact scenario and evidence envelope.

## Non-goals

This composition rule does not:

- make SDK agent names cryptographic principals;
- infer hidden provider handoffs or tool ownership;
- weaken root or delegated authority policy;
- treat MCP server identity as agent identity;
- fabricate missing run-item attribution;
- change turn-budget, tool-call-budget, or handoff-budget semantics;
- change retrieval, side-effect, protocol, approval, semantic, evidence, or assurance schemas.

When the public SDK cannot establish the required generating-agent provenance, the evaluator must remain uncertain rather than manufacture authority evidence.
