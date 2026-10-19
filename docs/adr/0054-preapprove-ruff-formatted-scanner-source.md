# ADR 0054: Correct exact scanner source preapproval before production migration

**Status:** Accepted
**Date:** 2026-10-19
**Supersedes:** None

## Context

Protected PR #400 and ADR 0052 introduced a one-time, accepted-main
approval of the **exact** source blob for the scanner policy migration.
PR #401, which attempts only that preapproved scanner source plus ADR
0053, revealed a Ruff 0.17 formatting refusal before qualified merge.
The previously approved SHA `12eab86b64d4c9ec637150c4e76868dcc052a025`
is therefore **not eligible** for merge. The accepted-main publisher
must not accept a revised scanner source unless a separately protected
change approves its exact new bytes.

The outstanding original PR #401 remains the sole active scanner
migration lane. Its unique code and ADR will be preserved and updated
in place after this certificate change merges; no duplicate scanner
implementation branch is authorized. Signed bot PR #397 is separate.

## Decision

From accepted main `75a55960ab65d1915d4a2b7dd90637525faa70d2`,
replace *only* the code-owned, one-time scanner certificate with the
Ruff-formatted source Git blob identity
`89d1eabbb866b16a43497df8aebc4610df35bec8`.
The source differs from the prior blob solely in formatting of the
mandatory immutable-SHA regular expression; all scanner, tag, SARIF,
coverage, authorization and refusal contracts are unchanged.

Extend the accepted-main publisher self-test to allow the exact
preapproved scanner blob and refuse an arbitrary different candidate
blob during canonical source verification. No permission, trigger,
branch protection, runtime trust or candidate self-declared policy
is widened. After this change qualifies and merges, modify PR #401
**on its original branch** to use exactly the newly approved bytes,
update its not-yet-accepted ADR 0053 and requalify all native checks.

## Consequences

The migration cannot bypass code quality by changing only the candidate
PR or falsely treating a hash as authentication. A new accepted-main
decision explicitly binds the reviewed bytes; the blob SHA is merely
the immutable equality reference. Future pin upgrades continue through
main-owned upstream tag, signed bot and exact-source evidence checks.

The old unformatted blob is no longer an approved exception after this
decision. Correcting an exact-byte preapproval requires another staged
protected merge; this deliberate cost avoids unbounded candidate trust.

## Assurance impact

The migration remains fail-closed for any altered scanner source,
changed producer workflow not proven to be a canonical signed bot
pin-only update, missing genuine native CodeQL publication, or failed
protected status. The negative self-test independently exercises
unknown script hashes and the positive fixture verifies only the exact
code-owned prior approval.

## Non-claims

- Code formatting is not security proof, and a SHA is not identity or
  upstream source authentication.
- The next stage still requires complete native CI/Security/CodeQL
  acceptance and a genuine signed-bot automated merge demonstration.
- Do not suppress scanner findings, manufacture an approval, or bypass
  the thirteen native protected contexts.
- All unobservable administrator settings remain BLOCKED, not PASS.

## Evidence

PR #401 failed two Quality lanes solely on the preapproved scanner
formatting; exact Ruff 0.17 job 118141398204 produced the one-file
source correction. The newly formatted blob
`89d1eabbb866b16a43497df8aebc4610df35bec8` is fixed by the
separate main-owned certificate before amendment of PR #401.
