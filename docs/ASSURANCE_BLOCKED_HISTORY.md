# Blocked assurance history

Assurance construction treats a terminal `BLOCKED` verdict as an evaluator/runtime classification, not as a caller-supplied label.

## Bidirectional invariant

When `AssuranceReport.from_session()` constructs `agent-evals/assurance-report/<schema>` from an `EvaluationSessionResult`, the trial verdict and the final evidence envelope must agree in both directions:

- a `BLOCKED` trial must contain blocking evidence recognized by the runtime's canonical `has_blocking_evidence()` predicate;
- a non-`BLOCKED` trial must not contain that blocking evidence.

The canonical blocking evidence kinds are evaluator/runtime failure evidence (`EVALUATION_ERROR` and `RUNTIME_ERROR`). This is the same durable boundary used by `TrialRunner` before deterministic grading.

A caller therefore cannot manufacture historically unsupported uncertainty by constructing an `EvaluatedTrial` with clean evidence, empty oracle results, and `verdict=BLOCKED`. Assurance construction rejects that combination before reliability, release-gate, or report-root claims are emitted.

## Genuine blocked history

A genuine persisted blocked trial remains valid for assurance construction when its final evidence envelope contains the evaluator/runtime failure that caused the trial to stop. `from_session()` does **not** attempt to re-run the failed provider call, re-close the failed evaluation precondition, or run full deterministic grading over evidence whose grading prerequisites did not close. Re-executing or reclassifying an unresolved prerequisite could change history and would collapse the distinction between bad subject behavior and evaluator uncertainty.

Instead, construction verifies that the terminal blocked classification has durable blocking evidence, preserves the no-oracle/no-semantic shape required for `BLOCKED`, and then recomputes session reliability and the release gate from the validated terminal facts.

## Known policy facts inside a blocked trial

`BLOCKED` means the complete evaluation outcome is unresolved. It does **not** mean every fact observed before the blocking condition is unknown.

A blocked run can contain an explicit `POLICY_VIOLATION` that is already a resolved fact. One concrete example is native HITL turn-budget handling: the adapter can know that the subject exceeded the configured turn budget while a different approval-continuation relation remains unverifiable. The trial must stay `BLOCKED`, because the missing relation prevents valid complete grading, but the known policy violation must not disappear from release authority.

The current Assurance schema therefore adds `BlockedPolicyViolationSnapshot` to blocked trial records. Each snapshot is derived only by `AssuranceReport.from_session()` from an actual `POLICY_VIOLATION` event in the exact final `TrialEvidence` and records:

- the event sequence;
- the exact event digest;
- the event source;
- the policy-violation reason used by deterministic policy semantics.

The event digest commits to the complete event, including its kind, payload, source, sequence, observed timestamp, and event-level critical flag. The duplicated source and reason are review material; they are not independent evidence authority.

The current schema does not create policy snapshots for non-blocked trials. Those trials continue to derive critical policy authority from completed deterministic oracle results.

## Release-gate semantics

An explicit blocked policy fact is non-compensatory. If a release policy permits some blocked trials but sets `max_critical_violations=0`, a blocked trial containing an explicit `POLICY_VIOLATION` still causes the critical-violation gate to reject the session.

Multiple explicit policy-violation events in the same blocked trial are all retained as separate snapshots for review and integrity. For the release counter they contribute one policy-oracle-equivalent critical failure, matching resolved `PolicyOracle` behavior, where multiple policy reasons are returned inside one critical failed policy oracle result.

A blocked trial containing only evaluator/runtime blocking evidence and no explicit policy violation does not invent critical subject authority. It remains governed by `max_blocked_trials` and the other release thresholds exactly as configured.

This preserves both sides of the framework's central distinction:

- **known bad** remains non-compensatory even when another relation is unknown;
- **unknown** is not converted into bad merely to make release gating simpler.

## Resolved history

For `PASS`, `FAIL`, and `INCONCLUSIVE` trials, The current Assurance schema rejects any evaluator/runtime blocking evidence and re-establishes the ordinary pre-grading closure before accepting deterministic oracle facts and, when configured, semantic judgment evidence.

This keeps the classification boundary explicit:

- **bad subject behavior** is resolved by deterministic or semantic grading;
- **unknown evaluation outcome** is `BLOCKED` only when evaluator/runtime evidence proves why grading could not validly complete;
- **known explicit policy facts retained before a block** are preserved as bounded report facts without pretending the blocked trial was fully graded.

## Standalone report parsing

The serialized Assurance Report intentionally stores evidence roots rather than duplicating every evidence event. current schema additionally stores the bounded blocked-policy snapshots described above. Loading a standalone current report can therefore recompute report-level shape, critical-violation count, reliability, gate output, and `report_root`, but it still cannot independently reconstruct the complete event stream referenced by an `evidence_root`.

The exact correspondence between each blocked-policy snapshot and its source event is established when constructing the report from the exact session/evidence objects. Historical event-level re-establishment still requires the exact evidence/replay path. The `report_root` binds the snapshots into report content, but remains a content-integrity commitment rather than a signature, trusted timestamp, publisher identity, or proof of honest evidence production.

## Schema evolution

This hardening changes the Assurance Report derivation surface, so it uses a distinct revision rather than silently changing predecessor schema semantics:

- evidence: `agent-evals/trial-evidence/<schema>` (unchanged)
- assurance report: `agent-evals/assurance-report/<schema>`
- report-root domain: `agent-evals/assurance-report/<schema>\0`

predecessor reports are rejected by the current report model rather than being interpreted under the new blocked-policy criticality rules.
