---
name: Bug report
about: Report a reproducible framework defect without sensitive production data
title: "bug: "
labels: ""
assignees: ""
---

## Defect

Describe the observed behavior and the expected behavior.

## Reproduction

Provide a minimal **synthetic** reproducer, affected commit/version, Python version, and relevant optional extras.

Do **not** include API keys, bearer tokens, private production transcripts, credentials, customer data, or exploit-ready sensitive details. Use `.github/SECURITY.md` for security-sensitive reports.

## Assurance impact

Which result can be affected?

- [ ] evidence integrity / replay
- [ ] authorization / handoff / approval
- [ ] deterministic grading
- [ ] semantic judging
- [ ] statistical aggregation / release gate
- [ ] MCP / OAuth protocol assurance
- [ ] packaging / CI / tooling
- [ ] other

Can the defect produce a false `PASS`, hide a critical failure, manufacture evaluator-owned evidence, or invalidate historical replay? Explain without disclosing sensitive exploit details publicly.

## Evidence

Include safe stack traces, failing test names, synthetic evidence roots, or CI links when available.
