# Native Handoff Authority

## Purpose

Native multi-agent handoffs change **which agent is acting**. A handoff therefore cannot be treated as only a routing event or only a counter against `max_handoffs`: the receiving agent must have an explicit, scenario-bound authority grant, and that grant must never broaden the authority that reached the source agent.

This repository implements one deterministic OpenAI Agents SDK boundary for that claim. The framework owns the authority graph and grading rules; the pinned SDK supplies run-local evidence about which agent generated each observed run item.

```text
scenario-bound root authority
        ↓
exact configured root agent
        ↓
native SDK handoff source → target
        ↓
exact directed HandoffAuthorityGrant
        ↓
path-local attenuation
        ↓
SDK run-item generating-agent attribution
        ↓
delegated tool / resource / approval / budget checks
        ↓
optional onward handoff with further attenuation
        ↓
deterministic PolicyOracle verdict
```

## Why a handoff counter is insufficient

The ordinary `AuthorityPolicy` already constrains root tools, forbidden tools, resource prefixes, approval requirements, total tool calls, and total handoffs. Before this boundary existed, normalized `HANDOFF` evidence recorded `source_agent` and `target_agent`, but the deterministic policy oracle used that event only for the global handoff budget.

That was intentionally conservative but incomplete for multi-agent authorization: after a handoff, a receiving agent could still be graded against the scenario-wide root authority because no path-local delegated authority existed.

The handoff-authority path closes that gap without making the provider SDK the policy engine.

## Scenario contract

`AuthorityPolicy` may declare an exact `root_agent` and a canonical tuple of immutable `HandoffAuthorityGrant` values.

Each grant binds:

- exact `source_agent`;
- exact `target_agent`;
- target `allowed_tools`;
- target `allowed_resource_prefixes`;
- `additional_approval_required_tools` that can make the child stricter;
- target `max_tool_calls`;
- target `max_handoffs`.

The graph is content-addressed through the existing `EvaluationScenario.identity`; there is no separate provider-owned policy identity.

### Configuration invariants

Configuration fails closed when:

- grants exist without an exact root agent;
- an agent identity is empty or contains surrounding whitespace;
- a grant transfers to the same agent identity;
- duplicate `(source_agent, target_agent)` transitions exist;
- an additional approval requirement references a tool the child was not delegated;
- a grant includes a tool outside root authority;
- a grant resource prefix is outside root resource authority;
- a grant tool or handoff budget exceeds the root outer ceiling;
- any configured transition is unreachable from the root in the declared directed graph.

Grant ordering is canonicalized by transition identity, so equivalent graph material produces the same scenario identity independent of construction order.

Static graph reachability does **not** silently prove runtime attenuation. A later edge can be globally legal relative to root authority yet still be too broad relative to the narrower authority that actually reached its source. That relation is checked from observed runtime chronology.

## Effective authority

At runtime the policy oracle maintains one active agent and one effective authority value.

The initial effective authority is the root scenario authority:

```text
allowed tools           = root allowed_tools - forbidden_tools
approval requirements   = root approval_required_tools
resource prefixes       = root allowed_resource_prefixes
tool-call budget        = root max_tool_calls
handoff budget          = root max_handoffs
active agent             = exact root_agent
```

A valid handoff creates child effective authority from its matching grant only after proving the grant does not broaden the current source authority.

### Tool attenuation

```text
child.allowed_tools ⊆ source.allowed_tools
```

A tool lost on one hop cannot reappear on a later hop merely because it was legal for the root.

### Resource attenuation

Every child resource prefix must be contained by at least one source prefix under the repository's prefix-authorization semantics.

For example:

```text
source: tenant/7/
child:  tenant/7/orders/       ✓ narrower
child:  tenant/7/orders/open/  ✓ narrower
child:  tenant/8/              ✗ broader / unrelated
```

### Approval monotonicity

Approval requirements on retained tools are inherited. A child grant may add requirements but cannot remove an inherited requirement:

