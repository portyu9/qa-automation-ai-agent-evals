# ADR 0020: Qualify every workflow pip installer before merge

**Status:** Accepted
**Date:** 2026-10-14
**Supersedes:** None

## Context

Authentic GitHub Code Scanning Scorecard on accepted
`main@f519d90594d2d3cde107374632532a5065db98c3` reported
24 open alerts: 18 `PinnedDependencies` source- or artifact-install heuristics
and six organizational, historical or scanner-recognition findings. PRs
#296, #306 and #357 separately hash-locked the executable third-party
CI, compatibility and maintenance compiler graphs. The Scorecard
monitor currently runs on accepted `main`, **after** merge, not as a
pre-merge veto. Consequently, an accidentally added unhashed third-party
pip download could cause a new warning after acceptance even though CI
was previously green. A pre-merge *preventive* control is needed;
that is different from requiring a zero Scorecard posture warning count.

Before creating implementation branch
`security/scorecard-pip-install-gate-20261014`, the team verified exact
accepted `main@f519d90594d2d3cde107374632532a5065db98c3`,
zero open PRs and only `main` as an active branch. Historical
PRs #296, #306, #337, #350, #351, #354, #356, #357 were already
accepted; there was no divergent or superseded live branch with unique
unmerged capability to salvage. Exact accepted workflow/parser/security
blobs are retained in focused issue #358. The new branch has paired PR
#359 and is not to become orphaned.

## Decision

1. Add a validator-owned, fail-closed **workflow installation inventory**:
   `.github/scripts/validate_workflow_pip_installs.py`. It parses
   GitHub Actions YAML as structured job/step data through the existing
   reviewed semantic workflow parser, not by trusting an
   unverified description inside the workflow.
2. Require executable third-party pip resolutions to use
   `python -m pip install --require-hashes -r` referencing reviewed
   repository-owned hashes for runtime, compatibility or the compiler
   bootstrap; reject direct version-only installs, unsafe indexes,
   noncanonical installer invocation and unsupported acquisition flags.
3. Preserve **only** the validator-owned finite existing locations and
   counts of `--no-deps` checked-out `.`, locally built `dist/*`,
   or independently retained/verified `retained-dist/*` smoke tests.
   These are not equivalent to downloading un-hashed third-party
   packages and should not be deleted to game Scorecard. For a new
   local-install case, update the independently reviewed validator
   allowlist and supply appropriate provenance evidence; a workflow
   cannot self-approve an exception.
4. Bind both the adversarial negative self-test and the actual
   validation to the existing required **Repository policy** CI job,
   before all dependent quality and security jobs. The mandatory
   scanner inventory also checks that those steps cannot be silently
   removed.
5. Retain all downstream independent CodeQL, Security, artifact
   attestation and ruleset-controlled `Package integrity` contracts.
   Any failure remains FAIL rather than being flattened to PASS or
   silently compensated by other scans.

## Consequences

The closed-loop Dependabot controller remains separately responsible
for trusted bot identity, scoped updates, exact-head CI and owner-token
automated reviews. It is not a general-purpose malware repair system or
an independent human reviewer. Existing 18 Scorecard local-install
heuristics remain recorded; this validator provides pre-merge
**new-install regression prevention** and is not a global vulnerability
claim. The remaining ruleset human-review, SAST history, fuzzing
recognition, repository age and Best Practices enrollment require their
own evidence and sometimes administrator/human involvement.

## Assurance impact

This control adds an independently executed, non-compensatory pre-merge CI
qualification: a single invalid pip install command fails the required
Repository policy job, then the required aggregate CI gate. Hash
identity and local-artifact provenance remain separate from evaluator
judgment, release attestation, and CodeQL security scan authority.
It never converts absent or unverified evidence into a passing result.

## Non-claims

The validator cannot prove that pinned packages are safe or that hashes
authenticate their publisher, that existing checked-out code is
non-malicious, that Scorecard heuristics represent exploitable flaws,
or that a GitHub Code Scanning alert was fixed before an authentic
accepted-main rescan. No existing alert is dismissed by this ADR.
A separate authentically configured required CodeQL/Security gate
continues to enforce execution security; workflow installer inventory
does not replace it. Nor can GitHub's disabled native auto-merge be
represented as enabled by declaring `automergeEnabled` in a
**Dependabot-specific** JSON policy.
