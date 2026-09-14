# Runtime telemetry

The evaluator keeps timing, token, and cost concepts deliberately separated by what it actually observes and who owns the measurement.

## Timing

`TrialEvidence.elapsed_ms` is evidence-envelope telemetry supplied by an adapter or preserved by exact evidence replay. It remains part of the historical `TrialEvidence/v2` value and its evidence root. A large, small, or otherwise unusual adapter-reported value is not independently promoted into evaluator timing authority.

`EvaluatedTrial.evaluator_elapsed_ms` is a local wall-clock observation measured by `TrialRunner` with the evaluator's monotonic clock around the complete returned trial lifecycle. It includes evaluator-side work as well as awaited adapter and semantic-judge work. `EvaluationSession` retains the value because its trials are the `EvaluatedTrial` objects returned by `TrialRunner`.

Manually or historically constructed `EvaluatedTrial` objects may leave `evaluator_elapsed_ms` unset. When explicitly supplied, the value must be finite and non-negative. This keeps existing hand-built/replayed runtime-result construction compatible without inventing a measurement that the evaluator did not actually observe.

Replay preserves historical timing: an `EvidenceReplayAdapter` returns the recorded `TrialEvidence.elapsed_ms`, while the enclosing live `TrialRunner` separately measures how long the replay/evaluation operation takes locally. The two values are not expected to match.

Evaluator deadline results are a special fail-closed case. When a configured evaluator wall-clock deadline expires, the deadline `TrialEvidence` uses evaluator-observed elapsed time because no completed adapter timing should be fabricated as the timeout observation. The returned `EvaluatedTrial` also carries the independently finalized `evaluator_elapsed_ms` for the complete returned runtime operation. Deadline expiry remains `BLOCKED`, never subject `FAIL`.

## Token and cost provenance

Historical `TrialEvidence/v2` already root-binds `input_tokens`, `output_tokens`, and `estimated_cost_usd` as terminal scalar telemetry. That root proves only that those scalar values are part of the recorded evidence envelope. It does not identify who counted tokens, which tokenizer was used, which pricing schedule produced a cost number, or whether a provider billed that amount. The v2 schema and root domain remain unchanged.

New `TrialRunner` results attach `RuntimeMetricProvenance` using schema `agent-evals/runtime-metric-provenance/v1`. The sidecar binds the exact trial ID, `TrialEvidence/v2` evidence root, runtime-adapter identity, token/cost scalar values, bounded source metadata, pricing status, and a domain-separated provenance root. Its authority is always `unverified_telemetry`; adapters cannot self-declare a stronger authority class.

Generic/manual adapters receive explicit unknown token-source and pricing provenance unless they expose a bounded `metric_provenance_assertion`. Such an assertion may identify a token source and may identify a pricing source only when a pricing version is also supplied. The evaluator revalidates the assertion before subject execution. Invalid or unbounded assertions fail closed as evaluator uncertainty (`BLOCKED`), not subject `FAIL`.

Known built-in OpenAI Agents adapters are labeled from their exact framework class identity with token source `openai-agents-sdk:context_wrapper.usage`, matching the public SDK usage surface from which the adapter obtains its normalized counts. This remains unverified telemetry. The framework does not infer a tokenizer version, provider billing identity, or pricing schedule from those counts. Because the adapter does not calculate cost from a versioned price table, pricing provenance is explicitly `unavailable` rather than fabricated.

Exact `EvidenceReplayAdapter` execution is deliberately weaker. It preserves the historical v2 token/cost scalars but records origin `historical_replay`, token source unknown, and pricing provenance unknown. A replay cannot upgrade a historical scalar into provider-verified usage or reconstruct a pricing source/version that the historical schema never persisted.

`RuntimeMetricProvenance.provenance_root` is an integrity binding over the sidecar material. It is not a signature, authenticated provider identity, billing attestation, non-repudiation proof, or independent tokenization/pricing verification. Mutating the evidence root, metric values, source metadata, or pricing metadata breaks the sidecar relation.

`EvaluatedTrial.metric_provenance` is optional for manually/historically constructed trial objects so old test fixtures and explicit legacy construction do not acquire invented provenance. Trials produced by the current `TrialRunner` carry the sidecar, and repeated `EvaluationSession` results retain it through their tuple of `EvaluatedTrial` objects.

The metric sidecar is telemetry only in this slice. It is not persisted into the current Assurance Report schema, not consumed as release-gate authority, and not used to strengthen reliability/statistical claims. A future stronger token/cost authority would require a separate evaluator-controlled verification contract rather than an adapter assertion.

## Nonclaims

`evaluator_elapsed_ms` does **not** prove provider latency, target-system execution time, network-only latency, provider-side cancellation, target quiescence, SLA compliance, authenticated telemetry, attestation, or where the observed time was spent. It measures only the local evaluator's monotonic wall-clock interval around a returned `TrialRunner` operation.

Token and cost telemetry does **not** prove provider billing accuracy, tokenizer correctness, request attribution outside the normalized adapter boundary, authenticated provider identity, or that a named pricing table was actually applied by an external service. Hashes and roots establish integrity relations only; they do not authenticate the reporter.
