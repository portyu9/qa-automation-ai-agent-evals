# ADR 0001: CI-gated assurance-semantic decision records

**Status:** Accepted
**Date:** 2026-10-07
**Supersedes:** None

## Context

Protected main intentionally uses one human CODEOWNER with zero mandatory approving reviews. Merge
authority is the protected CI contract plus resolved review threads, not GitHub Actions or Copilot
approval. That autonomous model is useful only if changes to assurance semantics remain durably
explainable and machine-gated.

The repository already asks contributors to describe schema, security, statistics, and trust-boundary
impact, but a pull-request checkbox is not durable decision history and can be omitted without a
path-sensitive machine check.

## Decision

Introduce versioned agent-evals/semantic-adr-policy/v1 and validate it in the CI Repository policy
job.

For pull requests, CI computes the exact base-to-head name/status diff. Any change under an enumerated
assurance-semantic prefix or exact trust/release-governance file requires at least one newly added
numbered ADR. Accepted ADRs are append-only even when an ADR is the only changed file; edits, deletions, renames,
or copies fail closed and cannot be authorized by adding another ADR in the same pull request. New
ADRs use canonical filenames and required decision sections, and free-form exemptions do not exist.

The policy and validator are themselves governed paths. The governed set also includes the public
architecture/security/limitations/release-provenance/compatibility/deprecation contracts, so prose
cannot broaden those assurance claims without a new decision record. Changing what counts as
assurance-semantic therefore requires another append-only ADR.

One narrow automation exception preserves the repository's already accepted Dependabot action-pin
lane without creating an author-controlled bypass. The validator requires the immutable GitHub actor
to be exactly dependabot[bot], requires every governed change to be an in-place file under
.github/workflows/, and inspects the exact base-to-head patch. Only one-for-one replacements of the
same action identity from one immutable 40-hex SHA to a different SHA with an advancing semantic
version comment may proceed without a new ADR. Any other changed line, actor, path shape, rename,
creation, deletion, or mixed governed change falls back to the normal ADR requirement. Python
dependency and reviewed compatibility-lock churn remain governed by the repository's separate
dependency/compatibility controls rather than by ADR path matching.

## Consequences

Small changes inside governed source areas may need an ADR even when an author considers them
routine. That conservatism is intentional: false-positive documentation cost is preferred to silently
changing authority, evidence, release, or replay semantics under an autonomous merge model.

Documentation-only changes outside governed paths do not need an ADR. Superseding a decision adds a
new record rather than rewriting the accepted record.

## Assurance impact

The gate strengthens repository decision provenance without changing evaluator authority, evidence
roots, BLOCKED versus FAIL, release artifact provenance, or live GitHub administration. CI self-tests
no-ADR failure, successful newly added ADR handling, historical-ADR edits, rename handling, and
malformed diff status behavior, ADR-only rewrites, attempts to pair an accepted-ADR mutation with
a new ADR, and the bounded action-pin parser versus a non-action workflow mutation.

This ADR also authorizes the #329 governance additions that introduce the policy itself.

## Non-claims

- ADR presence is not proof that a decision is safe, correct, independently reviewed, or externally
  enforced.
- Git/GitHub account attribution is not a cryptographic human signature.
- The ADR gate does not replace tests, CodeQL, release qualification, schema compatibility checks, or
  external administrator verification.
- Hashes remain integrity identities, not authentication.