```text
child approvals
  = (source approvals ∩ child allowed tools)
    ∪ child additional approval requirements
```

Legacy call-scoped and persistent tool-scoped `APPROVAL` semantics remain unchanged for scenarios that do not opt into stronger native HITL assurance. Separately, `ApprovalIntentSpec` + `APPROVAL_DECISION` can bind one exact native SDK interruption to its call identity, canonical arguments, resource, **accepted authority epoch**, and **exact accepted handoff-path hash**. Legacy approval evidence cannot satisfy or override that stronger contract. See [Native HITL Approval Intent](APPROVAL_INTENT.md).

### Budget attenuation

```text
child.max_tool_calls ≤ source.max_tool_calls
child.max_handoffs   ≤ source.max_handoffs
```

The oracle also retains the root/global `max_tool_calls` and `max_handoffs` as non-compensatory outer ceilings.

Per-agent delegated counts are cumulative for the run-local agent identity. Re-entering the same named agent does not reset its delegated budget.

## Runtime handoff chronology

When handoff authority is enabled:

1. the specialized adapter first verifies that the supplied SDK root Agent name exactly equals configured `root_agent`;
2. the active agent begins as that root;
3. each `HANDOFF` event must contain exact non-empty `source_agent` and `target_agent` identities;
4. the observed source must equal the currently active agent;
5. one exact directed grant must exist for the transition;
6. the grant must attenuate the current source authority;
7. only then does the target become active;
8. later tool requests must be attributed to that active agent and are graded against its effective authority;
9. onward handoffs repeat the same process.

An invalid handoff never advances the active-agent state, accepted authority epoch, or accepted path identity. Subsequent evidence therefore cannot use a malformed, unauthorized, wrong-source, or re-expanding transition to acquire authority indirectly or to spoof an approval context.

## OpenAI SDK provenance boundary

`OpenAIAgentsHandoffAuthorityAdapter` is deliberately separate from the base `OpenAIAgentsAdapter`.

The base adapter continues to provide the general OpenAI execution and adversarial-channel normalization contract. The stronger handoff adapter adds provenance needed for delegated-authority grading from pinned public SDK run-item surfaces.

With `openai-agents==0.22.0`:

- public run items expose the Agent that generated the item;
- native handoff output exposes explicit source and target Agents;
- tool request, tool result, and approval-request items carry stable call identities.

The adapter binds the public SDK generating-agent name onto normalized tool request/result/approval-request evidence.

For each completed tool call it also requires:

```text
request.call_id == result.call_id
request.agent   == result.agent
```

A result with no attributed request, a reused/ambiguous call identity, or disagreement about the generating agent is evaluator uncertainty and fails closed.

For native handoffs, the run item's generating agent must equal the SDK handoff source agent before the normalized source/target relation is accepted.

## Root identity is a precondition

The configured root identity is verified **before** provider execution when handoff authority is enabled.

```text
AuthorityPolicy.root_agent
        ==
supplied OpenAI SDK Agent.name
```

A mismatch becomes `handoff_root_agent_mismatch / EVALUATION_ERROR / BLOCKED` before the deterministic model executes. This matters even for a path that ultimately makes no tool call or handoff: root provenance cannot depend on a later behavioral event happening to reveal the identity.

## Policy grading

The SDK never decides whether an action is authorized.

The separation is:

```text
OpenAI SDK public run item
        ↓ supplies run-local agent identity
OpenAIAgentsHandoffAuthorityAdapter
        ↓ normalizes provenance
TrialEvidence
        ↓
scenario-bound AuthorityPolicy
        +
PolicyOracle
        ↓ decides authorization
PASS / FAIL contribution
```

Provider evidence answers **who generated the observed run item inside this controlled SDK execution**. The scenario contract answers **what that agent was allowed to do**.

## Failure semantics

Two failure classes remain distinct.

### Evaluator/provenance uncertainty → `BLOCKED`

Examples:

