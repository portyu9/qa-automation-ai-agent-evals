# Evaluator-owned runtime deadlines

`TrialRunner` can be configured with an optional positive finite `deadline_seconds` value. The
setting is evaluator-owned: the evaluator measures wall-clock progress with its monotonic clock and
refuses to grade a trial that exceeds the configured bound.

Deadline expiration is **not** a subject failure. It produces critical evaluator-owned
`EVALUATION_ERROR` evidence with code `trial_deadline_exceeded` and the terminal verdict is
`BLOCKED`. `BLOCKED` remains distinct from `FAIL` and `INCONCLUSIVE`.

The bound covers adapter execution, evaluator-side normalization/precondition/grading work, and a
live semantic judge invocation. Awaited adapter/judge work is cancelled when the evaluator's timer
expires. The evaluator also checks elapsed monotonic time after awaited and synchronous stages so a
late result cannot become PASS or FAIL merely because the child coroutine returned after the bound.

If the adapter completed and normalized subject evidence exists before a later timeout (for example,
during semantic judging), the timeout result retains that normalized subject evidence and appends the
evaluator deadline error. If adapter execution itself does not complete before the bound, the
evaluator does not fabricate subject output/state merely because the child task may later finish.
The timeout evidence's `elapsed_ms` is evaluator-observed wall-clock time; adapter-reported
`elapsed_ms` is not used to decide whether the evaluator deadline expired.

## Cancellation boundary and nonclaims

Cancellation is cooperative. In-process Python cannot forcibly preempt blocking synchronous code,
and cancelling the evaluator's child task does not prove that a provider, subprocess, remote agent,
or target system stopped work. A timed-out child coroutine can suppress cancellation or external
side effects may already have happened. The evaluator therefore discards late child-task results and
never lets them regain grading authority, but it does **not** claim process isolation, provider-side
cancellation, rollback, or target-side quiescence.

The deadline error proves only the evaluator's own configured bound, monotonic timing decision, and
evidence handling. It is not a provider attestation, signature, authentication mechanism, latency
SLA proof, or proof that external work ceased. Historical/replayed adapter latency is not
retroactively interpreted as a timeout when no evaluator deadline was configured.
