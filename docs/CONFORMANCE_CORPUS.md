# Conformance corpus

The checked-in corpus at `tests/fixtures/conformance/v1/corpus.json` is a
language-neutral set of integrity vectors for the repository's current digest and
root formats. It exists to make cross-implementation verification possible
without treating the Python implementation as the definition of its own hashes.

## What is covered

The corpus freezes both ASCII-escaped and direct-UTF-8 canonical JSON vectors,
plain canonical SHA-256 identities, every current domain-separated receipt/report
root family (including semantic calibration commitments/receipts), the chained
`TrialEvidence/v2` evidence root, the side-effect
logical-operation identity, and the historical `SubjectFingerprint` vector
salvaged from superseded PR #265.

It also carries deterministic corrupted-evidence recipes for a one-bit content
mutation, an omitted required field, event reordering, duplicate event sequence,
a cross-scenario receipt, and schema confusion. The companion
`tests/unit/test_conformance_corpus.py` first recomputes the vectors through a
small independent `json` + `hashlib` reference path and then checks the
production helpers against the same values.

The statistical differential reference remains
`tests/unit/test_statistics_complexity_limits.py::_reference_exact_mcnemar`,
which compares the optimized implementation to exact integer/binomial mass.
Protocol differential assurance remains in the deep-fuzz MCP/OAuth tests against
the pinned official MCP Python SDK reference used by the accepted #287/#288
work. Those references are independent test oracles for the named behavior; they
are not claims of universal protocol conformance.

## Canonical algorithms

For the common JSON vectors, object keys are sorted lexicographically, separators
are exactly `,` and `:`, non-finite numbers are forbidden, and UTF-8 is the byte
encoding. Most repository formats use JSON's ASCII escaping. Semantic
rubric/judge material and the semantic-judgment receipt deliberately preserve
their existing `ensure_ascii=false` UTF-8 behavior.

A domain-separated root is:

```text
SHA256(UTF8(domain) || 0x00 || canonical_json_bytes)
```

`TrialEvidence/v2` is intentionally different: it seeds a SHA-256 chain with
the domain-separated envelope identity, folds event digests in causal order, and
then hashes the domain, final chain state, and canonical terminal observations.
The exact vector is in the corpus.

## Verification boundary

A matching hash proves only that the verifier reproduced the same bytes and
algorithm. It does **not** prove who produced those bytes, authenticate an
evaluator/provider, establish a trusted timestamp, or attest to execution.
Similarly, a receipt whose internal root recomputes can still be invalid in its
surrounding relation; the cross-scenario corruption vector exists specifically
to exercise that distinction.

The corpus does not alter grading authority. In particular, `BLOCKED` remains
distinct from `FAIL`, and semantic judging remains subordinate to deterministic
preconditions/oracles.

## Versioning

Changes that intentionally alter a canonical format require a new corpus version
rather than silently rewriting `v1`. Additive vectors for an unchanged format
may extend this version, but existing expected values are compatibility
commitments and should not drift.
