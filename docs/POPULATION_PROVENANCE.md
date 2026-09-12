# Population provenance

Repeated-trial statistics need a population or sampling-frame assumption that is separate from the mechanics of repeated attempts. A campaign can have a fixed horizon, explicit randomness provenance, and reset/isolation receipts while still saying nothing about **what larger population the observed trials are intended to represent**.

This document defines the additive population-aware path introduced after the historical `agent-evals/session-sampling/v1` and Assurance Report v6 contracts.

## Version boundary

The existing `agent-evals/session-sampling/v1` contract remains historical. It records attempt inclusion, randomness/seed provenance, and stopping semantics. It does not contain population provenance and must not be reinterpreted as if it did.

`agent-evals/session-sampling/v2` is an explicit envelope containing:

- the exact validated v1 attempt provenance;
- campaign identity;
- subject identity;
- scenario identity;
- a versioned population-provenance object; and
- a domain-separated v2 metadata root.

The population-aware report is `agent-evals/assurance-report/v7`. V7 deliberately embeds the exact self-validating Assurance Report v6 predecessor plus the v2 statistical envelope. V6 remains historical and keeps its original meaning. V7 rechecks that campaign, subject, scenario, and v1 attempt provenance are identical across the two layers before accepting its own domain-separated root.

Release authority does not move into the population layer. The embedded v6 report continues to recompute reliability and the release decision from validated trial facts and the frozen release policy. Population provenance cannot rescue a failed safety invariant or convert `BLOCKED` / `INCONCLUSIVE` into behavioral `FAIL`.

## Population trust states

`agent-evals/population-provenance/v1` has three deliberately different states.

### `identified`

An identified population carries an `agent-evals/population-frame/v1` object with:

- canonical lowercase ASCII namespace;
- canonical population/frame ID;
- explicit revision;
- `definition_identity`, a caller-supplied SHA-256 identity for external definition material; and
- `frame_identity`, a domain-separated digest over the complete canonical frame descriptor.

The frame identity detects descriptor changes such as revision or definition-digest drift. It does **not** prove that `definition_identity` names real bytes, authenticate who supplied those bytes, establish ownership, or prove that the campaign sampled the frame representatively.

### `externally_declared`

An externally declared population carries a bounded textual basis and no identified frame. This preserves the fact that an operator or integration stated a population assumption without upgrading that statement into evaluator-owned verification.

### `unknown`

Unknown population provenance carries neither an identified frame nor a declaration basis. Unknown is a first-class state, not an omitted field that downstream consumers are expected to guess about.

## Execution path

`PopulationBoundEvaluationSession` requires a valid `PopulationProvenance` object before it delegates any subject attempt to the ordinary `EvaluationSession`. After the base session completes, the wrapper binds its exact v1 attempt provenance to population provenance in `SessionSamplingMetadataV2`.

This ordering is an evaluator API property, not a cryptographic timestamp or remote attestation. A serialized v2/v7 artifact can prove only that the recorded material is internally bound by its integrity roots. Hashes alone cannot prove to an external verifier that the population assumption was chosen before outcomes were observed. Stronger chronology or authenticated operator commitments require a separate signed/attested evidence domain.

## Qualified repeated-attempt metrics

Population-aware sessions expose the existing independence-qualified repeated-attempt metrics together with population status, identity, and basis. The statistical population fields are context for interpretation; they do not strengthen the mathematical assumptions already required by `pass@k` / `pass^k`.

In particular:

- an identified population is not evidence that attempts were sampled randomly from it;
- an external declaration is not evaluator verification;
- distinct seed identities do not prove independent random streams;
- reset/isolation receipts do not prove stationarity or absence of hidden shared state;
- a fixed horizon does not prove exchangeability; and
- no population state proves unbiased sampling or formal IID behavior.

The raw reliability counts and Wilson summaries retain their existing semantics. Population uncertainty is statistical/provenance uncertainty, not subject behavioral failure.

## Mutation and replay checks

The population-aware contracts fail closed on malformed or contradictory trust states, forged frame identities, schema confusion, campaign/subject/scenario mismatch, v1 attempt-provenance drift, cross-campaign replay, and v7 content changes that do not recompute the report root.

These are integrity checks. An attacker who can rewrite an unsigned artifact and recompute every hash is outside what hash-only integrity can authenticate. Optional signatures/attestations remain separate release-provenance work.

## Relationship to a future scenario registry

Roadmap item 81 calls for a versioned scenario registry with population metadata. A future registry may provide canonical definition material whose digest is referenced by `PopulationFrame.definition_identity`. Registry membership alone must not silently upgrade a population to representative sampling or authenticated truth. Any stronger registry authority must be explicit, versioned, and verified through its own trust domain.
