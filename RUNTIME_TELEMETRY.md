# Runtime timing, token, and cost telemetry

The evaluator keeps runtime telemetry concepts deliberately separate from grading and release authority.

`TrialEvidence.elapsed_ms` is evidence-envelope telemetry supplied by an adapter or preserved by exact evidence replay. It remains part of the historical `TrialEvidence/v2` value and its evidence root. A large, small, or otherwise unusual adapter-reported value is not independently promoted into evaluator timing authority.

`EvaluatedTrial.evaluator_elapsed_ms` is a local wall-clock observation measured by `TrialRunner` with the evaluator's monotonic clock around the complete returned trial lifecycle. It includes evaluator-side work as well as awaited adapter and semantic-judge work. `EvaluationSession` retains the value because its trials are the `EvaluatedTrial` objects returned by `TrialRunner`.

Manually or historically constructed `EvaluatedTrial` objects may leave `evaluator_elapsed_ms` unset. When explicitly supplied, the value must be finite and non-negative. This keeps existing hand-built/replayed runtime-result construction compatible without inventing a measurement that the evaluator did not actually observe.

Replay preserves historical timing: an `EvidenceReplayAdapter` returns the recorded `TrialEvidence.elapsed_ms`, while the enclosing live `TrialRunner` separately measures how long the replay/evaluation operation takes locally. The two values are not expected to match.

Evaluator deadline results are a special fail-closed case. When a configured evaluator wall-clock deadline expires, the deadline `TrialEvidence` uses evaluator-observed elapsed time because no completed adapter timing should be fabricated as the timeout observation. The returned `EvaluatedTrial` also carries the independently finalized `evaluator_elapsed_ms` for the complete returned runtime operation. Deadline expiry remains `BLOCKED`, never subject `FAIL`.

## Token and cost provenance

`TrialEvidence/v2` already contains `input_tokens`, `output_tokens`, and `estimated_cost_usd`, and its historical evidence root binds those exact scalar values. V2 does **not** say who counted the tokens, which tokenizer or provider surface produced them, or which price catalog produced an estimated cost. The project therefore does not reinterpret the v2 root as proof of those facts.

`RuntimeMetricProvenance` (`agent-evals/runtime-metric-provenance/v1`) is an evaluator-owned wrapper around the final v2 evidence. It binds the final trial ID, final evidence root, exact token counts, exact estimated cost, runtime adapter name, a source classification, optional bounded source/pricing assertion, and an explicit pricing-provenance status under a separate domain-separated provenance root. `EvaluatedTrial.metric_provenance` retains that object for live `TrialRunner` results, and `EvaluationSession` retains it transitively because it stores the returned trials. Existing manually constructed `EvaluatedTrial` objects may leave it unset rather than fabricating historical provenance.

The only authority class in v1 is `unverified_telemetry`. Adapter-provided source or pricing metadata cannot select or upgrade that authority. A generic adapter with no optional provenance assertion receives explicit `unknown` source and pricing provenance. An adapter may expose a bounded `runtime_metric_provenance_assertion` containing a source label/version and, only as a pair, a pricing source/version. The evaluator snapshots and validates that assertion before subject execution; malformed or exception-throwing assertions fail closed as evaluator `BLOCKED` uncertainty before grading.

For the exact built-in `OpenAIAgentsAdapter`, the evaluator recognizes the implementation path that reads nonzero token counts from `result.context_wrapper.usage` and labels that path `openai_agents_sdk_usage`. This remains unverified telemetry; the evaluator does not independently tokenize the request or response. The adapter currently does not calculate a price, so the framework invents no pricing source/version from a model name and leaves pricing provenance `unknown`. If no token telemetry is retained, the source classification is conservatively downgraded to `unknown` rather than claiming that an SDK usage observation occurred.

Exact `EvidenceReplayAdapter` runs preserve the historical v2 metric scalars but receive source classification `historical_evidence_replay` with original source/pricing provenance unavailable. Replay therefore cannot upgrade historical values into provider-verified usage or billing facts.

The v1 provenance root is an integrity binding only. It is not a signature, authenticated provider identity, billing attestation, tokenizer verification, price-sheet verification, invoice reconciliation, non-repudiation proof, or evidence that an adapter-reported cost is economically correct. Source/pricing assertions remain bounded assertions even though mutation of the recorded assertion invalidates the provenance root.

Metric provenance is not consulted by deterministic oracles, semantic authority, reliability statistics, `pass@k`/`pass^k`, or release gates in this slice. Missing optional source/pricing provenance therefore does not convert a subject outcome into `FAIL`, and `BLOCKED`/`INCONCLUSIVE` remain distinct from subject failure.

## Nonclaims

`evaluator_elapsed_ms` does **not** prove provider latency, target-system execution time, network-only latency, provider-side cancellation, target quiescence, SLA compliance, authenticated telemetry, attestation, or where the observed time was spent. It measures only the local evaluator's monotonic wall-clock interval around a returned `TrialRunner` operation.

Token/cost provenance likewise does **not** prove provider billing accuracy, exact tokenization, authenticated account identity, provider-side metering, price applicability, discounts, caching treatment, or that any quoted price was actually charged. Persisted performance distributions and cost/latency release thresholds remain separate work.
