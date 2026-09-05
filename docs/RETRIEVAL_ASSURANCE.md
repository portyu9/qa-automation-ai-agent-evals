# Retrieval Provenance and Poisoning Assurance

This document defines the repository's deterministic retrieval-assurance boundary. It is intentionally narrower than production RAG, hosted vector search, or provider-managed file-search assurance.

## Assurance target

The retrieval path answers one specific evaluation question:

> Did the evaluated agent receive the exact deterministic ranked context derived from the scenario-owned corpus, query, ranker profile, and optional controlled poison relation before subject behavior was graded?

The relation is:

```text
scenario-owned base corpus
        + exact query
        + explicit deterministic ranker profile
        ↓
baseline ranking
        ↓ optional insertion-only poison bound to exact base corpus identity
attacked corpus
        ↓
active ranking
        ↓ exact model-visible canonical JSON
OpenAI tool call selected by the model
        ↓
TOOL_REQUEST
        ↓
RETRIEVAL_DELIVERY receipt
        ↓
TOOL_RESULT
        ↓
verify_retrieval_delivery(...)
        ↓
deterministic subject grading
```

`RETRIEVAL_DELIVERY` is an evaluation-precondition fact. It is **not** itself a PASS, FAIL, safety verdict, citation-quality score, or proof that the model interpreted the retrieved text correctly.

## Scenario-owned retrieval contract

`EvaluationScenario.retrieval` carries one optional `RetrievalContractSpec`. Because the contract participates in scenario identity, changing any behavior-bearing retrieval material invalidates historical scenario identity rather than silently reusing stale evidence.

The contract binds:

- one exact tool name;
- a content-addressed base corpus;
- one exact query and `top_k`;
- one explicit deterministic ranker profile;
- optionally, one insertion-only controlled poison bound to the exact base-corpus identity;
- optionally, a required poison relation such as entering top-k or displacing one exact baseline chunk.

Corpus chunk ordering supplied by a caller is canonicalized before identity calculation. Duplicate chunk identities are rejected. Chunk content, provenance fields, and finite canonical metadata all participate in identity.

## Deterministic ranker

The evaluator-owned ranker is deliberately simple and reproducible rather than production-representative.

Its current contract uses:

- Unicode NFKC normalization;
- Unicode case folding;
- Unicode alphanumeric tokenization without locale dependence;
- integer-only overlap, unique-query coverage, and phrase-bonus scoring;
- explicit profile weights with their own content identity;
- stable tie-breaking by chunk identity and document identity;
- bounded `top_k`;
- canonical JSON serialization of the model-visible result.

This avoids floating-point/vector-backend drift inside the assurance primitive. It does **not** claim semantic-search quality, embedding quality, ANN behavior, reranker quality, hybrid-search quality, or parity with any hosted retrieval product.

## Controlled poisoning relation

`RetrievalPoisonSpec` is insertion-only. It cannot replace an existing `chunk_id`, and it is bound to one exact base-corpus identity.

Two relation classes are supported:

- `enter_top_k`: the inserted controlled chunk must appear in the active top-k result;
- `displace_chunk`: the inserted chunk must enter active top-k and one exact configured baseline chunk must leave it.

If the configured relation does not actually occur under the bound ranker/query/corpus, receipt construction fails closed. A scenario label therefore cannot manufacture a successful poisoning condition.

## Retrieval delivery receipt

`RetrievalDeliveryReceipt` is an integrity-bound evaluator receipt. It records provenance and digests rather than duplicating raw corpus or poison text.

The receipt binds:

- scenario identity;
- retrieval-contract identity;
- tool name and exact call ID;
- base-corpus identity;
- attacked-corpus identity when poisoning is configured;
- query identity;
- ranker-profile identity;
- poison identity and relation when configured;
- baseline and active ranked hit projections;
- digest of the exact model-visible canonical retrieval result;
- a domain-separated receipt root.

Ranked hit projections bind rank, chunk identity, document identity, score, and content digest. Raw retrieved content and raw source locators are intentionally not duplicated into the receipt. Source provenance still participates in each chunk and corpus identity and is therefore bound transitively through `base_corpus_identity` / `attacked_corpus_identity` and `contract_identity` without copying a potentially sensitive URI into durable evidence.

## Required chronology

A configured retrieval scenario requires exactly one target retrieval request, exactly one matching retrieval delivery receipt, and exactly one matching result.

The verifier requires:

