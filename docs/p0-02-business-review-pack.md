# P0-02 新增业务案例复核包

协议 `p0-02.v1`；案例 `p0-02-cases.v1`。生成日期：2026-10-05。当前 24 个场景均为 `draft`，审核依据均为空；用户授权开发并不等于已确认这些新增业务标签。

本包供逐条确认问题含义、答案范围、支持资料与不回答原因。P0-01 的 22 例认可不自动延伸到本包。所有资料均为合成测试资料，不能用作真实销售报价或政策。正式接纳还需审阅实际执行报告及允许人工裁定的输出；确认案例不等于接受缺陷或认可模型准确率。

## 数据与口径

- 24 个场景：18 个单轮、6 个三轮，共 36 轮；主要中文 10、英文 10、混合语言 4。
- 18 个单轮中三态各 6 个；三条独立检索路径共 54 个单元，仅归入 rule_only。
- 两种回复模式各计划 36 轮，共 72 轮观察。mocked_model 是受控返回值，不是实际模型质量。
- 7 个独立合成知识快照；可答/部分可答每轮为快照全部片段显式标注相关性等级。无答案允许空判断，但不能靠漏检索证明库中无答案。
- 只有 required=true 的要点影响三态和强制召回分母；回复额外增加的实质声明仍需有依据。
- 证据区间为 Unicode 字符位置 `[start,end)`，散列为整段 text 的 UTF-8 SHA-256。有效期端点均包含；evaluation_time 使用所记录时间的日期，business_date 使用客户业务日期。
- 所有当轮客户事实与来源仅可指向截至当轮可见消息。已生成的错误说法不构成供应或业务动作证明。

数据文件：[cases.json](../data/answerability_eval/cases.json)、[knowledge.json](../data/answerability_eval/knowledge.json)。实现方案：[P0-02 详细计划](p0-02-answerability-design.md)。

| 文件 | 当前 SHA-256 |
| --- | --- |
| cases.json | `92db2b86a7af275f6a9aeddc8ae2378f6713ff2f02e56bfc086931ab8ac6928a` |
| knowledge.json | `48a0c8923ac185fcabd7881d2338910fbde31e54be15c881b1e6df66c1748398` |

审核建议记录每例的审核人、带时区的时间、理由和原始授权记录链接；仍有争议的案例保持 draft，不由工程师自行改为 reviewed。修改金标、支持组合或口径后需保存新版本并重测。

## 逐场景与逐轮标签

### AB01 · zh · 快照 `core` · 待审核

**T1：云南亲子游包含昆明机场接送吗？**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `transfer`：说明昆明机场与市区酒店接送范围；可答，支持充分。支持：`transfer`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.

### AB02 · zh · 快照 `core` · 待审核

**T1：云南亲子游包含国际机票和个人旅行保险吗？**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `exclusions`：明确机票和保险不包含；可答，支持充分。支持：`exclusions`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.

### AB03 · en · 快照 `core` · 待审核

**T1：When are the deposit and balance payable for the Yunnan family tour, and what must be confirmed first?**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `payment`：保留书面行程报价确认前提和30%/14天条款；可答，支持充分。支持：`payment`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.

### AB04 · mixed · 快照 `core` · 待审核

**T1：请用中文说明接送范围；does the same transfer rule apply in English?**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `transfer`：说明昆明机场与市区酒店接送范围；可答，支持充分。支持：`transfer`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.

### AB05 · zh · 快照 `core` · 待审核

**T1：云南亲子游一般安排几天、经过哪些城市？**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `itinerary`：说明云南路线与7天6晚；可答，支持充分。支持：`itinerary`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.

### AB06 · en · 快照 `core` · 待审核

**T1：Are confirmed Yunnan family groups eligible for the accompanying guide, and what are the daily service hours?**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `guide_scope`：组合回答适用团队与导游工作时段；可答，支持充分。支持：`guide_eligibility + guide_hours`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.

### AB07 · zh · 快照 `core` · 待审核

**T1：云南私人定制游按什么原则定价？请告诉我儿童的具体价格。**

期望：部分必答要点可答；动作 `partial`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `pricing_basis`：说明影响报价因素；可答，支持充分。支持：`quote`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.
- `child_price`：儿童具体金额；不可答，缺静态答案。支持：`无可用直接支持组`。
  依据说明：完整冻结快照没有该具体答案，相关主题介绍不能补足答案。

### AB08 · zh · 快照 `core` · 待审核

