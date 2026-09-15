# Algorithmic complexity and denial-of-service bounds

Trust-critical deterministic work is bounded before expensive canonicalization or statistical arithmetic. These limits are correctness and availability contracts, not benchmark claims: accepted inputs must remain deterministic across supported Python versions, while inputs outside the supported work envelope fail closed with `ValueError`/validation errors.

## Contract canonicalization

General contract identity material is checked iteratively before recursive JSON canonicalization and hashing. The guard rejects reference cycles and enforces:

| Limit | Ceiling | Purpose |
| --- | ---: | --- |
| nesting depth | 32 | prevents recursion-depth attacks in canonicalization/JSON serialization |
| total material nodes | 100,000 | bounds traversal work across nested mappings/collections |
| elements in one mapping/collection | 10,000 | bounds sorting and breadth-sensitive work |
| aggregate UTF-8 bytes in keys/string values | 1 MiB | bounds scalar scanning before serialization |
| canonical JSON | 4 MiB | bounds the final serialized/hash input |
| directly hashed text (including subject instructions) | 4 MiB | bounds one-shot text hashing input |
| integer magnitude | 4,096 bits | prevents pathological integer-to-decimal serialization |

The limits execute before `json.dumps` for scenario state/outcome material and before `_canonicalize`/hashing for subject behavior material. Accepted material uses the unchanged canonical JSON ordering/separators and SHA-256 domains, so existing identities remain byte-for-byte stable.

Typed resource identifiers already have their own tighter component-count and component-length bounds; this change does not widen them. Evidence payloads and receipts remain governed by the separate ceilings documented in `RESOURCE_CEILINGS.md`.

## Statistical kernels

Deterministic reliability and paired-comparison kernels support at most **100,000 trials/pairs** per in-memory calculation. This intentionally matches the upper scale target tracked by the repository's 10k/100k scalability roadmap while preventing accidental unbounded CPU/memory work in synchronous APIs.

`pass@k` / `pass^k` transforms require `1 <= k <= 1,000,000`. Larger values add no useful assurance precision in this in-memory contract and are rejected instead of accepting arbitrary-size caller-controlled exponents.

The two-sided exact McNemar definition is unchanged. Its binomial lower tail is now evaluated from a log-PMF followed by a downward floating-point recurrence. This removes construction of `comb(n, i)` and `2**n` big integers while keeping work linear in the smaller discordant tail and bounded by the 100,000-pair ceiling. Small known vectors are regression-tested against their exact probabilities; extreme tails may underflow to `0.0`, which is the same float-level result used by downstream significance decisions.

## What these bounds do not claim

These ceilings do not replace future streaming aggregation, 10k/100k benchmark suites, mutation/property/fuzz campaigns, or process-level memory/CPU isolation. They bound the synchronous deterministic kernels that exist today. Provider calls, MCP transports, evidence persistence, and live adapters retain their own timeout/resource contracts.
