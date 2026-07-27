# RAG Evaluation

本文档记录当前冻结的检索评测证据，并明确区分离线 CLI 与历史 BGE-M3 评测。

## Retrieval Architecture

```text
sanitized knowledge snapshot
-> heading-aware chunks
-> BM25 candidates
-> dense candidates
-> Reciprocal Rank Fusion
-> sanitized Top 3
```

当前知识快照包含 47 个 chunks。运行时不会为每条 lead 实时读取 Notion。

## Backends

| Backend | Components | External network |
| --- | --- | ---: |
| `disabled` | no retrieval | No |
| `keyword_rrf` | BM25 + local KeywordEmbeddingProvider + RRF | No |
| `bge_rrf` | BM25 + BGE-M3 dense + RRF | Yes |

`RAG_REQUIRED=false` 时，检索故障安全降级为 `sources=[]` 和通用建议。
`RAG_REQUIRED=true` 时，服务返回 `rag_unavailable`，不会编造来源。

评分与检索之间有一条强制边界：

```text
PolicyV1 creates and freezes LeadDecision
-> RAG runs afterwards
-> RAG cannot change score, intent, or disposition
```

## Frozen BGE-M3 Evaluation

Artifacts:

- [Reviewed analysis](../reports/rag-eval-bge-m3-v4-reviewed-analysis-20260721.md)
- [Reviewed JSON report](../reports/rag-eval-bge-m3-v4-reviewed-20260721.json)
- [Official labels](../data/rag_eval/eval_queries.json)

Configuration:

```text
47 knowledge chunks
18 manually curated queries
BM25 + BGE-M3 dense + RRF
top_k=3
candidate_top_k=5
no reranker
103 paired title/section judgments
```

Reviewed results:

| Query path | Direct Top 1 | Direct Top 3 | MRR@3 | nDCG@3 | Facet Recall@3 | Unjudged@3 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Raw query | 16/18 | 18/18 | 0.9444 | 0.8111 | 1.0000 | 0.0000 |
| Rule-only query | 11/18 | 14/18 | 0.6852 | 0.5167 | 0.7778 | 0.4630 |
| Raw + RetrievalIntent fusion | 18/18 | 18/18 | 1.0000 | 0.8331 | 1.0000 | 0.0000 |

Direct Hit 要求命中人工标注为 grade 3 的 `title + section` 对，不是宽松的
“同一来源出现过”。

## Evidence Boundary

- `scripts/demo_cli.py rag` 实时运行的是完全离线的 `keyword_rrf`。
- 上表来自一次使用外部 embedding 服务生成的 BGE-M3 排名。
- reviewed report 只对保存下来的排名重新评分，没有再次调用网络。
- 因此这些数字不能表述为离线 CLI 的实时 BGE-M3 结果。

## Current Interpretation

原始问题已经能稳定覆盖当前 18 条测试中的核心知识目标。规则抽取后的查询单独使用时
会丢失上下文，因此当前推荐方向是保留原始问题，并将结构化 RetrievalIntent 作为补充
信号，而不是完全替换原文。

评测集规模仍然较小。任何生产结论都需要更多业务问题、负样本和持续人工标注支持。

## Recommendation Boundary

检索完成后，系统可以选择性地让 LLM 根据已冻结的 `LeadDecision` 和本次 Top 3 证据生成
建议，但该能力默认关闭，不属于上述检索指标。它不能反向修改评分，失败时回落为确定性
模板。推荐生成的安全边界和独立 12 条人工评测集见
[Grounded recommendation](grounded-recommendation.md)。
