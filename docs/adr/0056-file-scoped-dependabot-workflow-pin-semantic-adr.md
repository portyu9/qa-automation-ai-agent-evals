# ADR 0056: Evaluate signed Dependabot workflow pins per file, never globally

**Status:** Accepted
**Date:** 2026-10-19
**Supersedes:** None

## Context

The existing accepted-main semantic ADR exemption considers a
Dependabot-authored action-only workflow update safe only after verifying
an exact base/head Git diff. PR #397 is a genuine signed Dependabot
routine-actions group updating six official pinned actions across
thirteen workflows. Some workflows include optional semantic version
annotations (e.g. ci.yml), while other existing workflows intentionally
store SHA-only action references (deep-fuzz.yml and deep-mutation.yml).
Our previous implementation collected all same-named uses from **every**
file into a single old/new version set. This incorrectly reported both
`None` and a version tuple for the same action and required an ADR from
a canonical action-only bot PR.

The independently accepted `dependency_governance.validate_action_semantics`
already evaluates its diff **per changed file**, retaining all other
actor/commit/merge-tree/one-for-one protections. The semantic-ADR
exemption must not contradict that contract.

## Decision

Split the exact Git diff into workflow-file chunks at canonical
`diff --git` boundaries. Evaluate every chunk independently using
the unchanged strict action-line parser, file-scoped multiset identity,
single old/new immutable 40-hex SHAs, version-annotation consistency,
monotonic semver where annotated, and prohibition on non-action changes.
Reject malformed or empty chunks, unrelated edits, unresolved status,
unsigned/non-bot authors and mixed protected non-workflow file changes.
No new path becomes exempt: the original acceptance check continues to
require every changed path inside the versioned workflow prefix,
modified-only status, exact main/head SHAs and Git's real zero-context
diff over precisely those workflow paths.

Extend negative tests to include:
- legitimate cross-file annotated + SHA-only changes for the same action;
- semantic run injection into any file;
- replacement action identity in a different file;
- unchanged SHA disguised as an update;
- malformed extra diff block.

## Consequences

Signed routine grouped action upgrades can satisfy the ADR exemption
without modifying control-plane ADRs on every patch release. A genuine
workflow semantic edit, mixed content change, spoofed bot or missing
provenance must still require a separately accepted ADR or be rejected
by governance. The independent main-owned CodeQL publisher continues
binding upstream release tag/commit signatures, canonical bot source,
head/base/merge tree, native CodeQL and strict candidate source identity.

## Assurance impact

This changes only the *scope of grouping* from all workflow files
together to one file at a time; it does not weaken any per-file
one-for-one action-pin or issuer requirement. All scanner gate,
publisher, protected CI and owner-token controls are unchanged.

## Non-claims

- SHA-only lines are not claims of an upstream semantic release version;
  that binding is independently verified from canonical signed bot
  release metadata and GitHub upstream tags by accepted-main publisher.
- Neither a SHA nor a passing Actions check authenticates software safety.
- No elevated token in untrusted PR code, forged approval, skipped native
  Code Scanning or admin control bypass is authorized.
- Unobserved administrative features remain BLOCKED, not PASS.

## Evidence

Live PR #397 signed head `3695bf549489a60bd590f3c70cb3ba3f480c98fc`
failed Repository policy job `118144129773` on semantic-ADR exemption,
even though its patch contains only canonical immutable action updates;
the same head also failed known pre-migration scanner SHA checks.
Accepted main `6d6b62d37e4b67be2ea6ac4a4bf1960302805d58` includes PR #400/#402, while original
scanner PR #401 and bounded Security API retry PR #403 remain separately
open; their unique code/ADR must be preserved. PR #389 was explicitly
reverted by #390. No untracked lane branches are created.
