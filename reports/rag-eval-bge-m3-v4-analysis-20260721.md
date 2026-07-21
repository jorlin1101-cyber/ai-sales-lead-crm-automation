# BGE-M3 v4 Retrieval Evaluation Analysis

## Evaluation scope

- Label contract: `paired-graded-relevance-v2`
- Evaluation cases: 18
- Knowledge chunks: 47
- Retrieval: BM25 + BGE-M3 dense retrieval + RRF
- Reranker: not used
- Live LLM: not used
- Dataset SHA-256: `d0331383cc972035959de5fea55b89e5a8c37e144206ed7203ccef88202e5e6e`
- Knowledge SHA-256: `db438bcf4b45a93b749edb081b74abb75fe9020863f9ef59590ee54d6c7ed6d3`

The BGE and Keyword reports use the same dataset and knowledge snapshot hashes, so their
quality metrics are directly comparable.

## BGE-M3 versus Keyword baseline

| Query path | Keyword Direct Top 1 | BGE Direct Top 1 | Delta | Keyword Direct Top 3 | BGE Direct Top 3 | Delta |
|---|---:|---:|---:|---:|---:|---:|
| Raw query | 13/18 | 16/18 | +3 | 17/18 | 18/18 | +1 |
| Rule-feature query | 7/18 | 11/18 | +4 | 12/18 | 14/18 | +2 |
| Raw + retrieval-intent fusion | 11/18 | 18/18 | +7 | 17/18 | 18/18 | +1 |

## BGE-M3 graded ranking metrics

| Query path | MRR@3 | nDCG@3 | Facet Recall@3 | Unjudged@3 |
|---|---:|---:|---:|---:|
| Raw query | 0.9444 | 0.7700 | 1.0000 | 0.2407 |
| Rule-feature query | 0.6852 | 0.5167 | 0.7778 | 0.5000 |
| Raw + retrieval-intent fusion | 1.0000 | 0.7905 | 1.0000 | 0.2407 |

## Raw-query Top-1 misses

### `multi_family_price_001`

- Question: family suitability in Yunnan plus final quotation factors.
- Raw Top 1: `Yunnan Family Tour / Sales Follow-up Notes`, grade 2.
- First direct answer: rank 2.
- Fused Top 1: `Yunnan Family Tour / Pricing Notes`, grade 3.
- Interpretation: the original question found useful family-sales context first; the added
  pricing and family retrieval intents moved the direct pricing answer to rank 1.

### `payment_deposit_balance_002`

- Question: pay a deposit first and the remaining balance later.
- Raw Top 1: `Travel Permit and Payment FAQ / Sales Notes`, unjudged grade 0.
- First direct answer: rank 2.
- Fused Top 1: `Travel Permit and Payment FAQ / Common Questions`, grade 3.
- Interpretation: the payment-policy intent made the deposit/balance meaning explicit and
  promoted the direct answer to rank 1.

## Rule-feature Top-3 failures

The feature-only query lost essential wording in four cases:

- `trip_duration_001`
- `fuzzy_family_pace_001`
- `payment_before_arrival_001`
- `region_tibetan_culture_not_lhasa_001`

This confirms that `RuleFeatureExtractor -> LeadFeatures` is useful as an additional signal,
but should not replace the customer's original message for retrieval.

## Conclusion

For this frozen 18-case dataset, the strongest evaluated path is:

`raw customer question + deterministic retrieval intent -> BM25 + BGE-M3 -> RRF`

It reached Direct Top 1 and Top 3 of 18/18. This is evidence that BGE-M3 and query fusion are
useful for the current knowledge base, but it is not proof of production-level perfection:
the dataset is small and the fused Unjudged@3 rate is still 24.07%. The next quality step
should expand the query set and judge the currently unjudged Top-3 pool before tuning more
retrieval parameters or adding a reranker.

## Latency note

The BGE run embedded 47 knowledge chunks in one batch and prewarmed 39 unique query strings in
one batch. Index construction took 11.137 seconds and query prewarming took 6.744 seconds. The
per-query latency values in the JSON report use cached vectors and therefore exclude external
embedding API time.
