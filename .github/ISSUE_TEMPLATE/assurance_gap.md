---
name: Assurance / evaluation gap
about: Propose a missing trust-boundary, adversarial, replay, release, or assurance control
title: "assurance: "
labels: ""
assignees: ""
---

## Gap

What claim, trust boundary, failure mode, or non-claim is not sufficiently exercised today?

## Why it matters

Describe the false-positive/false-negative, security, reliability, provenance, or release risk.

## Proposed evidence boundary

Identify:

- untrusted subject/input;
- evaluator-owned control/precondition;
- normalized evidence or receipt required;
- deterministic oracle/release implication;
- conditions that must remain `BLOCKED` rather than becoming a subject `FAIL` or `PASS`.

## Adversarial cases

List positive and negative cases, including spoofed/missing/reordered/cross-scenario evidence when relevant.

## Non-claims

State what the proposed control still would **not** prove.

Do not attach credentials, private production payloads, secrets, or sensitive customer data.
