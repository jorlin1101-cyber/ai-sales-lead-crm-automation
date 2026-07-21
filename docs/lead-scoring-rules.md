

所以规则要改。

---

# 我的新判断

> **历史文档（已被替代）：** 本文包含早期评分探索和已经删除的 `LeadScoreResult` / `scoring.py`。当前唯一正式评分实现为 `services/policy_v1.py`，规则以其测试为准。

> **历史文档（已被替代）：** 本文包含早期评分探索和已经删除的 `LeadScoreResult` / `scoring.py`。当前唯一正式评分实现为 `services/policy_v1.py`，规则以其测试为准。

你的 `LeadScoreResult` 现在用：

```python
b2b_subtype
```

这个字段已经不够用了。

因为现在要同时判断：

```text
B2B Agency
B2B Operator
B2B School
B2C Large Group
B2C Private Custom
B2C Luxury / High Budget
B2C FIT
```

所以我建议把字段从：

```python
b2b_subtype
```

改成：

```python
lead_subtype
```

这是现在就该改的地方。别等后面 FastAPI 写完再改，那时候成本更高。

---

# 新版评分逻辑

建议分成 4 个维度：

```text
客户类型匹配：0–30
意向强度：0–30
订单价值潜力：0–25
信息完整度：0–15
总分：100
```

这比之前更合理。
之前“业务价值信号”和“信息完整度”有点重叠，现在改成“订单价值潜力”，专门识别大团、私人团、高预算、长线行程。

---

直接复制下面内容，替换你的 `docs/scoring-rules.md`。

````markdown
# Lead Scoring Rules

## 1. Purpose

本文档定义 AI Sales Automation System 当前阶段的规则评分逻辑。

当前规则评分不是最终 AI 判断方案，而是作为 **rule-based fallback** 使用。

系统总体策略是：

