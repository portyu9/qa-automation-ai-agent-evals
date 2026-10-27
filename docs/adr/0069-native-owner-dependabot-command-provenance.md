# ADR 0069: Native owner Dependabot recovery requires native comment provenance

**Status:** Accepted
**Date:** 2026-10-27
**Extends:** ADR 0068's bounded one-rebase/one-recreate refresh state machine.

## Observed failure
Signed Dependabot Actions PR #417 did not advance after an owner rebase and connector-mediated recreate. REST comments show owner-authored `@dependabot rebase` comment 6425130632 on October 26 had `performed_via_github_app=null` and Dependabot (ID 49699333) reacted +1. October 27 owner rebase 6444613050 had no bot reaction. October 27 recreate comment 6448067278 reported `performed_via_github_app.slug=chatgpt-codex-connector`; it also had no bot reaction. The accepted state machine treated the last App-authored comment as an authentic native owner command merely because the comment displayed the owner's numeric identity, permanently exhausting its bounded recovery.

## Decision
For each exact signed bot head SHA and accepted main SHA, continue recognizing a finite pair of one rebase then one recreate after the configured delay. In addition to owner account login, immutable numeric ID, exact immutable marker, and command prefix, require the comment's `performed_via_github_app` key to be present and **null**. A non-null App identity never consumes the native owner refresh budget, regardless of which login GitHub displays. Missing provenance for a purported owner-native marker fails closed, not guessed. Only the already authorized push-capable owner token can submit the native command. Revalidations before emission preserve exact PR head/base/current main, current signed Dependabot source, controlled changed-path scope, and owner token identity. No branch rewrite, check publication or ruleset change occurs.

## Assurance and terminal truth
Inline deterministic state-machine tests cover the observed connector impersonation, owner misidentification, missing origin, malformed App origin, duplicate native rebase/recreate, bad UTC timestamps, stale bot head/base, and replay after one finite native recovery. A GitHub comment 201 is only proof of a **request**; Dependabot acknowledgment and new signed head/green CI must be observed independently. Once a legitimate native command has exhausted the bounded budget, the controller must remain blocked pending signed source and no more commands may be spammed. Keep the original bot PR #417 open until native branch advances and protected gates can pass.

## Immutable lineage
Latest accepted main `1a250421434761df11b4f5ac2c916c36aa660a11`; old governance source blob `0188a9066e74be7472f5ca56e6ef41e70aaae3cb`; native signed branch `a03140e930cc0c124e2ea6501e62a6fa037d510f`. See #417's 2026-10-27 comprehensive lineage-and-salvage preflight before feature branch creation.