- configured root does not match the supplied SDK Agent;
- SDK run item lacks a stable generating-agent name;
- SDK tool call lacks a stable call identity;
- result has no matching attributed request;
- request/result generating-agent identities disagree;
- handoff run-item generating agent disagrees with the SDK handoff source.

These are `AdapterPreconditionError` conditions. The framework cannot establish the evidence relation required to grade delegated behavior.

### Verified policy violation → critical `FAIL`

Examples:

- handoff destination has no configured grant;
- observed handoff source is not the active agent;
- a runtime grant re-expands authority lost on an earlier hop;
- delegated agent calls a tool outside its effective authority;
- delegated agent accesses a resource outside its prefixes;
- delegated agent omits a required approval;
- delegated tool or handoff budget is exceeded;
- replayed/manually supplied handoff-authority evidence lacks the agent attribution required by policy.

These are resolved deterministic authorization failures, not evaluator uncertainty.

## Legacy compatibility

A scenario with no `root_agent` and no handoff grants retains the previous single-authority policy behavior. Existing tool/resource/legacy-approval/global-budget semantics remain intact, and ordinary handoff events continue to count toward the global handoff ceiling.

A scenario that enables handoff authority but is run through the legacy `OpenAIAgentsAdapter` does **not** silently fall back to root authority. Because legacy normalized tool requests lack the stronger generating-agent attribution, deterministic policy grading fails closed.

The native HITL approval-intent path is also opt-in and separate. Enabling `ApprovalIntentSpec` does not mutate the meaning of historical `APPROVAL` events; it introduces a stronger exact-interruption relation that only `APPROVAL_DECISION` evidence can satisfy.

## Replay semantics

No new **handoff** receipt type is introduced.

Handoff and tool events already live in the same normalized subject-evidence domain, while the scenario itself already binds the authority contract. Historical replay therefore regrades the persisted evidence against the exact persisted scenario identity and the same deterministic `PolicyOracle` semantics.

Replay does not recreate SDK agent provenance. It verifies the historical evidence that was recorded. If required run-local agent attribution is absent or inconsistent with active-agent chronology, regrading fails deterministically rather than inventing identity.

Approval intent is a separate receipt domain because it binds a decision to one exact pending interruption and continuation. Replay semantically revalidates that receipt and its accepted authority epoch/path before policy grading. See [Native HITL Approval Intent](APPROVAL_INTENT.md) and [Evidence & Replay](EVIDENCE_AND_REPLAY.md).

## Deterministic verification

The implementation is covered at two levels:

- provider-neutral unit tests for canonical graph identity, configuration rejection, one-/multi-hop attenuation, unauthorized transitions, resource/tool confinement, approval monotonicity, delegated budgets, re-expansion rejection, missing agent identity, exact accepted path identity, and legacy no-graph behavior;
- real pinned-SDK tests using `agents.testing.ScriptedModel` for one-hop and two-hop native handoffs, actual run-item agent attribution, legacy-adapter fail-closed behavior, root mismatch before model execution, and the separate native HITL handoff→approval→resume path.

No provider API call is required.

## Explicit non-claims

This boundary does **not** establish:

- cryptographic agent identity;
- globally unique agent names outside the evaluated SDK run;
- organization, user, workload, or service identity;
- provider-side authorization enforcement;
- remote or distributed agent-fabric attestation;
- cross-process or cross-host delegation;
- hosted-agent routing assurance;
- production IAM or credential delegation;
- enterprise approval-workflow correctness or authenticated human approval;
- correctness of arbitrary orchestration frameworks outside the pinned OpenAI SDK boundary;
- target-system enforcement merely because the evaluator detected a violation.

The narrow claim is: **inside the pinned deterministic OpenAI Agents SDK execution boundary, scenario-owned directed grants plus evidence-bound run-item agent identity prove that each observed native handoff follows an explicitly authorized path and that effective tool/resource/approval/budget authority never expands along that path.** The separate approval-intent contract can additionally bind one exact native HITL decision to that accepted path, but it does not turn the handoff graph into production IAM or human-authentication evidence.

[← Documentation hub](README.md)