```text
TOOL_REQUEST.sequence
    < RETRIEVAL_DELIVERY.sequence
    < TOOL_RESULT.sequence
```

The exact call ID must agree across request, receipt, and result. Request arguments must be strict JSON containing only the exact bound query. Duplicate JSON keys are rejected.

The model-visible result must be a string equal to the canonical active ranking recomputed from scenario-owned source material. Persisted receipt fields are then compared against a freshly rederived receipt.

Missing, duplicated, malformed, reordered, foreign, or unreconstructable retrieval-delivery evidence becomes evaluator uncertainty and blocks grading. It is not rewritten as a behavioral product failure.

## OpenAI Agents SDK bridge

`OpenAIAgentsRetrievalAdapter` is the current provider-specific bridge for this assurance domain.

The adapter:

1. requires a scenario-owned retrieval contract;
2. requires a real pinned OpenAI Agents SDK `Agent` instance;
3. rejects collision with a preconfigured tool using the retrieval tool name;
4. computes the evaluator-owned active ranking before execution;
5. clones the agent with one evaluator-owned retrieval `FunctionTool`;
6. requires the model to select exactly one target call;
7. requires the model-selected query to equal the scenario-bound query;
8. returns the exact canonical ranked context only for that exact query;
9. returns a fixed rejection payload for a mismatched query rather than leaking the bound context;
10. normalizes the SDK request/result through the ordinary OpenAI adapter;
11. inserts `RETRIEVAL_DELIVERY` between the exact request and result;
12. relies on `TrialRunner` verification before deterministic subject grading.

Deterministic integration tests use `agents.testing.ScriptedModel`; they do not call a provider API.

## Replay

Historical replay does not rerun retrieval and does not call the model again.

Instead, replay requires the persisted evidence to match the exact trial, subject, and scenario identities, then `verify_retrieval_delivery(...)` reconstructs the retrieval relation from the scenario-owned contract and persisted model-visible result.

Changing the query, corpus, ranker profile, poison relation, or other scenario-owned retrieval material changes scenario identity. Historical evidence from the prior scenario therefore cannot be silently replayed as though the contract were unchanged.

Replay proves historical internal consistency under the recorded scenario. It does not prove that a current external retrieval service would return the same results now.

## Failure semantics

Retrieval assurance follows the framework's `bad != unknown` rule.

Examples of evaluator uncertainty that become `EVALUATION_ERROR / BLOCKED` include:

- missing retrieval contract for the retrieval adapter;
- target-tool collision;
- missing or multiple target calls;
- unstable/missing call identity;
- mismatched or ambiguous target result;
- model-selected query different from the bound query;
- failed controlled-poison relation;
- missing, duplicated, critical, foreign-source, malformed, or reordered delivery evidence;
- receipt identity/root mismatch;
- model-visible result that cannot be reconstructed from scenario-owned material.

Once the retrieval delivery precondition is verified, ordinary deterministic policy/outcome evidence remains responsible for subject PASS/FAIL.

## Trust boundaries and non-claims

This feature does **not** establish:

- OpenAI hosted File Search behavior;
- provider-hosted vector-store correctness;
- embedding correctness or semantic similarity quality;
- approximate-nearest-neighbor index behavior;
- chunking quality for arbitrary source documents;
- production document ingestion or deletion lifecycle;
- tenant isolation in an external retrieval service;
- metadata-filter correctness in a hosted backend;
- reranking, hybrid retrieval, query rewriting, or multi-query fusion quality;
- citation correctness, citation completeness, or source-grounded factuality;
- browser/search-engine retrieval behavior;
- live provider behavior or provider-side delivery attestation;
- remote retrieval-service availability or consistency;
- prompt-injection resistance merely because a poison entered top-k;
- model attention, interpretation, obedience, resistance, or safe behavior;
- universal RAG poisoning assurance.

The deterministic lexical ranker is an evaluator-owned control surface designed to make retrieval provenance and poisoning relations reproducible. Production retrieval systems require their own adapters and receipts if their actual ranking, filtering, provenance, or lifecycle behavior is to be claimed.

## Why this is separate from `MEMORY` and `RESOURCE`

The generic OpenAI adversarial channels remain unchanged:

- `MEMORY` covers a fresh trial-local SDK session-history boundary;
- `RESOURCE` covers one structured inline-file input boundary.

Neither generic channel proves retrieval selection, ranking, provenance, or poisoning behavior. Retrieval assurance therefore lives in its own scenario/evidence domain rather than silently widening those channel claims.
