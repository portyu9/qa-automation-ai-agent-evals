# ADR 0045: Revert experimental per-commit CodeQL concurrency isolation

**Status:** Accepted

## Context

ADR 0044 recorded an experiment intended to preserve genuine read-only
CodeQL scans for intermediate PR source commits. PR #389 then changed
the CodeQL workflow-level concurrency key to include exact PR source SHA
and disabled in-progress cancellation. It also pinned the changed shape in
the fail-closed workflow-graph validator. Those changes merged through
normal protection to `main@111dcd64a66c89afef0a2d414821fd580dabdc87`.

The last independently observed genuine unfiltered OpenSSF Scorecard
before #389, [run 38906594311](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38906594311)
on `main@4a79372cedb8e7726887719435991e756a1b671e`, reported
`SASTID` 18 of 30 recognized recent commits. Post-merge real
[run 38913195790](https://github.com/portyu9/qa-automation-ai-agent-evals/actions/runs/38913195790)
on `main@111dcd64a66c89afef0a2d414821fd580dabdc87` reported
`SASTID` 12 of 30. Both retained original unsuppressed SARIF evidence;
the later artifact is ID `12051675537` with GitHub digest
`sha256:fef0650c540eabcd70a02b5c628057c91937fde92226a4b780604a810fda7baa`.

The Scorecard fraction measures a rolling last-30-commit sample and
scanner-recognized check provenance. A decline after a merge is a real
measured outcome but does **not** by itself establish that the changed
concurrency key caused all six missing qualifying entries. Neither an
earlier green Actions CodeQL check nor a publisher artifact can
retrospectively authenticate a commit without its own evidence.

The repository owner explicitly requested rollback of the accepted #389
experiment when coverage fell from 18 to 12. Respect this risk-control
decision and preserve the previously accepted stable policy exactly.

## Decision

Revert **only** PR #389's executable and policy changes by restoring
the **exact immutable blobs** from the accepted pre-#389 main:

- `.github/workflows/codeql.yml`: blob
  `8b9a2e7447876d5c22daa84f26cf980dcf546ad2`. This restores the
  existing repository/PR concurrency group and
  `cancel-in-progress: true`, with no new events or permissions.
- `.github/scripts/validate_workflow_graph.py`: blob
  `54df2896729767451d7b90c36242e19232e25602`. This restores its
  previously accepted fail-closed workflow rules and adversarial fixtures
  without relaxing the semantic policy.
- Retain ADR 0044 *unchanged* as an immutable record of the attempted
  concurrency design. This new ADR 0045 **supersedes its operative
  decision**. Do not rewrite or delete historical accepted ADRs.

No CodeQL original SARIF, zero-alert validator, trusted-main publisher,
off-hour schedule/protected-main push, source SHA identity, active Code
Scanning category, immutable evidence authentication or repository
branch-protection rules are modified.

## Consequences

Future older PR synchronization runs may again be cancelled by a new head
commit, as they were under the accepted pre-#389 implementation. That is
a known limitation, **not** a license to fabricate historical SAST
checks or to treat cancelled runs as successful. An alternative
non-cancelling scan policy would need genuinely observed scanner and
Scorecard results, a separate preflight, and owner acceptance before
deployment.

The rollback itself adds Git commits, so Scorecard's rolling history can
change independently of its scanner implementation. A new genuine,
unfiltered Scorecard analysis must establish the post-rollback result:
**returning to 18/30 is not guaranteed**.

## Assurance impact

The original read-only, non-compensatory CodeQL source job still vets
original two-file SARIF and preserves forensic artifacts, including for
untrusted fork PRs. The accepted-main publisher alone retains narrowly
scoped security-events write privileges. Its original-source run
authentication, active category, explicit **BLOCKED** on contradictory
Code Scanning evidence, and separate native app qualification remain
independently enforced.

Existing 13 required protected GitHub Actions contexts, strict normal
PR merges and zero bypass actors remain. All exact-head required CI,
CodeQL and Security tests must succeed before this rollback merges.
No privileged untrusted workflow, simulated green scan or Scorecard
finding suppression is authorized.

## Non-claims

- The observed 18-to-12 SAST decline is a verified sequence, not
  independently proven causation by CodeQL concurrency.
- The rollback does not automatically restore historical check status,
  resolve SAST alert #27, or certify 30 of 30 genuine scans.
- The rollback does not qualify native Code Scanning publication for
  external forks or justify replacing independent human review with
  automated self-approval.
- Historical ADR 0044 remains visible but is **superseded**, not
  rewritten; previously accepted architectural invariants remain
  authoritative.

**Tracked by:** [#380](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/380)
and [#349](https://github.com/portyu9/qa-automation-ai-agent-evals/issues/349).
