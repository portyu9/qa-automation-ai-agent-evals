## Summary

Describe the change and link the focused issue/master backlog item.

Closes #
Tracks #192 item(s):

## Assurance impact

- [ ] I identified every trust/evidence boundary this change touches.
- [ ] Deterministic failure remains non-compensatory; semantic grading cannot rescue it.
- [ ] Missing/unverifiable evidence still fails closed (`BLOCKED`/explicit uncertainty as appropriate).
- [ ] No evaluated subject/adapter gains evaluator-owned authority through self-declared data.

## Evidence / replay compatibility

- [ ] This change does **not** alter durable evidence/receipt/report parsing, canonical identity, or historical replay semantics.
- [ ] Or: it does alter them, and the PR includes an explicit schema/version transition plus old/new compatibility tests and documentation.
- [ ] Persisted historical evidence is not silently reinterpreted under an unchanged schema identity.

## Architecture decision record

- [ ] No governed assurance-semantic path is changed.
- [ ] Or: this PR adds a new numbered ADR under docs/adr/ describing the decision, consequences,
      assurance impact, and non-claims.
- [ ] I did not edit/reuse an old ADR as a substitute for a new governed decision.

## Security review

- [ ] No secrets, credentials, private production payloads, or sensitive user data are added to tests/docs/logs.
- [ ] Authorization/resource/approval/handoff changes include adversarial negative tests.
- [ ] New GitHub Actions are full commit-SHA pinned and workflow permissions remain least-privilege.

## Repository governance review

- [ ] This change does not alter CODEOWNERS, CI/release authority, protected-history policy, or live-admin prerequisites.
- [ ] Or: it does alter repository governance, and the PR updates `.github/repository-governance.json`, `docs/REPOSITORY_GOVERNANCE.md`, and executable policy checks as required.
- [ ] I have not represented repository-owned policy as proof that a live GitHub administration setting is enabled.

## Statistical review

- [ ] No statistical contract changes.
- [ ] Or: sampling/independence/stopping assumptions, uncertainty, thresholds and multiple-comparison implications are explicitly documented and tested.

## Validation

- [ ] `ruff check .`
- [ ] `ruff format --check --diff .`
- [ ] `mypy`
- [ ] default `pytest` / coverage gate
- [ ] relevant OpenAI/MCP integration lane(s), if touched
- [ ] Bandit/dependency audit/package integrity, if touched

## Remaining non-claims

List any important capability/security claim this change intentionally does **not** establish. Do not broaden repository claims beyond executable evidence.
