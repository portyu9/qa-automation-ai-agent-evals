# Deprecation Policy

The project is pre-1.0, so ordinary Python API stability is still evolving. Pre-1.0 status does not
permit silent changes to evidence meaning, authority domains, replay semantics, or authenticated
release claims.

## Evidence schemas and integrity domains

Durable evidence, receipt, report, policy, and content-addressed identities are interpreted by their
explicit schema/domain version.

A change that would alter the meaning of already-valid persisted material must do one of the
following:

1. preserve the old semantics exactly; or
2. introduce a new schema/domain identity and an explicit transition path.

It must never keep the same identity while silently changing what old bytes mean.

Historical readers may be retained for verification-only use. For example,
agent_evals.evidence.legacy_v2 can rederive historical TrialEvidence/v2 roots that used older
timestamp representations, but it does not migrate them into current evidence, authorize replay or
grading, infer missing timezone intent, or add authentication.

When a historic schema is no longer supported even for verification, the removal must be recorded in
a new ADR and changelog with the last supported framework line and the reason. Removal does not make
previously valid hashes authenticated or invalidate the historical meaning they had under their
original verifier.

## First-party adapters

After the first published GitHub Release, removal of a named first-party adapter or a declared
provider/protocol compatibility boundary normally requires notice in at least one prior published
framework release. The notice must identify the replacement or explain that no replacement exists,
and the compatibility matrix must reflect the transition.

Before the first published release, adapter changes are still recorded in the changelog when
user-visible and remain subject to ADR enforcement on governed paths.

A security or correctness defect that makes an adapter unsafe to keep operational may be disabled or
made fail-closed without waiting through a grace release. The same change must document the reason,
preserve BLOCKED versus FAIL semantics, and add an ADR when it crosses a governed boundary.

## Dependency and SDK support

A dependency version leaving the reviewed min/latest locks is not "deprecated" merely because a new
upstream version exists. Support changes only when package metadata and executable compatibility
evidence change. "Latest" means latest reviewed lock, not an open-ended promise.

## Notices and enforcement

A material deprecation should appear in:

- CHANGELOG.md;
- docs/COMPATIBILITY.md when the supported matrix changes;
- a new ADR when governed assurance semantics change; and
- executable tests/compatibility locks when behavior or dependency support changes.

The PR template and CI ADR policy make these obligations visible and, for governed semantic paths,
machine-enforced.

## Non-claims

- A deprecation notice is not a migration proof.
- A compatibility lock is not publisher authentication.
- Historical verification support is not current replay/gradeability.
- SemVer labels do not override evidence schema identities or trust boundaries.
- Emergency fail-closed removal does not convert missing evidence into subject failure.
