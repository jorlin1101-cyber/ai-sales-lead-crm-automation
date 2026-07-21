# BGE-M3 RAG Evaluation — Reviewed Label Rescore

Date: 2026-07-21

## What changed

- 13 previously unjudged title/section pairs were manually reviewed.
- The official evaluation pool increased from 90 to 103 judgments across the same 18 queries.
- Review grades: six grade-0, one grade-1, six grade-2, and zero grade-3.
- Dataset SHA-256: `4a677c21056008039885f98af3a4929ee57fe70f1d39e7d89541ef9fc8bb79b6`
- Knowledge SHA-256: `db438bcf4b45a93b749edb081b74abb75fe9020863f9ef59590ee54d6c7ed6d3`

The BGE-M3 retrieval rankings were not rerun. This report only rescored the stored rankings
against the expanded reviewed label pool, so no network access or embedding API call was used.

## Reviewed BGE-M3 metrics

| Query path | Direct Top 1 | Direct Top 3 | MRR@3 | nDCG@3 | Facet Recall@3 | Unjudged@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Raw query | 16/18 | 18/18 | 0.9444 | 0.8111 | 1.0000 | 0.0000 |
| Rule-only query | 11/18 | 14/18 | 0.6852 | 0.5167 | 0.7778 | 0.4630 |
| Raw + retrieval-intent fusion | 18/18 | 18/18 | 1.0000 | 0.8331 | 1.0000 | 0.0000 |

## Interpretation

- The fused path remains the strongest evaluated path: every query has a grade-3 direct answer
  at rank 1, and every declared facet is covered within the Top 3.
- Fused nDCG@3 increased from 0.7905 to 0.8331 because the new grade-1 and grade-2 judgments
  distinguish useful supporting results from irrelevant results.
- Fused Unjudged@3 fell from 0.2407 to 0.0000, so all 54 fused Top-3 positions now have explicit
  human labels.
- The rule-only path still has an Unjudged@3 rate of 0.4630 because this review round targeted the
  BGE fused Top-3 pool, not every rule-only result. This does not invalidate the fused-path result,
  but rule-only comparisons remain less complete.
- Direct hit rates did not change because no newly reviewed item received grade 3.

## Artifacts

- Source retrieval report: `reports/rag-eval-bge-m3-v4-20260721.json`
- Reviewed rescore report: `reports/rag-eval-bge-m3-v4-reviewed-20260721.json`
- Review decisions: `data/rag_eval/review/bge-m3-v4-unjudged-review.json`
- Official evaluation labels: `data/rag_eval/eval_queries.json`
