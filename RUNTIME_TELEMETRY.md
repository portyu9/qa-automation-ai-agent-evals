# Runtime timing telemetry

The evaluator keeps two timing concepts deliberately separate.

`TrialEvidence.elapsed_ms` is evidence-envelope telemetry supplied by an adapter or preserved by exact evidence replay. It remains part of the historical `TrialEvidence` value and its evidence root. A large, small, or otherwise unusual adapter-reported value is not independently promoted into evaluator timing authority.

`EvaluatedTrial.evaluator_elapsed_ms` is a local wall-clock observation measured by `TrialRunner` with the evaluator's monotonic clock around the complete returned trial lifecycle. It includes evaluator-side work as well as awaited adapter and semantic-judge work. `EvaluationSession` retains the value because its trials are the `EvaluatedTrial` objects returned by `TrialRunner`.

Manually or historically constructed `EvaluatedTrial` objects may leave `evaluator_elapsed_ms` unset. When explicitly supplied, the value must be finite and non-negative. This keeps existing hand-built/replayed runtime-result construction compatible without inventing a measurement that the evaluator did not actually observe.

Replay preserves historical timing: an `EvidenceReplayAdapter` returns the recorded `TrialEvidence.elapsed_ms`, while the enclosing live `TrialRunner` separately measures how long the replay/evaluation operation takes locally. The two values are not expected to match.

Evaluator deadline results are a special fail-closed case. When a configured evaluator wall-clock deadline expires, the deadline `TrialEvidence` uses evaluator-observed elapsed time because no completed adapter timing should be fabricated as the timeout observation. The returned `EvaluatedTrial` also carries the independently finalized `evaluator_elapsed_ms` for the complete returned runtime operation. Deadline expiry remains `BLOCKED`, never subject `FAIL`.

The evaluator-observed duration is runtime telemetry only in this slice. It is not persisted into Assurance Report v6, used as release-gate authority, or treated as a statistical latency contract. Provider token/cost telemetry, pricing provenance, persisted performance distributions, and release thresholds remain separate work.

## Nonclaims

`evaluator_elapsed_ms` does **not** prove provider latency, target-system execution time, network-only latency, provider-side cancellation, target quiescence, SLA compliance, authenticated telemetry, attestation, or where the observed time was spent. It measures only the local evaluator's monotonic wall-clock interval around a returned `TrialRunner` operation.