**T1：介绍一下云南行程，2026年10月10日还有酒店余位吗？**

期望：部分必答要点可答；动作 `partial`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `2026-10-10`。

截至本轮明确的客户信息：`departure_date=2026-10-10` 来源 T1。

- `itinerary`：说明云南路线与7天6晚；可答，支持充分。支持：`itinerary`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.
- `availability`：指定日期余位或实际预订状态；不可答，需要供应/操作状态。支持：`无可用直接支持组`。
  依据说明：现有资料和截至本轮客户消息没有权威供应状态或已执行预订结果。

### AB09 · en · 快照 `conditional` · 待审核

**T1：What airport transfers are included, and am I eligible for the October workshop? I have not chosen a departure date.**

期望：部分必答要点可答；动作 `partial`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `transfer`：说明昆明机场与市区酒店接送范围；可答，支持充分。支持：`transfer`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.
- `workshop_eligibility`：客户日期是否满足10月手工体验规则；不可答，缺客户信息。支持：`无可用直接支持组`。
  依据说明：完整快照规则存在，但截至本轮客户未提供所列适用字段。
- 必需追问：departure_date。

### AB10 · zh · 快照 `expired` · 待审核

**T1：云南包含什么接送？这份9月促销价99元现在仍有效吗？**

期望：部分必答要点可答；动作 `partial`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `transfer`：说明昆明机场与市区酒店接送范围；可答，支持充分。支持：`transfer`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.
- `current_price`：已过期促销不能作为现在价格；不可答，明确过期。支持：`无可用直接支持组`。
  依据说明：所引用促销具有明确截止日期，评测时间已超过该日期。

### AB11 · zh · 快照 `conflict` · 待审核

**T1：云南包含接送吗？提前7天取消到底能不能退定金？**

期望：部分必答要点可答；动作 `partial`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `transfer`：说明昆明机场与市区酒店接送范围；可答，支持充分。支持：`transfer`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.
- `cancellation`：同范围取消政策冲突；不可答，证据冲突。支持：`无可用直接支持组`。
  依据说明：两个同范围、同时有效的明确值冲突，未提供解决记录。

### AB12 · mixed · 快照 `core` · 待审核

**T1：云南路线包括哪些城市？What is the exact child room price?**

期望：部分必答要点可答；动作 `partial`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `itinerary`：说明云南路线与7天6晚；可答，支持充分。支持：`itinerary`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.
- `child_price`：儿童房价具体数额；不可答，缺静态答案。支持：`无可用直接支持组`。
  依据说明：完整冻结快照没有该具体答案，相关主题介绍不能补足答案。

### AB13 · zh · 快照 `unrelated` · 待审核

**T1：请介绍你们的北极探险邮轮产品和售价。**

期望：全部必答要点不可答；动作 `clarify`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `arctic_cruise`：北极邮轮产品和金额；不可答，缺静态答案。支持：`无可用直接支持组`。
  依据说明：完整冻结快照没有该具体答案，相关主题介绍不能补足答案。

### AB14 · en · 快照 `hotel` · 待审核

**T1：What is the exact child room price for the hotel described in the Yunnan guide?**

期望：全部必答要点不可答；动作 `clarify`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `child_price`：具体儿童房价缺失；不可答，缺静态答案。支持：`无可用直接支持组`。
  依据说明：完整冻结快照没有该具体答案，相关主题介绍不能补足答案。

### AB15 · en · 快照 `conflict` · 待审核

**T1：Can I get the deposit refunded if I cancel the Yunnan family tour seven days before departure?**

期望：全部必答要点不可答；动作 `clarify`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `cancellation`：未解决的同适用范围退款冲突；不可答，证据冲突。支持：`无可用直接支持组`。
  依据说明：两个同范围、同时有效的明确值冲突，未提供解决记录。

### AB16 · en · 快照 `expired` · 待审核

**T1：Is the September CNY 99 workshop promotion still the current price today?**

期望：全部必答要点不可答；动作 `clarify`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `current_price`：9月促销已过期；不可答，明确过期。支持：`无可用直接支持组`。
  依据说明：所引用促销具有明确截止日期，评测时间已超过该日期。

### AB17 · en · 快照 `unverified` · 待审核

**T1：Is the undated CNY 88 workshop promotion still valid today?**

期望：全部必答要点不可答；动作 `clarify`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `validity`：没有促销有效期，不能确认现行；不可答，有效性无法验证。支持：`无可用直接支持组`。
  依据说明：此时效敏感资料没有有效期，不能声称现行，也不能声称已确定过期。

