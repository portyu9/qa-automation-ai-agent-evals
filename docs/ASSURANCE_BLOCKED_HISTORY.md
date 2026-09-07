# Blocked assurance history

Assurance construction treats a terminal `BLOCKED` verdict as an evaluator/runtime classification, not as a caller-supplied label.

## Bidirectional invariant

When `AssuranceReport.from_session()` constructs `agent-evals/assurance-report/v4` from an `EvaluationSessionResult`, the trial verdict and the final evidence envelope must agree in both directions:

- a `BLOCKED` trial must contain blocking evidence recognized by the runtime's canonical `has_blocking_evidence()` predicate;
- a non-`BLOCKED` trial must not contain that blocking evidence.

The canonical blocking evidence kinds are evaluator/runtime failure evidence (`EVALUATION_ERROR` and `RUNTIME_ERROR`). This is the same durable boundary used by `TrialRunner` before deterministic grading.

A caller therefore cannot manufacture historically unsupported uncertainty by constructing an `EvaluatedTrial` with clean evidence, empty oracle results, and `verdict=BLOCKED`. Assurance construction rejects that combination before reliability, release-gate, or report-root claims are emitted.

## Genuine blocked history

A genuine persisted blocked trial remains valid for assurance construction when its final evidence envelope contains the evaluator/runtime failure that caused the trial to stop. `from_session()` does **not** attempt to re-run the failed provider call or re-close the failed evaluation precondition. Re-executing a failed prerequisite could change history and would make replay nondeterministic.

Instead, construction verifies that the terminal blocked classification has durable blocking evidence, preserves the no-oracle/no-semantic shape required for `BLOCKED`, and then recomputes session reliability and the release gate from the validated terminal verdicts.

## Resolved history

For `PASS`, `FAIL`, and `INCONCLUSIVE` trials, Assurance v4 continues to reject any blocking evidence and then re-establishes the ordinary pre-grading closure before accepting deterministic oracle facts and, when configured, semantic judgment evidence.

This keeps the distinction explicit:

- **bad subject behavior** is resolved by deterministic or semantic grading;
- **unknown evaluation outcome** is `BLOCKED` only when evaluator/runtime evidence proves why grading could not validly complete.

## Standalone report parsing

The serialized Assurance Report intentionally stores evidence roots rather than duplicating every evidence event. Consequently, loading a standalone v4 report can recompute report-level shape, reliability, gate output, and `report_root`, but it cannot independently inspect the event stream referenced by an `evidence_root`.

The blocked-evidence invariant is therefore re-established when constructing a report from the exact session/evidence objects. Historical event-level re-establishment still requires the exact evidence/replay path. The `report_root` remains a content-integrity commitment, not a signature, trusted timestamp, publisher identity, or proof of honest evidence production.

## Versioning

This hardening changes no provider-neutral evidence or report schema. The current versions remain:

- evidence: `agent-evals/trial-evidence/v2`
- assurance report: `agent-evals/assurance-report/v4`
