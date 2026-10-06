# Adversarial Semantic Calibration

This layer strengthens semantic calibration without giving model judgment deterministic authority. It is additive to the existing v2 calibration receipt, stratified validation/holdout qualification, and robustness diagnostics.

## Prompt-injection subclasses

`PromptInjectionClass` standardizes six evaluator-owned classes: direct override, markup escape, fake rubric, fake system message, long-context attack, and multilingual attack. `prompt_injection_tags()` emits both the general `judge-prompt-injection` tag and the subclass tag. `high_assurance_prompt_injection_requirements()` creates canonical per-subclass validation and holdout FAIL-support requirements for `StratifiedCalibrationPolicy`.

A tag is a calibration taxonomy label, not proof that an attack was delivered or that the judge is universally robust.

## Metadata blinding

`SemanticBlindingEnvelope` exposes only the existing bounded `SemanticJudgeInput` while committing, by digest, to source metadata intentionally withheld from the judge. The standard blind-field vocabulary covers candidate identity, provider, model, and baseline label.

The envelope proves only what the evaluator chose to project and commit. A SHA-256 commitment is integrity material, not publisher authentication or proof that an external provider did not possess the metadata independently.

## Contamination and memorization probes

`CalibrationLeakageReceipt` records exact-case exposure, canary recall, paraphrase memorization, and training-membership probes. Coverage and detection counts are recomputed from observations and integrity-bound to a versioned receipt. The default policy requires all probe kinds and zero detections.

A clean receipt is bounded evidence for the configured probes only. It is not proof that training data is uncontaminated.

## Explicit abstention calibration

`SemanticAbstentionCase` creates a separate evaluator-owned set where the safe expected behavior is ABSTAIN. `SemanticAbstentionReceipt` distinguishes explicit abstention from judge failure and from an incorrect resolved PASS/FAIL decision.

This does not reinterpret historical calibration cases, which still require evaluator-owned PASS or FAIL labels. It adds a separate calibration domain so transport failure cannot be counted as safe uncertainty.

## Authority boundary

These contracts are diagnostic and qualification inputs. They cannot:
- rescue deterministic FAIL;
- turn BLOCKED into FAIL or PASS;
- replace scenario-owned rubric authority;
- authenticate a provider, benchmark source, or publisher;
- establish universal semantic correctness.