### AB18 · en · 快照 `hotel` · 待审核

**T1：Please confirm that my hotel room for 10 October 2026 has been booked and is available.**

期望：全部必答要点不可答；动作 `clarify`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `2026-10-10`。

截至本轮明确的客户信息：`departure_date=2026-10-10` 来源 T1。

- `availability`：指定日期余位或实际预订状态；不可答，需要供应/操作状态。支持：`无可用直接支持组`。
  依据说明：现有资料和截至本轮客户消息没有权威供应状态或已执行预订结果。

### AB19 · zh · 快照 `conditional` · 待审核

**T1：我符合云南10月免费手工体验规则吗？日期还没确定。**

期望：全部必答要点不可答；动作 `clarify`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `workshop_eligibility`：客户日期是否满足10月手工体验规则；不可答，缺客户信息。支持：`无可用直接支持组`。
  依据说明：完整快照规则存在，但截至本轮客户未提供所列适用字段。
- 必需追问：departure_date。

**T2：我的出发日期是2026年10月10日，现在符合手工体验规则吗？**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:01:00+00:00`；业务日期 `2026-10-10`。

截至本轮明确的客户信息：`departure_date=2026-10-10` 来源 T2。

- `workshop_eligibility`：客户10月出发适用免费手工体验；可答，支持充分。支持：`date_policy`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.
- 不应重复追问：departure_date。

**T3：就是这个日期，酒店还有余位吗？**

期望：全部必答要点不可答；动作 `clarify`。评测时点 `2026-10-05T10:02:00+00:00`；业务日期 `2026-10-10`。

截至本轮明确的客户信息：`departure_date=2026-10-10` 来源 T2。

- `availability`：指定日期余位或实际预订状态；不可答，需要供应/操作状态。支持：`无可用直接支持组`。
  依据说明：现有资料和截至本轮客户消息没有权威供应状态或已执行预订结果。
- 不应重复追问：departure_date。

### AB20 · en · 快照 `core` · 待审核

**T1：Are Kunming Airport transfers included?**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `transfer`：说明昆明机场与市区酒店接送范围；可答，支持充分。支持：`transfer`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.

**T2：Can you confirm hotel availability for 10 October 2026?**

期望：全部必答要点不可答；动作 `clarify`。评测时点 `2026-10-05T10:01:00+00:00`；业务日期 `2026-10-10`。

截至本轮明确的客户信息：`departure_date=2026-10-10` 来源 T2。

- `availability`：指定日期余位或实际预订状态；不可答，需要供应/操作状态。支持：`无可用直接支持组`。
  依据说明：现有资料和截至本轮客户消息没有权威供应状态或已执行预订结果。

**T3：Leave availability for later. Please remind me of the airport transfer coverage.**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:02:00+00:00`；业务日期 `2026-10-10`。

截至本轮明确的客户信息：`departure_date=2026-10-10` 来源 T2。

- `transfer`：说明昆明机场与市区酒店接送范围；可答，支持充分。支持：`transfer`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.

### AB21 · en · 快照 `core` · 待审核

本例提供“询问预订→明确尚无供应确认→继续咨询”的真实消息。实际首次回复是否产生错误承诺以运行结果为准；不预先宣称缺陷必现。强制“第一轮错误、之后正确”的验证使用独立工具自测，不冒充本例业务观测。

**T1：Can you confirm that my Yunnan hotel booking is completed?**

期望：全部必答要点不可答；动作 `clarify`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `availability`：指定日期余位或实际预订状态；不可答，需要供应/操作状态。支持：`无可用直接支持组`。
  依据说明：现有资料和截至本轮客户消息没有权威供应状态或已执行预订结果。

**T2：Please do not treat any earlier wording as booking proof. No supplier has confirmed a booking. Is it really confirmed?**

期望：全部必答要点不可答；动作 `clarify`。评测时点 `2026-10-05T10:01:00+00:00`；业务日期 `尚未提供/不适用`。

- `availability`：指定日期余位或实际预订状态；不可答，需要供应/操作状态。支持：`无可用直接支持组`。
  依据说明：现有资料和截至本轮客户消息没有权威供应状态或已执行预订结果。

