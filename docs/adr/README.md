# Architecture Decision Records

This directory records durable decisions that change the framework's assurance semantics, trust
boundaries, evidence interpretation, release authority, or executable compatibility contract.

## When an ADR is required

The versioned policy in .github/semantic-adr-policy.json enumerates governed repository paths.
For pull requests, CI compares the exact base and head commits. If any governed path changes, the
change must add a new numbered ADR matching:

docs/adr/NNNN-lowercase-kebab-title.md

Editing, renaming, or reusing an existing ADR does not satisfy the gate. There is no free-form
"no ADR needed" exemption for a governed path. If the governed-path policy is too broad or too
narrow, changing that policy is itself governed and therefore requires a new ADR.

## Lifecycle

ADRs are append-only decision history. Do not rewrite an accepted ADR to make history appear as if a
later design had always been intended. A later decision supersedes an earlier one by adding a new
ADR that names the earlier record and explains the transition.

Every accepted ADR must contain context, decision, consequences, assurance impact, and explicit
non-claims. The template is ADR 0000 (0000-template.md).

An ADR documents repository intent. Its presence does not prove that the decision is correct,
independently reviewed, cryptographically authenticated, or live-enforced outside the repository.
Executable tests, CI, evidence, release qualification, and external administration remain separate
authority domains.
