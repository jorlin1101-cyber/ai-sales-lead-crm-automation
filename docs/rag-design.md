# Notion Page-tree-backed Hybrid RAG Design

## 1. 设计目标

本项目的 Week 3 目标，是为 `AI Sales Lead CRM Automation` 增加一个 Notion Page-tree-backed Hybrid RAG 原型。

这个 RAG 模块的目的不是替代当前的 lead scoring，也不是立刻接入 n8n 主流程，而是先建立一个稳定、可测试、可解释的知识库检索链路。

最终目标是：

```text
Notion Page Tree
→ recursive page loader
→ source_path inference
→ knowledge_manifest.yml
→ metadata_resolver
→ Pydantic validation
→ local snapshot
→ structure-aware chunking
→ BM25 retrieval
→ dense retrieval
→ RRF fusion
→ top-k chunks with source metadata
→ later prompt grounding
```

RAG 第一版主要用于增强：

```text
recommended_action
followup_email_draft
```

暂时不影响：

```text
lead_score
intent_level
lead_type
lead_subtype
```

原因是这些字段会影响 CRM 路由和销售优先级。第一版 retrieval 质量还没有稳定验证，不能让检索噪声污染下游分流逻辑。

---

## 2. 为什么需要 RAG

当前系统已经可以完成：

```text
lead cleaning
lead validation
lead scoring
LLM analysis
rule_fallback
recommended_action generation
followup_email_draft generation
```

但是当前 LLM 分析主要依赖：

```text
lead message
cleaned lead fields
prompt instructions
model general knowledge
```

这会带来一个问题：模型可以判断 lead 意向，但未必知道 Eastogo 的真实产品、目的地资料、报价规则和常见销售限制。

例如，一条 lead 写道：

```text
We are a Spanish travel agency looking for a 20 people private custom tour in western Sichuan in September.
```

没有 RAG 时，LLM 可能只能生成泛化回复。

有 RAG 后，系统可以先检索：

```text
Western Sichuan Private Tour
Western Sichuan Destination Overview
Private Tour Pricing Rules
Travel Permit and Payment FAQ
```

再生成更具体的销售建议和邮件草稿。

RAG 要解决的具体业务问题包括：

```text
产品信息缺失
目的地资料不稳定
报价前需要确认的变量不清楚
follow-up email draft 过于泛化
recommended_action 不够基于真实产品资料
```

---

## 3. 为什么使用 Notion 页面树作为知识来源

Notion 页面树更接近很多企业内部知识库的真实状态。

实际团队里的产品资料、目的地资料、FAQ、报价规则，往往不会一开始就整理成严格数据库。更常见的是：

```text
一个知识库总页面
→ 分类页面
→ 多个子页面
→ 页面正文承载具体内容
```

因此，本项目采用：

```text
Notion Page Tree as source of truth
```

建议页面结构：

```text
AI Sales Knowledge Base
  Products
    Western Sichuan
      Western Sichuan Private Tour
    Tibet
      Tibet Cultural Tour
    Yunnan
      Yunnan Family Tour

  Destinations
    Western Sichuan Destination Overview
    Tibet Destination Overview
    Yunnan Destination Overview

  Pricing
    Private Tour Pricing Rules

  FAQ
    Travel Permit and Payment FAQ
```

Notion 负责让业务人员维护内容。Python RAG 模块负责同步、解析、结构化、切分、索引和检索。

---

## 4. 为什么不运行时实时查询 Notion

Notion 适合作为内容源，不适合作为每条 lead 的实时检索引擎。

原因：

```text
Notion 页面正文需要读取 block 内容
页面树需要递归遍历 child pages
嵌套 block 需要递归处理
接口存在分页和速率限制
实时读取延迟高
实时读取不利于测试
实时读取会降低工作流稳定性
```

所以本项目采用同步式架构：

```text
同步阶段：
Notion Page Tree
→ local snapshot
→ chunks
→ indexes

运行阶段：
lead message
→ hybrid retriever
→ top-k chunks
```

运行时检索只读本地 snapshot 和 index，不直接请求 Notion。

---

## 5. 为什么不用页面顶部 Metadata Block 作为主方案

页面顶部 Metadata Block 虽然简单，但长期维护体验差。

它会让业务人员在正文里维护机器字段，例如：

```text
Doc Type: product
Region: western_sichuan
Priority: P0
Status: Active
Tags: ...
```

这个方式可用，但不够优雅。它把“给人看的内容”和“给系统用的 metadata”混在一起。

本项目采用更清晰的方案：

```text
页面正文：业务人员自然维护
metadata：由 source_path inference + knowledge_manifest.yml + metadata_resolver 生成
```

这样可以保持 Notion 内容干净，同时让系统获得稳定 metadata。

Metadata Block 只作为可选 fallback，不作为主方案。

---

## 6. Metadata 解析方案

本项目采用三层 metadata 解析策略：

```text
1. source_path inference
2. knowledge_manifest.yml override
3. optional auto metadata extraction
```

### 6.1 source_path inference

