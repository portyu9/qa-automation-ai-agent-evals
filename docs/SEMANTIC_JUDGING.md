# Calibrated Semantic Judging

## Purpose

Semantic judging evaluates meaning-level properties that deterministic state and policy oracles cannot always express cleanly: whether an answer is grounded in supplied facts, whether it addresses every requested requirement, or whether a textual response satisfies a scenario-owned quality contract.

This framework treats semantic judging as **subordinate evidence**, not as release authority.

The hard boundary is:

```text
verified execution evidence
        ↓
deterministic policy + outcome grading
        ├─ FAIL ─────────────────────────────→ trial FAIL
        │                                     semantic judge is not invoked
        └─ PASS
             ↓
       accepted calibrated semantic judge
             ├─ PASS ────────────────────────→ trial PASS
             ├─ FAIL ────────────────────────→ trial FAIL, non-critical
             └─ ABSTAIN ─────────────────────→ trial INCONCLUSIVE
```

A semantic judge cannot override authorization, approval, protocol-delivery, state, or other deterministic evaluation failures.

## Trust model

The semantic layer separates five identities that are easy to conflate:

1. **scenario identity** — the complete evaluation contract, including the semantic rubric when configured;
2. **rubric identity** — the exact meaning-level criteria and thresholds;
3. **judge-profile identity** — the exact behavior-bearing judge configuration;
4. **calibration identity** — the accepted empirical evidence for that exact profile and calibration policy;
5. **subject-evidence root** — the exact pre-semantic trial evidence being judged.

`SemanticJudgmentReceipt` binds all five. Reuse across drift in any of them fails validation.

Ordinary SHA-256 roots provide content integrity and stable identity. They are not signatures, authenticated publisher identity, trusted timestamps, remote attestation, or proof that an external model/provider behaved honestly.

## Scenario-owned rubric

A scenario opts into semantic grading with `EvaluationScenario.semantic_rubric`.

```python
from agent_evals.contracts.models import EvaluationScenario, ScenarioKind
from agent_evals.contracts.semantic import SemanticCriterionSpec, SemanticRubricSpec

rubric = SemanticRubricSpec(
    rubric_id="answer-quality",
    revision="1",
    criteria=(
        SemanticCriterionSpec(
            criterion_id="grounded",
            description="The answer stays grounded in the supplied facts.",
            minimum_score=3,
        ),
        SemanticCriterionSpec(
            criterion_id="complete",
            description="The answer addresses every requested requirement.",
            minimum_score=3,
        ),
    ),
)

scenario = EvaluationScenario(
    scenario_id="customer.answer-quality",
    revision="1",
    kind=ScenarioKind.CAPABILITY,
    objective="Answer the customer question accurately and completely.",
    semantic_rubric=rubric,
)
```

The rubric participates directly in `EvaluationScenario.identity`. Changing its revision, criterion identity, criterion description, order, or threshold changes the scenario hash.

That property is essential for replay: a semantic receipt produced for one rubric cannot be silently interpreted under a different meaning-level contract.

## Response contract

The judge returns only a bounded `SemanticJudgeResponse`:

```text
schema_version
criteria[]
    criterion_id
    decision: pass | fail | abstain
    score: 0..4 integer, or null for abstain
overall: pass | fail | abstain
```

No free-form reasoning or chain-of-thought field exists in the contract.

For every resolved criterion, the evaluator independently derives the expected decision from the integer score and the scenario-owned minimum threshold. `ABSTAIN` must carry no score. Criterion identity and order must exactly match the rubric. The evaluator then independently derives the overall decision:

```text
any criterion FAIL     → overall FAIL
else any ABSTAIN       → overall ABSTAIN
else                   → overall PASS
```

A model cannot manufacture a contradictory `overall` value or pair a PASS label with a below-threshold score.

## Bounded judge input

The default `SemanticJudgeInput` contains only:

- the scenario objective;
- the exact rubric;
- the candidate final output.

It intentionally excludes arbitrary normalized events, tool payloads, credentials, approval material, environment state, and the complete evidence stream.

This is both a data-minimization and authority-control property. The semantic judge receives enough information to grade the configured textual rubric but does not automatically inherit access to unrelated evidence domains.

The input itself is content-addressed. `SemanticJudgmentReceipt` stores its digest rather than duplicating the raw subject output.

## Judge profile

`SemanticJudgeProfile` content-addresses behavior-bearing judge configuration:

- provider;
- model name;
- model revision label;
- adapter name and version;
- evaluator prompt-template digest;
- expected response schema;
- behavior-configuration digest.

A prompt change is therefore calibration drift. A model revision change is calibration drift. Changing behavior configuration such as max turns, input encoding, or response bounds is calibration drift.

The live `SemanticJudge.profile` must exactly match the profile embedded in its accepted calibration receipt before runtime invocation is permitted.

## Calibration

Semantic authority must be earned by an accepted `SemanticCalibrationReceipt`; it is not inferred from model reputation or structured-output capability.

A `SemanticCalibrationCase` contains evaluator-owned labeled material:

- case ID and revision;
- objective;
- rubric;
- candidate output;
- expected PASS or FAIL label;
- optional coverage tags.

The raw candidate text is not duplicated into the calibration receipt. Each observation binds the content-addressed case identity and either:

- a rederived structured judge decision plus response digest; or
- an explicit judge/malformed-response failure code.

### Metrics

Calibration recomputes and binds:

- total cases;
- PASS-labeled cases;
- FAIL-labeled cases;
- correct observations;
- false PASS count;
- false PASS rate over FAIL-labeled cases;
- abstention count;
- judge/malformed-response failure count;
- covered adversarial tags;
- aggregate accuracy;
- final accepted/rejected status.

False PASS is tracked separately because a judge that incorrectly promotes a known-bad answer is a different risk from a conservative abstention.

### Default acceptance policy

The default `SemanticCalibrationPolicy` requires balanced support and is intentionally strict. In particular, accepted calibration requires explicit `judge-prompt-injection` coverage and allows no false PASS, abstention, or judge failure unless the policy is deliberately changed.

The policy itself is content-addressed and embedded in the receipt. Changing acceptance thresholds changes calibration identity.

### Prompt-injection coverage

A calibration case tagged `judge-prompt-injection` is not a magic security certification. It proves only that the exact calibrated judge configuration was evaluated against at least one explicitly labeled candidate containing evaluator-directed adversarial text.

The repository's deterministic OpenAI SDK tests additionally verify that candidate text such as an instruction to ignore the rubric remains inside the canonical JSON `candidate_output` field supplied to the judge model.

Those facts support a narrow claim: the evaluator boundary treats candidate output as data and the calibration policy requires adversarial coverage. They do **not** prove universal prompt-injection resistance.

## Runtime authority validation

Before any fresh semantic invocation, `TrialRunner` calls `validate_semantic_judge_authority()`.

Validation re-parses the live judge profile and calibration receipt, then requires:

- calibration `accepted == True`;
- exact profile identity equality between live judge and calibration;
- internally valid calibration metrics and receipt root.

Malformed, rejected, or drifted authority produces evaluator uncertainty rather than subject failure.

## Deterministic precedence

Semantic grading occurs only after the framework has already verified execution preconditions and run deterministic policy/outcome oracles.

This is a **short-circuit**, not merely a final tie-break rule.

If deterministic grading fails:

- the semantic judge is not invoked;
- no candidate output is disclosed to it by this runtime path;
- the deterministic failure remains authoritative;
- critical policy failures remain critical.

When deterministic grading passes:

| Semantic result | Trial result | Critical? |
|---|---|---|
| PASS | PASS | no |
| FAIL | FAIL | no |
| ABSTAIN | INCONCLUSIVE | no |
| judge unavailable / malformed / unverifiable | BLOCKED | evaluator uncertainty |

Semantic FAIL therefore affects reliability statistics but does not increment the deterministic critical-violation count.

## Evidence and receipt construction

A fresh semantic judgment closes this relation:

```text
TrialEvidence before semantic event
        ↓ evidence_root
SemanticJudgeInput
        ↓ exact rubric + candidate digest
validated calibrated judge
        ↓ strict response
rederived criterion decisions + overall decision
        ↓
SemanticJudgmentReceipt
        ↓ terminal non-critical event
TrialEvidence with SEMANTIC_JUDGMENT
```

The receipt binds:

- scenario identity;
- subject identity;
- pre-semantic subject-evidence root;
- complete embedded rubric and rubric identity;
- judge profile;
- calibration receipt identity;
- judge-input digest;
- structured judge-response digest;
- exact criterion results;
- rederived decision;
- outer domain-separated receipt root.

The raw candidate output is not duplicated inside the receipt when its digest is sufficient.

## Event invariants

`SEMANTIC_JUDGMENT` is intentionally a distinct evidence kind.