```text
LLM-first + rule-based fallback
````

当 LLM 可用时，系统优先使用 LLM 做复杂语义判断、摘要、推荐动作和邮件草稿生成。

当 LLM 不可用、超时、输出不合法或成本限制触发时，系统回退到本规则评分逻辑。

---

## 2. Core Design Change

旧规则过度偏向 B2B，会把很多 B2C lead 归为 `Unknown`。

这不合理。

对入境游业务来说，以下 B2C lead 也可能非常有价值：

* 大团客户
* 私人定制团
* 高预算家庭团
* 长线深度游客户
* 明确日期、人数、目的地、预算的个人客户

因此当前规则不再简单使用：

```text
B2B = valuable
B2C = Unknown
```

而是改为：

```text
根据客户类型、意向强度、订单价值潜力、信息完整度综合评分
```

---

## 3. Recommended Schema Change

当前 `LeadScoreResult` 不建议继续使用：

```text
b2b_subtype
```

建议改成：

```text
lead_subtype
```

原因：

`b2b_subtype` 只能表达 B2B 细分，无法表达 B2C 大团、私人定制、高预算客户。

建议字段：

```text
lead_type
lead_subtype
intent_level
lead_score
```

其中：

```text
lead_type = B2B / B2C / Unknown
```

```text
lead_subtype =
Agency
Operator
School
Corporate
Influencer
LargeGroup
PrivateCustom
LuxuryHighBudget
FIT
Other
Unknown
```

---

## 4. Input

评分模块接收的是 `CleanedLead`。

主要使用字段：

* `company_name`
* `message`
* `email`
* `source`

---

## 5. Output

评分模块返回 `LeadScoreResult`。

字段包括：

* `lead_type`
* `lead_subtype`
* `intent_level`
* `lead_score`

---

## 6. Scoring Dimensions

总分为 100 分。

| 维度     |   分值 |
| ------ | ---: |
| 客户类型匹配 | 0–30 |
| 意向强度   | 0–30 |
| 订单价值潜力 | 0–25 |
| 信息完整度  | 0–15 |
| 总分     |  100 |

---

## 7. Lead Type and Subtype Detection

### 7.1 B2B Agency

关键词：

* `travel agency`
* `agency`

输出：

```text
lead_type = "B2B"
lead_subtype = "Agency"
```

客户类型匹配分：

```text
+30
```

---

### 7.2 B2B Operator

关键词：

* `tour operator`
* `operator`

输出：

```text
lead_type = "B2B"
lead_subtype = "Operator"
```

客户类型匹配分：

```text
+30
```

---

### 7.3 B2B School

关键词：

* `school`
* `university`
* `student group`

输出：

```text
lead_type = "B2B"
lead_subtype = "School"
```

客户类型匹配分：

```text
+25
```

注意：

单独的 `student` 不直接判断为 `School`。

原因：

单个 student 可能只是个人游客，不一定代表学校团、研学团或机构客户。

---

### 7.4 B2B Corporate

关键词：

* `corporate`
* `business trip`
* `company retreat`
* `incentive trip`
* `MICE`
* `meeting`
* `conference`

输出：

```text
lead_type = "B2B"
lead_subtype = "Corporate"
```

客户类型匹配分：

```text
+25
```

注意：

`company` 不单独作为 Corporate 判断依据。

原因：

`company` 太泛，容易把普通个人咨询误判成企业客户。

---

### 7.5 B2B Influencer

关键词：

* `influencer`
* `blogger`
* `creator`
* `instagram`
* `youtube`
* `tiktok`
* `media kit`
* `collaboration`

输出：

```text
lead_type = "B2B"
lead_subtype = "Influencer"
```

客户类型匹配分：

```text
+25
```

---

### 7.6 B2C Large Group

关键词或信号：

* `group`
* `large group`
* `family group`
* `friends group`
* `10 people`
* `15 people`
* `20 people`
* `30 people`
* `pax`
* `people`

输出：

```text
lead_type = "B2C"
lead_subtype = "LargeGroup"
```

客户类型匹配分：

```text
+30
```

说明：

大团 B2C lead 可能具有很高成交价值，不应该归为 `Unknown`。

---

### 7.7 B2C Private Custom

关键词：

* `private tour`
* `custom tour`
* `custom itinerary`
* `tailor-made`
* `personalized itinerary`
* `bespoke`
* `private guide`
* `private driver`

输出：

```text
lead_type = "B2C"
lead_subtype = "PrivateCustom"
```

客户类型匹配分：

```text
+25
```

---

### 7.8 B2C Luxury / High Budget

关键词：

* `luxury`
* `high-end`
* `premium`
* `5-star`
* `boutique hotel`
* `high budget`
* `comfortable hotel`
* `private experience`

输出：

```text
lead_type = "B2C"
lead_subtype = "LuxuryHighBudget"
```

客户类型匹配分：

```text
+25
```

---

### 7.9 B2C FIT

关键词或信号：

* `solo`
* `couple`
* `family`
* `my wife`
* `my husband`
* `my parents`
* `with my family`
* `independent traveler`

输出：

```text
lead_type = "B2C"
lead_subtype = "FIT"
```

客户类型匹配分：

```text
+10
```

说明：

FIT 不一定低价值，但在当前销售优先级里，通常低于明确大团、私人定制和高预算客户。

---

### 7.10 Unknown

如果没有明确 B2B 或 B2C 信号，输出：

```text
lead_type = "Unknown"
lead_subtype = "Unknown"
```

客户类型匹配分：

```text
+0
```

---

## 8. Detection Priority

判断顺序如下：

```text
Agency
→ Operator
→ School
→ Corporate
→ Influencer
→ LargeGroup
→ PrivateCustom
→ LuxuryHighBudget
→ FIT
→ Unknown
```

说明：

B2B travel trade 优先识别，因为它们可能带来持续合作。

B2C 中，大团、私人定制、高预算客户优先级高于普通 FIT。

---

## 9. Intent Strength Score: 0–30 points

### High Intent: +30

关键词：

* `quotation`
* `quote`
* `book`
* `booking`
* `reserve`
* `partnership`
* `cooperate`
* `collaboration`
* `plan`
* `planning`
* `interested`
* `want to arrange`
* `ready to book`

---

### Medium Intent: +18

关键词：

* `ask`
* `question`
* `information`
* `details`
* `learn more`
* `available`
* `possible`
* `can you`
* `could you`

---

### Low Intent: +5

没有明确意向关键词，但仍然主动留下 lead。

---

## 10. Order Value Potential Score: 0–25 points

订单价值潜力用于判断这条 lead 可能带来的商业价值。

### High Value: +25

信号：

* 明确人数大于等于 6 人
* `large group`
* `private tour`
* `custom itinerary`
* `luxury`
* `high-end`
* `premium`
* `long-term`
* `partnership`
* `multi-day`
* `15 days`
* `two weeks`
* `budget`
* `5-star`

---

### Medium Value: +15

信号：

* `family`
* `couple`
* `small group`
* `private guide`
* `private driver`
* `custom tour`
* `itinerary`

---

### Low Value: +5

没有明显订单价值信号。

---

## 11. Information Completeness Score: 0–15 points

| 信号                      | 分数 |
| ----------------------- | -: |
| `company_name` 不为空      | +3 |
| `message` 长度大于等于 30 个字符 | +4 |
| 包含人数信息                  | +3 |
| 包含日期或月份                 | +3 |
| 包含目的地、预算或行程信息           | +2 |

最高不超过：

```text
15
```

具体关键词包括：

* `people`
* `pax`
* `group`
* `date`
* `budget`
* `destination`
* `itinerary`
* `private tour`
* `custom tour`
* `september`
* `october`
* `november`
* `december`
* `january`
* `february`
* `march`
* `april`
* `may`
* `june`
* `july`
* `august`

---

## 12. Final Score Calculation

最终分数：

```text
lead_score =
customer_type_score
+ intent_strength_score
+ order_value_potential_score
+ information_completeness_score
```

最高分限制：

```text
100
```

如果超过 100，最终仍然为 100。

---

## 13. Intent Level Mapping

| 最终分数   | `intent_level` |
| ------ | -------------- |
| 75–100 | `High`         |
| 45–74  | `Medium`       |
| 0–44   | `Low`          |

---

## 14. Example Cases

### Example 1: B2B Agency Lead

```text
company_name: Spain Travel Agency
message: We want a quotation for a 20-person private China tour in September.
```

Expected:

```text
lead_type = "B2B"
lead_subtype = "Agency"
intent_level = "High"
lead_score = High range
```

原因：

* `travel agency` 命中 Agency
* `quotation` 命中高意向
* `20-person`、`private tour`、`September` 提供高价值订单信号

---

### Example 2: B2C Large Group Lead

```text
company_name:
message: We are a family group of 12 people planning a private tour in China next October.
```

Expected:

```text
lead_type = "B2C"
lead_subtype = "LargeGroup"
intent_level = "High"
lead_score = High range
```

原因：

* `12 people` / `group` 命中 LargeGroup
* `planning` 命中高意向
* `private tour`、`China`、`October` 提供具体计划信息

---

### Example 3: B2C Private Custom Lead

```text
company_name:
message: My wife and I are looking for a private custom itinerary in western China with a private guide.
```

Expected:

```text
lead_type = "B2C"
lead_subtype = "PrivateCustom"
intent_level = "Medium" or "High"
lead_score = Medium to High range
```

原因：

* `private custom itinerary` 命中 PrivateCustom
* `private guide` 提供订单价值信号
* 虽然人数少，但定制需求明确

---

### Example 4: B2C Luxury Lead

```text
company_name:
message: We want a luxury private tour with boutique hotels and premium experiences.
```

Expected:

```text
lead_type = "B2C"
lead_subtype = "LuxuryHighBudget"
intent_level = "High"
lead_score = High range
```

原因：

* `luxury`、`boutique hotels`、`premium experiences` 命中高预算信号
* `private tour` 提供订单价值信号

---

### Example 5: Weak FIT Lead

```text
company_name:
message: I want to travel with my family.
```

Expected:

```text
lead_type = "B2C"
lead_subtype = "FIT"
intent_level = "Low" or "Medium"
lead_score = Low to Medium range
```

原因：

* 有 B2C 个人旅行信号
* 但缺少人数、日期、预算、目的地和明确订单信息

---

## 15. Current MVP Limitations

当前规则仍然是 MVP 版本，有以下限制：

* 仍然依赖关键词匹配
* 无法理解复杂语境
* 无法处理否定表达
* 对非英文 message 支持有限
* 无法准确识别所有人数表达
* 无法判断真实预算能力
* 无法生成摘要、推荐动作和邮件草稿
* 无法替代 LLM 的复杂语义判断

这些限制将在下一阶段通过 LLM analysis 优化。

---

## 16. Design Principle

当前规则评分必须满足：

* 稳定：同一条 lead 每次评分结果一致
* 可解释：可以说明为什么加分
* 可测试：每条关键规则都能写 pytest
* 低成本：不依赖 LLM API
* 可兜底：LLM 失败时仍然可以输出基础评分
* 可扩展：后续可以接入 LLM 语义分析

---

## 17. Implementation Order

当前实现顺序：

```text
1. 修改 LeadScoreResult schema：b2b_subtype → lead_subtype
2. detect_lead_subtype()
3. calculate_customer_type_score()
4. calculate_intent_score()
5. calculate_order_value_score()
6. calculate_information_completeness_score()
7. map_score_to_intent_level()
8. score_lead()
9. tests/test_scoring.py
```

---

## 18. Interview Explanation

面试时可以这样解释：

我最开始的规则评分只重点识别 B2B lead，但后来发现这对旅游业务不够准确，因为 B2C 中的大团、私人定制、高预算家庭团也可能有很高商业价值。

所以我把评分逻辑从简单的 B2B 优先，改成客户商业价值导向。

新版评分分成四个维度：客户类型匹配、意向强度、订单价值潜力和信息完整度。

这样既能识别 B2B travel trade，也能识别高价值 B2C lead，比如大团、私人定制和高预算客户。

当 LLM 可用时，系统优先使用 LLM 做复杂语义判断；当 LLM 不可用时，这套规则评分作为 fallback，保证系统仍然可以稳定运行。

```

我的建议很明确：**现在应该改 schema**。
你现在还没接 FastAPI，还没接数据库，改字段成本最低。等你后面接了 Notion / PostgreSQL 再改，会麻烦很多。
```

