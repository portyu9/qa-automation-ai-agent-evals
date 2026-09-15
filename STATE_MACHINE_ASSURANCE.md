# State-machine assurance

The deterministic assurance core uses Hypothesis state machines for trust boundaries whose safety depends on **sequences** of otherwise valid or invalid operations. These models complement example-based regression tests and pure property tests: they generate transitions, shrink failing traces, and assert invariants after intermediate states rather than checking only one final example.

## Covered transition domains

| Domain | Model | Primary invariant |
| --- | --- | --- |
| approval / resume chronology | `tests/unit/test_approval_chronology_state_machine.py` | an approval decision is bound to the exact request/invocation and authority epoch; duplicate or out-of-order continuation does not create approval authority |
| handoff attenuation | `tests/unit/test_handoff_authority_state_machine.py` | tools, resources, budgets, and active-agent authority can stay equal or narrow along a valid path but never re-expand |
| MCP schema / identity / cache transitions | `tests/unit/test_mcp_transition_state_machine.py` | stale, reordered, duplicated, or mismatched protocol observations cannot be promoted into a fresh valid protocol relation |
| immutable evidence publication | `tests/unit/test_evidence_store_state_machine.py` | partial/corrupt/conflicting/locked publication states never become a valid committed record and committed evidence is not clobbered |
| replay identity transitions | `tests/unit/test_replay_state_machine.py` | replay succeeds only for the exact recorded trial/subject/scenario identities; drift fails closed and restoring exact identity restores deterministic replay without cached authority |

Together these five models cover the transition classes tracked by hardening roadmap item 32. Each domain keeps its production trust semantics separate; there is no single synthetic state machine that can accidentally become a new cross-domain authority.

## Replay model contract

The replay model varies three identity axes independently—trial, subject, and scenario—while switching between direct `EvidenceReplayAdapter` construction and `LocalEvidenceStore`-verified construction. It also switches among a clean recorded observation and recorded evaluator/runtime blocking evidence. An invariant runs after every generated transition:

- any identity drift raises `ReplayIdentityError` at the adapter boundary;
- exact identity returns the recorded events, terminal state/output, and metrics unchanged;
- drift followed by restoration succeeds again, demonstrating that the adapter does not cache a prior success or failure as authorization;
- store-backed replay is semantically identical to replay of the same verified in-memory evidence;
- replay snapshots its source evidence, so later mutation of an adapter-owned nested container cannot rewrite the retained observation;
- when exercised through `TrialRunner`, identity/precondition uncertainty becomes `BLOCKED` evaluation evidence rather than subject `FAIL`;
- recorded evaluator/runtime blocking evidence remains `BLOCKED` even when its terminal state would otherwise satisfy deterministic outcome grading.

The model uses bounded local examples and disables Hypothesis wall-clock deadlines. Runtime speed is not assurance authority; deterministic semantic invariants are.

## Nonclaims

State-machine tests are not formal verification and do not prove all possible traces. They do not replace mutation testing, fuzzing, corrupted-evidence corpora, crash/power-loss injection, concurrent filesystem torture, or independent conformance vectors.

The replay model regrades **recorded observations**. It does not re-execute an agent, provider, tool, MCP server, side effect, human approval, retrieval system, or environment, and therefore establishes no fresh liveness, external authorization, target-side effect, or provider-availability claim. Store-backed replay relies on the local evidence store's existing integrity contract; the replay model does not claim hostile-kernel or TOCTOU filesystem resistance beyond that contract.

A state-machine counterexample is treated as a defect lead, not automatically as subject failure. Framework/evaluator uncertainty remains distinct from behavioral `FAIL`, and minimized counterexamples should be promoted into ordinary regression tests whenever they expose a durable defect.