根据页面路径推断基础 metadata。

例如：

```text
AI Sales Knowledge Base / Products / Western Sichuan / Western Sichuan Private Tour
```

可以推断：

```text
doc_type = product
region = western_sichuan
source_title = Western Sichuan Private Tour
source_path = AI Sales Knowledge Base / Products / Western Sichuan / Western Sichuan Private Tour
```

路径推断适合处理：

```text
doc_type
region
source_title
source_path
```

### 6.2 knowledge_manifest.yml

路径推断不够完整，所以需要一个 manifest 文件补充 metadata。

建议路径：

```text
config/knowledge_manifest.yml
```

示例：

```yaml
pages:
  "AI Sales Knowledge Base/Products/Western Sichuan/Western Sichuan Private Tour":
    doc_type: product
    region: western_sichuan
    product_name: Western Sichuan Private Tour
    priority: P0
    status: Active
    tags:
      - western_sichuan
      - private_tour
      - agency
      - custom_group

  "AI Sales Knowledge Base/Pricing/Private Tour Pricing Rules":
    doc_type: pricing
    region: general
    product_name: null
    priority: P0
    status: Active
    tags:
      - pricing
      - quotation
      - group_size
      - private_tour
```

manifest 的作用：

```text
补充路径无法稳定推断的 metadata
统一 taxonomy
避免字段值漂移
支持人工可控配置
便于测试和审查
```

### 6.3 optional auto metadata extraction

自动 metadata extraction 只作为辅助，不作为核心字段来源。

可用于提取：

```text
summary
keywords
suggested_questions
entities
```

不能用于决定核心字段：

```text
doc_type
region
status
priority
```

这些字段必须由路径推断、manifest 或受控规则产生，并经过 Pydantic 校验。

---

## 7. 为什么使用 Pydantic 校验 metadata

metadata 必须稳定，否则后续 retrieval、filter、evaluation 都会混乱。

例如，同一个地区如果出现：

```text
western_sichuan
Western Sichuan
West Sichuan
sichuan_west
```

系统就很难稳定过滤和评估。

因此，metadata_resolver 输出后必须通过 Pydantic 校验。

核心校验内容包括：

```text
doc_type 是否在允许值内
region 是否在允许值内
priority 是否在允许值内
status 是否在允许值内
tags 是否为 list[str]
source_path 是否存在
source_title 是否存在
text 是否非空
```

Pydantic 在这里不是形式化类型检查，而是知识库治理边界。

---

## 8. Knowledge Source Scope

Week 3 第一版知识库范围必须窄。

### P0

必须包含：

```text
产品资料
目的地资料
报价规则
```

这些内容直接影响销售推荐和 follow-up email draft。

### P1

可以包含：

```text
FAQ
```

FAQ 用于支持许可证、支付、预订流程、人数、旅行准备等常见问题。

### 暂不做

Week 3 暂不包含：

```text
公司介绍
品牌理念
大规模营销文案库
Google Docs / 飞书同步
Notion database source
线上搜索索引
```

---

## 9. Retrieval Architecture

Week 3 采用 Hybrid Retrieval。

检索结构：

```text
BM25 sparse retrieval
+
dense embedding retrieval
+
RRF fusion
```

完整流程：

```text
lead message
→ build retrieval query
→ BM25 retrieve
→ dense retrieve
→ RRF fusion
→ top-k RetrievedChunk list
```

---

## 10. 为什么使用 BM25

BM25 用于 sparse retrieval，也就是关键词检索。

它适合处理精确匹配，尤其适合：

```text
产品名称
目的地名称
政策词
报价词
人数
季节
具体旅行方式
```

在当前项目中，典型关键词包括：

```text
Tibet permit
western Sichuan
Daocheng Yading
private tour
quotation
20 people
September
agency
```

这些词对旅游销售非常重要。BM25 可以确保具体关键词不被语义检索漏掉。

---

## 11. 为什么使用 Dense Retrieval

Dense retrieval 用于语义检索。

它适合处理 lead message 和知识库表达方式不同，但含义接近的情况。

例如，客户可能写：

```text
a meaningful cultural journey in Tibetan areas
```

知识库中可能写：

```text
Tibet cultural tour
western Sichuan Tibetan villages
monastery visits
local family experience
```

这些内容关键词不完全相同，但语义相关。Dense retrieval 可以提高语义召回能力。

---

## 12. 为什么使用 RRF Fusion

BM25 和 dense retrieval 的分数体系不同，不能直接相加。

RRF 根据排名融合两路检索结果。

如果一个 chunk 在 BM25 和 dense retrieval 中都排名靠前，它在最终结果中也应该更靠前。

RRF 的作用：

```text
融合 BM25 和 dense retrieval 的排序结果
避免直接混合不同检索器的原始分数
生成统一 top-k results
```

---

## 13. Indexing Flow

Indexing 是离线准备阶段。

流程：

```text
Notion Knowledge Root Page
→ discover child pages
→ recursively load page content
→ extract source_title and source_path
→ infer metadata from source_path
→ apply knowledge_manifest.yml
→ validate metadata with Pydantic
→ save local snapshot
→ chunk documents
→ build BM25 index
→ build dense embedding index
```

