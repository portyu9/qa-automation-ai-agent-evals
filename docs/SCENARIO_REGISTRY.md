# Scenario Registry

The scenario registry is a versioned **metadata and commitment index** over immutable
`EvaluationScenario` contracts. It does not change `EvaluationScenario.identity`, and it does not
embed raw scenario bodies. This separation lets benchmark-governance metadata evolve without
silently changing the behavioral contract under evaluation.

## Registry entry

`ScenarioRegistryEntry` binds metadata to:

- exact `scenario_id`, scenario revision, kind, and `scenario_identity`;
- an exact structural `behavioral_fingerprint` that ignores only scenario ID, revision, and tags;
- canonical scenario tags;
- owner, taxonomy, population scope, rationale, and difficulty;
- exact prerequisite scenario identities;
- benchmark exposure/leakage metadata;
- authored or promoted provenance;
- active/deprecated lifecycle metadata.

Every entry has a domain-separated `entry_root`. `ScenarioRegistry` canonically orders entries,
requires unique scenario identities and ID/revision keys, requires prerequisites, supersession
targets, and derived provenance parents to exist in the same registry, rejects prerequisite cycles,
and commits the ordered entry roots into a domain-separated `registry_root`.

A consumer with the raw scenarios can call `verify_scenarios(...)` to require an exact one-to-one
match between registry commitments and detached/revalidated `EvaluationScenario` objects.

## Benchmark exposure and leakage metadata

`BenchmarkLeakageMetadata` distinguishes:

- `stable_public`: intentionally stable and public;
- `rotating_private`: private material with an explicit rotation identity;
- `private_holdout`: private holdout material that is not necessarily rotation-based.

Contamination and memorization risk are explicit `unknown / low / moderate / high` metadata.
`lint_scenario_registry(...)` surfaces unknown leakage risk and high memorization risk on stable
public scenarios.

These are evaluator-owned labels, not evidence that material remained secret or uncontaminated.
In particular, **anything committed to this public repository is public regardless of a registry
label**. Private/rotating entries are intended to carry commitments and metadata while their raw
scenario bodies live in an appropriately controlled external store.

## Exact structural deduplication

The behavioral fingerprint hashes the scenario contract after removing only `scenario_id`,
`revision`, and `tags`. This catches exact structural aliases that differ only in naming,
revision, or labels.

Two different scenario identities with the same structural fingerprint produce the
`exact_behavior_duplicate` ERROR finding unless both entries carry an explicit duplicate-waiver
reason. `require_scenario_registry_quality(...)` fails on ERROR findings.

This is deliberately narrow. A different fingerprint does **not** prove semantic uniqueness,
independence, different model behavior, or absence of benchmark overlap. Semantic/near-duplicate
detection needs a separately validated method and must not be inferred from hash inequality.

## Counterexample and minimized-failure promotion

`ScenarioProvenance` distinguishes authored cases from `counterexample`,
`minimized_failure`, and `metamorphic_mutant` origins.

Counterexample/minimized-failure promotion requires:

1. the exact parent scenario identity;
2. the source trial ID; and
3. the source trial evidence root.

The parent must also exist in the registry. This creates durable lineage from a promoted regression
case back to one exact observed failure without claiming that an unsigned evidence root
authenticates who produced it.

Metamorphic-mutant provenance requires a parent scenario identity; optional source trial/evidence
material must appear as a pair.

## Lifecycle and prerequisites

Deprecated scenarios require a deprecation reason and may identify an exact superseding scenario.
Active scenarios cannot carry deprecation metadata. Prerequisite identities must be unique,
canonically sorted, present in the same registry, and acyclic.

An active scenario depending on a deprecated prerequisite is a deterministic lint WARNING rather
than an automatic rewrite. Deprecation policy therefore remains reviewable instead of silently
removing historical benchmark coverage.

## JSON Schema export

`scenario_registry_json_schema()` exports the Pydantic JSON Schema for tooling, validation, and
external registry pipelines. The exported schema describes the contract; it is not a registry
instance, attestation, signature, or certification.

## Relationship to the conformance corpus

The checked-in conformance corpus under `tests/fixtures/conformance/v1/corpus.json` is a
language-neutral set of canonical hash/root vectors. It is **not** the scenario benchmark registry
and remains a separate integrity-verification domain. The scenario registry must not repurpose
conformance vectors as behavioral benchmark cases.

## Non-claims

A registry root is an integrity identity, not publisher authentication. Owner labels are not
identity proof. Leakage labels do not prove secrecy. Exact structural deduplication does not prove
semantic independence. Promotion provenance does not turn hashes into signatures. Registry
membership does not turn semantic judging into deterministic authority, does not flatten
`BLOCKED` into `FAIL`, and does not broaden what a scenario result establishes.