A valid semantic event must be:

- unique within the trial;
- terminal;
- emitted from the known evaluator semantic source;
- non-critical;
- bound to the same subject and scenario as the trial;
- bound to the exact scenario rubric;
- bound to the exact evidence root reconstructed from everything before the semantic event.

Duplicate semantic events, post-judgment subject events, critical semantic events, source spoofing, receipt tampering, or pre-semantic root mismatch fail closed.

## Replay

Replay never silently invokes a semantic model.

When persisted evidence already contains a semantic event, `TrialRunner`:

1. reruns deterministic delivery/precondition checks;
2. reruns deterministic policy/outcome oracles;
3. reconstructs the evidence envelope before the semantic event;
4. revalidates the semantic receipt and exact pre-semantic root;
5. rederives PASS/FAIL/INCONCLUSIVE precedence from the historical semantic decision.

If deterministic replay now fails while historical semantic evidence exists, the runtime rejects the impossible precedence relation instead of allowing the old semantic result to rescue or coexist with deterministic failure.

Replay therefore verifies historical consistency. It does not prove that the semantic provider is live, that the model would return the same result now, or that external state is unchanged.

## Assurance reports

`AssuranceReport` v2 keeps deterministic and semantic authority visibly separate.

Each `TrialAssuranceRecord` contains:

- exact final evidence root;
- deterministic oracle snapshots;
- optional full self-validating `SemanticJudgmentReceipt`;
- terminal trial verdict.

On load, the report rederives the trial verdict from those two authority classes with deterministic precedence. A semantic receipt cannot coexist with deterministic oracle failure. Critical violations are recomputed from deterministic oracle snapshots only.

Reliability and release-gate decisions are then recomputed from the validated trial verdicts and frozen release policy.

## OpenAI Agents SDK implementation

`OpenAIAgentsSemanticJudge` is optional and requires the repository's `openai` extra. The package core does not import the SDK merely to define semantic contracts.

The implementation uses the pinned public Agents SDK boundary:

```text
concrete agents.models.interface.Model
        ↓
Agent(name="agent-evals semantic judge", tools=[])
        ↓
Runner.run(..., max_turns=1)
        ↓
strict final JSON string
        ↓
duplicate-key / non-finite / size / JSON-object validation
        ↓
SemanticJudgeResponse
```

The fixed profile binds:

- canonical-JSON user-message encoding;
- one-turn limit;
- no tools;
- bounded 64,000-character final output;
- tracing disabled;
- sensitive trace data disabled;
- exact evaluator prompt digest;
- response schema v1.

The parser rejects duplicate JSON keys, non-finite numeric constants, invalid JSON, non-object JSON, oversized output, and schema-invalid responses. Those are evaluator/judge failures, not subject semantic FAIL.

CI uses `agents.testing.ScriptedModel`, so the integration test exercises the real pinned SDK runner/model interface without provider credentials or an external API call.

## What this feature does not claim

The current semantic layer does not claim:

- that model judgment is deterministic in the mathematical sense;
- universal semantic correctness;
- universal prompt-injection resistance;
- human-equivalent review;
- authenticated human approval;
- a cryptographic signature over judge output;
- provider-side model-version attestation;
- calibration transfer across model/prompt/configuration drift;
- current-model liveness during replay;
- authority to override policy, state, approval, protocol, or release-safety evidence;
- that a semantic PASS proves any external side effect occurred.

These limits are architectural, not caveats added after scoring. The code encodes them through identity, calibration, runtime short-circuiting, event criticality, replay verification, and report derivation.

## Recommended usage

Use semantic judging when a scenario has a bounded, reviewable meaning-level property that cannot be proven from deterministic state alone. Keep deterministic state/policy checks wherever they are possible.

A strong scenario often combines both:

```text
required state: refund.status == "created"
required policy: tool/resource/approval authority respected
semantic rubric: final answer accurately describes the completed refund and omits unsupported claims
```

The deterministic layers establish what happened and whether it was authorized. The semantic layer can then grade how accurately the agent communicated that already-verified reality.

[← Documentation hub](README.md) · [Evaluation Model](EVALUATION_MODEL.md) · [Evidence & Replay](EVIDENCE_AND_REPLAY.md) · [Assurance Reports](ASSURANCE_REPORTS.md) · [OpenAI Adapter](OPENAI_ADAPTER.md) · [Limitations](LIMITATIONS.md)