本地 snapshot 建议路径：

```text
data/knowledge_snapshot/notion_pages.json
```

这个 snapshot 是后续检索模块的输入。

---

## 14. Runtime Retrieval Flow

Runtime retrieval 发生在 lead message 进入系统时。

流程：

```text
receive lead message
→ use lead message as retrieval query
→ retrieve BM25 top-n results
→ retrieve dense top-n results
→ fuse rankings with RRF
→ return top-k chunks
```

运行时不直接访问 Notion。

示例：

```text
Lead message:
We are a Spanish travel agency looking for a 20 people private custom tour in western Sichuan in September.

Expected retrieved knowledge:
Products / Western Sichuan / Western Sichuan Private Tour
Destinations / Western Sichuan Destination Overview
Pricing / Private Tour Pricing Rules
```

---

## 15. Data Models

### RawNotionPage

表示从 Notion 页面树读取出来的原始页面。

建议字段：

```text
notion_page_id
source_title
source_path
raw_blocks
raw_text
last_edited_time
```

### KnowledgeDocument

表示经过 metadata_resolver 处理后的知识文档。

建议字段：

```text
source_type
notion_page_id
source_title
source_path
doc_type
region
product_name
status
priority
tags
last_edited_time
text
```

### KnowledgeChunk

表示可检索的文档片段。

建议字段：

```text
chunk_id
source_type
notion_page_id
source_title
source_path
doc_type
region
product_name
section
text
last_edited_time
```

### RetrievedChunk

表示检索结果。

建议字段：

```text
chunk_id
source_type
notion_page_id
source_title
source_path
doc_type
region
section
score
retrieval_source
text
```

Hybrid fused result 后续可以加入：

```text
bm25_rank
dense_rank
fused_score
retrieval_sources
```

---

## 16. Evaluation Plan

RAG 必须用测试 query 评估，不能只靠主观感觉。

Week 3 的评估标准：

```text
query 能同时运行 BM25 和 dense retrieval
fusion 能返回统一 top-k chunks
每个 chunk 包含 Notion source metadata
rag_demo.py 能打印 BM25 results、dense results 和 fused results
至少有 8 条 eval queries
top_3 hit rate 至少达到 6/8
pytest 全部通过
```

每条 evaluation query 应该包含 expected source pattern。

示例：

```json
{
  "query": "western Sichuan private custom tour",
  "expected_source_contains": "Western Sichuan"
}
```

如果 fused top 3 results 中包含预期 source，则该 query 通过。

---

## 17. Week 3 Success Criteria

Week 3 完成标准：

```text
Notion Knowledge Root Page 存在
页面树结构清晰
local snapshot notion_pages.json 可生成
metadata_resolver 可用
knowledge_manifest.yml 可用
Pydantic metadata validation 可用
chunker 可生成带 metadata 的 chunks
BM25 retriever 可用
dense retriever 可用
RRF fusion 可用
hybrid retriever 可返回统一 top-k results
rag_demo.py 可展示检索结果
eval query set 至少包含 8 条 query
top_3 hit rate 至少达到 6/8
pytest 全部通过
run-summary.md 已更新
```

---

## 18. Out of Scope

Week 3 不做：

```text
不把 RAG 接入 /process-lead 主流程
不改 n8n
不接 Gmail
不做自动发邮件
不做线上部署
不接 Pinecone / Azure AI Search / Elasticsearch
不做 reranker
不做 Agentic RAG
不做实时 Notion 查询型 RAG
不强制使用 Notion database
```

---

## 19. Future Extensions

后续可扩展：

```text
把 retrieved context 接入 lead analysis prompt
在 LeadAnalysisResult 中返回 retrieved_sources
加入 reranker
生产环境迁移到 Azure AI Search / Elasticsearch / Pinecone
加入增量 indexing
加入 retrieval quality dashboard
接入 n8n workflow
生成带来源依据的 follow-up email
支持 Notion database source
支持 Google Docs / 飞书知识源
```

---

## 20. Interview Explanation

面试时可以这样解释：

```text
我没有把 Notion 当成实时检索引擎，而是把它作为 source of truth。系统会从 Notion 页面树递归同步页面内容，生成本地 snapshot，再通过 metadata_resolver 结合 source_path 和 knowledge_manifest.yml 补齐 doc_type、region、priority、tags 等字段，并用 Pydantic 校验。

之后系统会进行 chunk、BM25 检索、dense embedding 检索和 RRF 融合。这样既保留了 Notion 作为业务知识库的易维护性，又保证 RAG 检索时有稳定 metadata，可以支持过滤、评估、source tracing 和后续 prompt grounding。

当前版本是本地 v1 原型，架构对齐企业 RAG 中常见的 ingestion → schema normalization → indexing → retrieval 思路。后续可以迁移到 Azure AI Search、Elastic、Pinecone 或 Microsoft Graph connector 类系统。
```