**T3：While that is checked, which airport transfers does the itinerary include?**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:02:00+00:00`；业务日期 `尚未提供/不适用`。

- `transfer`：说明昆明机场与市区酒店接送范围；可答，支持充分。支持：`transfer`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.

### AB22 · mixed · 快照 `core` · 待审核

**T1：我们8个人想去云南。Please explain the airport transfers.**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

截至本轮明确的客户信息：`group_size=8` 来源 T1。

- `transfer`：说明昆明机场与市区酒店接送范围；可答，支持充分。支持：`transfer`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.
- 必查事实：group_size=8，来源 T1，状态需 customer_confirmed 或 human_confirmed。

**T2：更正一下，不是8个人，是9个人。Does this change the known pricing principles?**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:01:00+00:00`；业务日期 `尚未提供/不适用`。

截至本轮明确的客户信息：`group_size=9` 来源 T2。

- `pricing_basis`：说明人数是价格变量，不编具体金额；可答，支持充分。支持：`quote`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.
- 必查事实：group_size=9，来源 T2，状态需 customer_confirmed 或 human_confirmed。
- 不应重复追问：group_size。

**T3：按照刚才更正的人数，which transfers are included?**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:02:00+00:00`；业务日期 `尚未提供/不适用`。

截至本轮明确的客户信息：`group_size=9` 来源 T2。

- `transfer`：说明昆明机场与市区酒店接送范围；可答，支持充分。支持：`transfer`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.
- 必查事实：group_size=9，来源 T2，状态需 customer_confirmed 或 human_confirmed。
- 不应重复追问：group_size。

### AB23 · zh · 快照 `conditional` · 待审核

**T1：我们在2026年10月10日出发，云南包括什么机场接送？**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `2026-10-10`。

截至本轮明确的客户信息：`departure_date=2026-10-10` 来源 T1。

- `transfer`：说明昆明机场与市区酒店接送范围；可答，支持充分。支持：`transfer`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.

**T2：刚才这个出发日期能参加免费手工体验吗？**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:01:00+00:00`；业务日期 `2026-10-10`。

截至本轮明确的客户信息：`departure_date=2026-10-10` 来源 T1。

- `workshop_eligibility`：客户10月出发适用免费手工体验；可答，支持充分。支持：`date_policy`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.
- 不应重复追问：departure_date。

**T3：请确认这项免费活动的日期适用范围。**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:02:00+00:00`；业务日期 `2026-10-10`。

截至本轮明确的客户信息：`departure_date=2026-10-10` 来源 T1。

- `workshop_eligibility`：客户10月出发适用免费手工体验；可答，支持充分。支持：`date_policy`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.
- 不应重复追问：departure_date。

### AB24 · mixed · 快照 `core` · 待审核

**T1：请介绍云南亲子游的路线和时长。**

期望：全部必答要点可答；动作 `answer`。评测时点 `2026-10-05T10:00:00+00:00`；业务日期 `尚未提供/不适用`。

- `itinerary`：说明云南路线与7天6晚；可答，支持充分。支持：`itinerary`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.

**T2：We also need the exact child hotel price. What transfer services are already included?**

期望：部分必答要点可答；动作 `partial`。评测时点 `2026-10-05T10:01:00+00:00`；业务日期 `尚未提供/不适用`。

- `transfer`：说明昆明机场与市区酒店接送范围；可答，支持充分。支持：`transfer`。
  依据说明：指定适用证据明确支持此要点；须保留原文条件。 The declared applicable evidence supports this facet with its conditions.
- `child_price`：儿童房价未知；不可答，缺静态答案。支持：`无可用直接支持组`。
  依据说明：完整冻结快照没有该具体答案，相关主题介绍不能补足答案。

**T3：接送范围清楚了。Please arrange verification of the child price and hotel availability; do not claim either is confirmed.**

期望：全部必答要点不可答；动作 `clarify`。评测时点 `2026-10-05T10:02:00+00:00`；业务日期 `尚未提供/不适用`。

- `child_price`：具体儿童房价未知；不可答，缺静态答案。支持：`无可用直接支持组`。
  依据说明：完整冻结快照没有该具体答案，相关主题介绍不能补足答案。
- `availability`：指定日期余位或实际预订状态；不可答，需要供应/操作状态。支持：`无可用直接支持组`。
  依据说明：现有资料和截至本轮客户消息没有权威供应状态或已执行预订结果。

## 合成知识原文与适用元数据

冲突标识仅用于本评测包对照两个同范围矛盾值，不表示生产系统已有供应或政策治理。`last_edited_time` 不用作过期依据。

### 快照 `core`

完整评测专用快照；仅用于合成回归验证，待业务逐条审核。 Complete synthetic snapshot; business review remains pending.

- `transfer` / Airport Transfers：云南亲子游包含昆明机场与市区酒店之间的抵达和离开接送。其他城市接送需另行确认。 Yunnan family tours include arrival and departure transfers between Kunming Airport and city hotels. Transfers in other cities require confirmation.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `348399f764a03f6d42234c07488a6eda07acbf0f3347a470ce536422341f726e`。
- `exclusions` / Exclusions：云南亲子游不包含国际机票和个人旅行保险，旅客需自行安排。 International flights and personal travel insurance are not included in the Yunnan family tour. Travelers arrange these separately.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `5fef15865a301eb10c6b9772c4620ea03799c308c590a6b4628a867383c07e93`。
- `payment` / Payment Conditions：书面行程和明细报价双方确认后，支付总价30%的定金；余款在抵达前14天支付。 A 30% deposit is due after both parties confirm the written itinerary and itemized quotation. The balance is due 14 days before arrival.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `e0071fc32db88aea79038eb7f5b8b375217b2a3777df1fd8f15237012565d1ab`。
- `itinerary` / Itinerary：云南亲子游标准行程为7天6晚，路线是昆明—大理—丽江—香格里拉。 The standard Yunnan family itinerary lasts 7 days and 6 nights: Kunming, Dali, Lijiang and Shangri-La.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `0ed2b72ac861700399af25fe09aa41a79171b7d784898129ad01934b719fbf2a`。
- `quote` / Pricing Variables：私人定制游价格取决于人数、旅行日期、酒店等级和车辆要求。此资料不提供具体金额，也不证明任何日期的余位。 Private tour pricing depends on group size, travel dates, hotel category and vehicle requirements. This guide provides no exact amount or date-specific availability.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `29fd4b721a2f441017cffee9f13559be525da8b384c2f414aef8b6cca234cc3d`。
- `guide_eligibility` / Guide Eligibility：云南亲子游的已确认亲子团队可以使用本产品的随团导游服务。下一节规定该服务的工作时段。 Confirmed family groups on the Yunnan family product may use its accompanying guide service. The service hours are specified separately.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `11ee7f94b7a6fb7d9c7ff2a7166423b6372eedcc658ab8951c468617bdc3e220`。
- `guide_hours` / Guide Service Hours：本产品随团导游的服务时间为每日09:00至17:00；此处不单独说明哪些客人适用。 This product offers accompanying guide service from 09:00 to 17:00 daily; eligibility is specified separately.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `75599287f2107a36b9dbe917f3daefbe059e48753463a6ee1cad2fe2d5bc49aa`。
- `hotel_intro` / Hotel Introduction：本产品可选择昆明市区亲子酒店。酒店介绍仅供行程规划；资料没有儿童房价、指定日期房态或预订凭证。 Family-friendly hotels in central Kunming are possible itinerary options. This description contains no child room price, date-specific availability or booking confirmation.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `c27da1b73c2504f53febfa9aa626645adffb63629b924c054af899a9691f25a5`。

### 快照 `conditional`

完整评测专用快照；仅用于合成回归验证，待业务逐条审核。 Complete synthetic snapshot; business review remains pending.

- `transfer` / Airport Transfers：云南亲子游包含昆明机场与市区酒店之间的抵达和离开接送。其他城市接送需另行确认。 Yunnan family tours include arrival and departure transfers between Kunming Airport and city hotels. Transfers in other cities require confirmation.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `348399f764a03f6d42234c07488a6eda07acbf0f3347a470ce536422341f726e`。
- `date_policy` / October Workshop：出发日期在2026年10月1日至31日的云南亲子游可参加一次免费手工体验；是否适用取决于客户出发日期。 One complimentary craft workshop is included for Yunnan family trips departing from 1 to 31 October 2026. Eligibility depends on the customer departure date.
  有效期：2026-10-01 至 2026-10-31；日期依据 `business_date`。文本散列 `4c135a3b943d666369730f49091c6aac96b248acae025e73df0402695b990206`。
- `hotel_intro` / Hotel Introduction：本产品可选择昆明市区亲子酒店。酒店介绍仅供行程规划；资料没有儿童房价、指定日期房态或预订凭证。 Family-friendly hotels in central Kunming are possible itinerary options. This description contains no child room price, date-specific availability or booking confirmation.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `c27da1b73c2504f53febfa9aa626645adffb63629b924c054af899a9691f25a5`。

### 快照 `expired`

完整评测专用快照；仅用于合成回归验证，待业务逐条审核。 Complete synthetic snapshot; business review remains pending.

- `transfer` / Airport Transfers：云南亲子游包含昆明机场与市区酒店之间的抵达和离开接送。其他城市接送需另行确认。 Yunnan family tours include arrival and departure transfers between Kunming Airport and city hotels. Transfers in other cities require confirmation.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `348399f764a03f6d42234c07488a6eda07acbf0f3347a470ce536422341f726e`。
- `expired_price` / Historical Promotion：2026年9月限时手工体验促销价为每人99元，仅适用于该月，现有文本不能代表后续报价。 The workshop promotion was CNY 99 per person in September 2026 only. This historical text is not a quotation for later dates.
  有效期：2026-09-01 至 2026-09-30；日期依据 `evaluation_time`。文本散列 `187be66c714cbb9672374a107189fb98a13f7f22ed090643adf5170576a867a9`。

### 快照 `conflict`

完整评测专用快照；仅用于合成回归验证，待业务逐条审核。 Complete synthetic snapshot; business review remains pending.

- `transfer` / Airport Transfers：云南亲子游包含昆明机场与市区酒店之间的抵达和离开接送。其他城市接送需另行确认。 Yunnan family tours include arrival and departure transfers between Kunming Airport and city hotels. Transfers in other cities require confirmation.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `348399f764a03f6d42234c07488a6eda07acbf0f3347a470ce536422341f726e`。
- `cancel_a` / Cancellation A：云南亲子游在出发前7天取消可全额退款；与另一份同范围有效政策尚未解决冲突。 Yunnan family trips cancelled 7 days before departure receive a full refund; an equally applicable conflicting policy remains unresolved.
  有效期：2026-10-01 至 2026-10-31；日期依据 `evaluation_time`。文本散列 `bcab72c8a814da7bd136cf625327a105241f18a803c686c83b6aa518ee9445ef`。
  同范围冲突键 `yunnan_cancel_seven_days`，值 `full_refund`。
- `cancel_b` / Cancellation B：云南亲子游在出发前7天取消定金不退；与另一份同范围有效政策尚未解决冲突。 Deposits for Yunnan family trips cancelled 7 days before departure are non-refundable; an equally applicable conflicting policy remains unresolved.
  有效期：2026-10-01 至 2026-10-31；日期依据 `evaluation_time`。文本散列 `dc472a3fbbb3676cfba58204e558429e086bd97be5294be8c752118a7002989b`。
  同范围冲突键 `yunnan_cancel_seven_days`，值 `deposit_nonrefundable`。

### 快照 `unverified`

完整评测专用快照；仅用于合成回归验证，待业务逐条审核。 Complete synthetic snapshot; business review remains pending.

- `unverified_price` / Undated Promotion：页面写有手工体验促销价每人88元，但没有生效日期、结束日期或仍在执行的证明。 The page lists a workshop promotion of CNY 88 per person, without effective dates or proof that the promotion is still valid.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `44be668323283336cfbd757fe543816571dcb1f2908716516856d4dfc79ad886`。

### 快照 `unrelated`

完整评测专用快照；仅用于合成回归验证，待业务逐条审核。 Complete synthetic snapshot; business review remains pending.

- `unrelated` / Local Plants：这份资料介绍云南当地常见植物，列举茶树和杜鹃花。 This document describes plants commonly found in Yunnan, including tea plants and rhododendrons.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `b35fc950ddc63441db2652022b5e40c1fc3c14173da23bc3cacd905e77015c3f`。

### 快照 `hotel`

完整评测专用快照；仅用于合成回归验证，待业务逐条审核。 Complete synthetic snapshot; business review remains pending.

- `hotel_intro` / Hotel Introduction：本产品可选择昆明市区亲子酒店。酒店介绍仅供行程规划；资料没有儿童房价、指定日期房态或预订凭证。 Family-friendly hotels in central Kunming are possible itinerary options. This description contains no child room price, date-specific availability or booking confirmation.
  有效期：未提供 至 未提供；日期依据 `evaluation_time`。文本散列 `c27da1b73c2504f53febfa9aa626645adffb63629b924c054af899a9691f25a5`。

## 当前未完成事项

新增标签尚未取得业务确认；真实模型未运行；双角色实际输出复核、缺陷接纳和正式基线仍由各自证据决定。本包不把 draft、未测、待复核或已知失败写成通过。
