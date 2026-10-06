# P0-02 v2 业务案例复核包

日期：2026-10-06。状态：24 个候选场景均为 **draft（待业务确认）**；没有添加审核人、审核时间或通过记录。

本包用于审核“客户问题和预期回答是否符合当前虚构产品手册”。它不代表具体系统输出已经通过人工审核，也不表示真实旅行产品、真实客户或真实模型质量已经验证。实际回复及自动发现的问题由运行报告另行记录，不能用这里的预期答案代替。

依据：[已批准的调整计划](p0-02-handbook-alignment-plan.md)。数据版本为 `p0-02.v2`，原 v1 案例、知识和配置保留原路径原字节。

## 两组分别怎么看

| 分组 | 场景/语言 | 每模式轮次 | 规则模式独立检索 | 轮次标签分布（预期，不是实测成功率） |
| --- | --- | --- | --- | --- |
| 原手册组 | 18例；中文8/英文6/混合4 | 28 | 39 | 全部可答12、部分可答7、全部不可答9 |
| 专项测试组 | 6例；中文2/英文4/混合0 | 8 | 15 | 全部可答3、部分可答2、全部不可答3 |

总计24场景、每模式36轮、两模式72轮。39＋15＝54个独立检索单元只归规则模式；模拟模式不重复计入。三态数量来自逐题判断，没有沿用旧版“每类必须6例”的限制。两组各有三态覆盖并分别统计，不合并成一个产品准确率。

原手册组的18例均使用同一份完整8页面、47片段，保留原文、原编号、产品范围、文档类型及顺序。问题由人工合成，资料来自原虚构手册；“原手册组”不意味着真实客户问题。专项6例只使用单独构造的资料，用来制造条件缺失、过期、冲突等边界；它们不写入产品知识，也不作为原产品已有政策。

## 需要特别核对的业务边界

- 原手册的“包含交通”不能推出包含昆明机场至市区酒店双程接送。
- 通用报价排除机票和旅行保险；不能悄悄缩小成只有国际机票，也不能追加“必须自行安排”或“保证代订”。
- 30%定金明确存在；“双方先确认书面行程和明细报价后才付款”不是原条款。
- 余款基准存在真实差异：报价/FAQ问答写抵达前14天，FAQ简答写出发前14天。AB11需同时保留原文，不能选一处作唯一截止日。
- 儿童优惠条件明确为12岁以下且与父母同住；具体金额没有写。问适用性时须区分客户信息未提供、条件已满足和金额仍未知。
- 私人团英语导游规则有原文，具体每日工时没有；云南自助出行也不能被自动当成私人导游团。
- 手工活动、99元/88元促销和7天取消的两条人为冲突政策，只属于专项设定。
- 酒店介绍、客户愿望和历史回复都不是指定日期的房态或预订凭证。

## 资料来源怎样核验

[来源清单](../data/answerability_eval/v2/source_manifest.json)绑定两个原始文件及47条完整来源映射：

- [原8页手册](../data/knowledge_snapshot/notion_pages.json)；[原47片段](../data/knowledge_snapshot/knowledge_chunks.json)。
- 文件级 `lf_normalized_file_hash` 只统一操作系统行尾后计算；`canonical_json_hash` 校验完整JSON结构。
- 每片段 `exact_chunk_text_hash` 校验原正文UTF-8，正文不做换行或语言改写；`production_record_hash` 校验全部生产字段。
- 每片段还绑定原页面编号、页面正文字符区间与原文；加载时逐项对照当前原文件，丢片段、改编号、改产品结构、错引用均会拒绝。
- 当前工作区原始字节散列另作诊断，不把Windows/Linux行尾差异说成字节相同。

来源清单的规范化内容指纹：`67713818acf1f2b647390e0c162c86f2ed482e5b670350586ad323852c64a7af`。该指纹是版本绑定，不是远端批准或业务审核。

## 逐例业务复核

以下“应该回答”和“不能承诺”都是待确认的预期要求。对于部分/全部不可答，目标是讲清已知内容与需核实内容，而不是简单拒绝全部问题。

### AB01 · 原手册组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：全部不可答**

实际测试输入：云南亲子私人团包含昆明机场到市区酒店的抵达和离开接送吗？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **昆明机场到市区酒店的具体接送范围：仍需核实。** 已核对全部47片段：原文只笼统包含交通，没有明确昆明机场接送的路线、抵离范围或费用。
  原因：完整资料没有所问答案。
  应说清楚：说明范围未明确，需核实接送安排。
  不能承诺：声称已包含昆明机场双程接送。
  原文依据：Private Tour Pricing Rules / Quotation Notes，[chunk_88e6a3c65309](../data/knowledge_snapshot/knowledge_chunks.json#L633)，正文字符[87, 171)：
  > included items (transport, guide, accommodation, listed meals, listed entrance fees)

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB02 · 原手册组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：全部可答**

实际测试输入：按私人团通用报价说明，机票和个人旅行保险是否包含？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **私人团通用报价中的机票和旅行保险排除项：可以回答。** 通用报价明确排除flights及travel insurance；没有区分只有国际机票，也未约定代订或自理义务。
  应说清楚：机票和旅行保险不包含在所述私人团通用报价内。
  不能承诺：把国内机票自动算进包含项；无依据承诺代订或强加自行安排义务。
  原文依据：Private Tour Pricing Rules / Quotation Notes，[chunk_88e6a3c65309](../data/knowledge_snapshot/knowledge_chunks.json#L633)，正文字符[176, 255)：
  > excluded items (flights, visa fees, tips, personal expenses, travel insurance).

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB03 · 原手册组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：全部可答**

实际测试输入：What deposit percentage confirms a private-tour booking, and which payment methods are accepted?

中文理解：确认私人团预订需支付多少比例的定金？接受哪些支付方式？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **确认预订的定金比例：可以回答。** 两处原文一致写30%定金用于确认预订；没有新增的双方确认书面行程和明细报价这一付款前提。
  应说清楚：30%定金确认预订。
  不能承诺：必须先双方确认书面行程和明细报价才付款。
  原文依据：Private Tour Pricing Rules / Quotation Notes，[chunk_88e6a3c65309](../data/knowledge_snapshot/knowledge_chunks.json#L633)，正文字符[371, 420)：
  > Deposit: 30% deposit required to confirm booking.
  原文依据：Travel Permit and Payment FAQ / Common Questions，[chunk_7eca38e94502](../data/knowledge_snapshot/knowledge_chunks.json#L648)，正文字符[604, 637)：
  > 30% deposit confirms the booking.

- **支付方式及明确写出的附加费：可以回答。** FAQ列明银行转账、PayPal及4%附加费、支付宝；大多数币种可通过Stripe处理信用卡支付。
  应说清楚：银行转账、PayPal（4%附加费）、支付宝；大多数币种的信用卡通过Stripe处理。
  不能承诺：编造其他手续费或保证所有币种均可使用。
  原文依据：Travel Permit and Payment FAQ / Common Questions，[chunk_7eca38e94502](../data/knowledge_snapshot/knowledge_chunks.json#L648)，正文字符[419, 550)：
  > We accept bank wire transfer, PayPal (4% surcharge), and Alipay. Credit card payments processed through Stripe for most currencies.

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB04 · 原手册组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：全部可答**

实际测试输入：请用中文说明云南经典线路；does the English handbook describe the same cities and duration?

中文理解：请说明云南经典线路，英文手册是否对应相同的城市和时长？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **云南经典线路的天数与城市顺序：可以回答。** 原云南产品手册直接列出7天6晚及昆明、大理、丽江、香格里拉；无需补造路线。
  应说清楚：7天6晚，昆明—大理—丽江—香格里拉。
  不能承诺：更改城市顺序或将可选延长行程当作标准路线。
  原文依据：Yunnan Family Tour / Typical Duration，[chunk_113ba161c312](../data/knowledge_snapshot/knowledge_chunks.json#L213)，正文字符[43, 127)：
  > Classic Yunnan itinerary: 7 days / 6 nights (Kunming → Dali → Lijiang → Shangri-La).

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB05 · 原手册组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：全部可答**

实际测试输入：云南亲子游经典行程一般安排几天、经过哪些城市？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **云南经典线路的天数与城市顺序：可以回答。** 原云南产品手册直接列出7天6晚及昆明、大理、丽江、香格里拉；无需补造路线。
  应说清楚：7天6晚，昆明—大理—丽江—香格里拉。
  不能承诺：更改城市顺序或将可选延长行程当作标准路线。
  原文依据：Yunnan Family Tour / Typical Duration，[chunk_113ba161c312](../data/knowledge_snapshot/knowledge_chunks.json#L213)，正文字符[43, 127)：
  > Classic Yunnan itinerary: 7 days / 6 nights (Kunming → Dali → Lijiang → Shangri-La).

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB06 · 原手册组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：部分可答**

实际测试输入：For a private Yunnan family tour, is an English-speaking guide included and what exact daily hours are covered?

中文理解：云南亲子私人团包含英语导游吗？每日服务的具体起止时间是什么？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **私人团的英语导游包含规则：可以回答。** 通用报价说明适用于私人团；云南也可选择自助加预订交通，不能扩展为所有云南旅客都已配导游。
  应说清楚：所问私人团按通用规则包含英语导游。
  不能承诺：所有云南客人无论出行方式均已配导游；每天09:00至17:00是原手册规则。
  原文依据：Private Tour Pricing Rules / Guide Requirement，[chunk_c7f793e4b6a6](../data/knowledge_snapshot/knowledge_chunks.json#L603)，正文字符[52, 113)：
  > English-speaking guide included in all private tour packages.

- **导游每日具体服务时段：仍需核实。** 完整手册写了导游类型和价格条件，没有每日起止时间；不能补造09:00至17:00。
  原因：完整资料没有所问答案。
  应说清楚：具体服务时段待核实。
  不能承诺：声称手册规定09:00至17:00。
  原文依据：Private Tour Pricing Rules / Guide Requirement，[chunk_c7f793e4b6a6](../data/knowledge_snapshot/knowledge_chunks.json#L603)，正文字符[52, 113)：
  > English-speaking guide included in all private tour packages.

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB07 · 原手册组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：部分可答**

实际测试输入：云南私人定制游按什么原则定价？儿童优惠有哪些条件，具体价格是多少？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **影响私人定制报价的已知因素：可以回答。** 原报价规则列出人数、酒店、车辆、导游服务与季节；没有具体单人价格。
  应说清楚：人数、酒店等级、车辆、导游服务和季节影响报价。
  不能承诺：直接由人数推算没有依据的金额。
  原文依据：Private Tour Pricing Rules / Pricing Variables，[chunk_1993bf646ea3](../data/knowledge_snapshot/knowledge_chunks.json#L543)，正文字符[52, 162)：
  > Private tour pricing is calculated based on: group size, hotel level, vehicle type, guide service, and season.

- **儿童优惠的年龄和同住条件：可以回答。** 云南产品手册明确12岁以下且与父母同住可享儿童优惠，但没有具体金额或折扣比例。
  应说清楚：12岁以下、与父母同住可享优惠；金额另行核实。
  不能承诺：把所有儿童都判定适用；编造儿童房价、半价或免费。
  原文依据：Yunnan Family Tour / Pricing Notes，[chunk_002f31150e91](../data/knowledge_snapshot/knowledge_chunks.json#L243)，正文字符[40, 154)：
  > Family packages with child discounts available — children under 12 at reduced rate when sharing room with parents.

- **具体儿童团费或房价金额：仍需核实。** 完整手册只有儿童优惠条件，没有儿童金额、折扣比例或该酒店具体房价；应保留已知条件并另核实报价。
  原因：完整资料没有所问答案。
  应说清楚：金额需要进一步报价核实。
  不能承诺：编造具体金额、折扣比例或免费。
  原文依据：Yunnan Family Tour / Pricing Notes，[chunk_002f31150e91](../data/knowledge_snapshot/knowledge_chunks.json#L243)，正文字符[40, 154)：
  > Family packages with child discounts available — children under 12 at reduced rate when sharing room with parents.

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB08 · 原手册组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：部分可答**

实际测试输入：介绍一下云南行程，2026年10月10日还有酒店余位吗？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

已明确的客户信息：出发日期＝2026-10-10（来自T1）。

- **云南经典线路的天数与城市顺序：可以回答。** 原云南产品手册直接列出7天6晚及昆明、大理、丽江、香格里拉；无需补造路线。
  应说清楚：7天6晚，昆明—大理—丽江—香格里拉。
  不能承诺：更改城市顺序或将可选延长行程当作标准路线。
  原文依据：Yunnan Family Tour / Typical Duration，[chunk_113ba161c312](../data/knowledge_snapshot/knowledge_chunks.json#L213)，正文字符[43, 127)：
  > Classic Yunnan itinerary: 7 days / 6 nights (Kunming → Dali → Lijiang → Shangri-La).

- **指定日期实时房态及已预订确认：仍需核实。** 完整静态手册的住宿介绍和季节提醒均不是房态、订单或供应商确认；需独立核实指定日期供应。
  原因：必须核实实时供应/预订。
  应说清楚：需要查询并核实房态或预订凭证。
  不能承诺：保证有房或已预订；把客户愿望、旧回复当供应商确认。
  原文依据：Yunnan Destination Overview / Travel Style，[chunk_aa8a2ca102f0](../data/knowledge_snapshot/knowledge_chunks.json#L483)，正文字符[321, 432)：
  > Accommodation options are extensive: from international 5-star chains to boutique guesthouses in ancient towns.

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB09 · 专项测试组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：构造免费活动和出发日期条件，检查缺客户信息与补齐后的合法对照；不是原手册政策。

**第1轮：部分可答**

实际测试输入：What airport transfers are included, and am I eligible for the October workshop? I have not chosen a departure date.

中文理解：包含哪些机场接送？我能参加十月手工活动吗？我还没选出发日期。

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **说明昆明机场与市区酒店接送范围：可以回答。** 本专项人为设定包含昆明机场与市区酒店之间的抵达及离开接送，其他城市需确认；这不是原产品手册已有的接送规则。
  应说清楚：在本专项设定内，昆明机场与市区酒店抵离接送包含，其他城市待确认。
  不能承诺：把专项接送条款说成原产品手册已明确包含；承诺其他城市接送也包含。
  原文依据：P0-02 Synthetic Yunnan Travel Guide / Airport Transfers，[transfer](../data/answerability_eval/v2/knowledge.json#L1135)，正文字符[0, 188)：
  > 云南亲子游包含昆明机场与市区酒店之间的抵达和离开接送。其他城市接送需另行确认。 Yunnan family tours include arrival and departure transfers between Kunming Airport and city hotels. Transfers in other cities require confirmation.

- **客户日期是否满足10月手工体验规则：仍需核实。** 本专项免费手工体验只适用于2026年10月1日至31日出发；客户没有出发日期，暂不能确定是否符合。
  原因：缺少客户信息。
  应说清楚：说明活动仅限指定十月出发日期，并追问客户出发日期。
  不能承诺：未获得出发日期便保证适用免费活动。
  原文依据：P0-02 Synthetic Yunnan Travel Guide / October Workshop，[date_policy](../data/answerability_eval/v2/knowledge.json#L1158)，正文字符[0, 209)：
  > 出发日期在2026年10月1日至31日的云南亲子游可参加一次免费手工体验；是否适用取决于客户出发日期。 One complimentary craft workshop is included for Yunnan family trips departing from 1 to 31 October 2026. Eligibility depends on the customer departure date.

需要追问：出发日期。

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB10 · 专项测试组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：构造仅2026年9月有效的99元促销，检查过期信息不可用于当前报价。

**第1轮：部分可答**

实际测试输入：云南包含什么接送？这份9月促销价99元现在仍有效吗？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **说明昆明机场与市区酒店接送范围：可以回答。** 本专项人为设定包含昆明机场与市区酒店之间的抵达及离开接送，其他城市需确认；这不是原产品手册已有的接送规则。
  应说清楚：在本专项设定内，昆明机场与市区酒店抵离接送包含，其他城市待确认。
  不能承诺：把专项接送条款说成原产品手册已明确包含；承诺其他城市接送也包含。
  原文依据：P0-02 Synthetic Yunnan Travel Guide / Airport Transfers，[transfer](../data/answerability_eval/v2/knowledge.json#L1135)，正文字符[0, 188)：
  > 云南亲子游包含昆明机场与市区酒店之间的抵达和离开接送。其他城市接送需另行确认。 Yunnan family tours include arrival and departure transfers between Kunming Airport and city hotels. Transfers in other cities require confirmation.

- **已过期促销不能作为现在价格：仍需核实。** 本专项99元促销仅限2026年9月，截止2026年9月30日；本轮评测时点在10月，不能当作当前价格。
  原因：所引资料已经过期。
  应说清楚：说明99元是已结束活动的历史价格，当前报价需另行核实。
  不能承诺：继续承诺当前可按每人99元购买；从历史价格编造新的当前价格。
  原文依据：P0-02 Synthetic Yunnan Travel Guide / Historical Promotion，[expired_price](../data/answerability_eval/v2/knowledge.json#L1238)，正文字符[0, 169)：
  > 2026年9月限时手工体验促销价为每人99元，仅适用于该月，现有文本不能代表后续报价。 The workshop promotion was CNY 99 per person in September 2026 only. This historical text is not a quotation for later dates.

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB11 · 原手册组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：部分可答**

实际测试输入：云南私人团的定金比例是多少？余款的14天期限究竟按抵达日期还是出发日期计算？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **确认预订的定金比例：可以回答。** 两处原文一致写30%定金用于确认预订；没有新增的双方确认书面行程和明细报价这一付款前提。
  应说清楚：30%定金确认预订。
  不能承诺：必须先双方确认书面行程和明细报价才付款。
  原文依据：Private Tour Pricing Rules / Quotation Notes，[chunk_88e6a3c65309](../data/knowledge_snapshot/knowledge_chunks.json#L633)，正文字符[371, 420)：
  > Deposit: 30% deposit required to confirm booking.
  原文依据：Travel Permit and Payment FAQ / Common Questions，[chunk_7eca38e94502](../data/knowledge_snapshot/knowledge_chunks.json#L648)，正文字符[604, 637)：
  > 30% deposit confirms the booking.

- **余款提前14天究竟以抵达还是出发为准：仍需核实。** 通用报价与FAQ问答以抵达为基准，FAQ简答以出发为基准；手册未指明优先级，实际两日可能不同，不能自行选定唯一付款截止日。
  原因：资料口径存在差异或冲突。
  应说清楚：资料同时出现抵达前和出发前14天，需澄清口径；不能自行计算唯一付款截止日。
  不能承诺：无条件选择抵达前14天；无条件选择出发前14天。
  原文依据：Private Tour Pricing Rules / Quotation Notes，[chunk_88e6a3c65309](../data/knowledge_snapshot/knowledge_chunks.json#L633)，正文字符[421, 456)：
  > Balance due 14 days before arrival.
  原文依据：Travel Permit and Payment FAQ / Common Questions，[chunk_7eca38e94502](../data/knowledge_snapshot/knowledge_chunks.json#L648)，正文字符[638, 673)：
  > Balance due 14 days before arrival.
  原文依据：Travel Permit and Payment FAQ / Short Answers，[chunk_2993a362487c](../data/knowledge_snapshot/knowledge_chunks.json#L663)，正文字符[493, 536)：
  > Balance → charged 14 days before departure.

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB12 · 原手册组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：部分可答**

实际测试输入：云南路线包括哪些城市？What are the child-discount conditions and the exact child room price?

中文理解：云南路线包括哪些城市？儿童优惠需要满足哪些条件，儿童房价具体多少？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **云南经典线路的天数与城市顺序：可以回答。** 原云南产品手册直接列出7天6晚及昆明、大理、丽江、香格里拉；无需补造路线。
  应说清楚：7天6晚，昆明—大理—丽江—香格里拉。
  不能承诺：更改城市顺序或将可选延长行程当作标准路线。
  原文依据：Yunnan Family Tour / Typical Duration，[chunk_113ba161c312](../data/knowledge_snapshot/knowledge_chunks.json#L213)，正文字符[43, 127)：
  > Classic Yunnan itinerary: 7 days / 6 nights (Kunming → Dali → Lijiang → Shangri-La).

- **儿童优惠的年龄和同住条件：可以回答。** 云南产品手册明确12岁以下且与父母同住可享儿童优惠，但没有具体金额或折扣比例。
  应说清楚：12岁以下、与父母同住可享优惠；金额另行核实。
  不能承诺：把所有儿童都判定适用；编造儿童房价、半价或免费。
  原文依据：Yunnan Family Tour / Pricing Notes，[chunk_002f31150e91](../data/knowledge_snapshot/knowledge_chunks.json#L243)，正文字符[40, 154)：
  > Family packages with child discounts available — children under 12 at reduced rate when sharing room with parents.

- **具体儿童团费或房价金额：仍需核实。** 完整手册只有儿童优惠条件，没有儿童金额、折扣比例或该酒店具体房价；应保留已知条件并另核实报价。
  原因：完整资料没有所问答案。
  应说清楚：金额需要进一步报价核实。
  不能承诺：编造具体金额、折扣比例或免费。
  原文依据：Yunnan Family Tour / Pricing Notes，[chunk_002f31150e91](../data/knowledge_snapshot/knowledge_chunks.json#L243)，正文字符[40, 154)：
  > Family packages with child discounts available — children under 12 at reduced rate when sharing room with parents.

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB13 · 原手册组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：全部不可答**

实际测试输入：请介绍你们的北极探险邮轮产品和售价。

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **北极探险邮轮产品与售价：仍需核实。** 已核对完整8页面47片段，涉及川西、西藏、云南及通用报价/付款，没有北极探险邮轮产品或售价。
  原因：完整资料没有所问答案。
  应说清楚：现有资料不提供该产品，应说明需另行核实。
  不能承诺：借云南、川西或西藏资料编造邮轮产品价格。
  无直接答案引用；缺口依据是完整资料范围核查，不是删去相关资料后制造的无答案。

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB14 · 原手册组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：部分可答**

实际测试输入：What child-discount conditions does the Yunnan family guide specify, and what is the exact child room price?

中文理解：云南亲子手册规定了哪些儿童优惠条件？儿童房价的具体金额是多少？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **儿童优惠的年龄和同住条件：可以回答。** 云南产品手册明确12岁以下且与父母同住可享儿童优惠，但没有具体金额或折扣比例。
  应说清楚：12岁以下、与父母同住可享优惠；金额另行核实。
  不能承诺：把所有儿童都判定适用；编造儿童房价、半价或免费。
  原文依据：Yunnan Family Tour / Pricing Notes，[chunk_002f31150e91](../data/knowledge_snapshot/knowledge_chunks.json#L243)，正文字符[40, 154)：
  > Family packages with child discounts available — children under 12 at reduced rate when sharing room with parents.

- **具体儿童团费或房价金额：仍需核实。** 完整手册只有儿童优惠条件，没有儿童金额、折扣比例或该酒店具体房价；应保留已知条件并另核实报价。
  原因：完整资料没有所问答案。
  应说清楚：金额需要进一步报价核实。
  不能承诺：编造具体金额、折扣比例或免费。
  原文依据：Yunnan Family Tour / Pricing Notes，[chunk_002f31150e91](../data/knowledge_snapshot/knowledge_chunks.json#L243)，正文字符[40, 154)：
  > Family packages with child discounts available — children under 12 at reduced rate when sharing room with parents.

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB15 · 专项测试组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：人为构造提前7天全退与定金不退的同范围矛盾政策，检查冲突处理；不代表原手册存在此冲突。

**第1轮：全部不可答**

实际测试输入：Can I get the deposit refunded if I cancel the Yunnan family tour seven days before departure?

中文理解：云南亲子团出发前七天取消，定金能退吗？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **未解决的同适用范围退款冲突：仍需核实。** 本专项同时构造了提前7天取消全额退款和定金不退两条有效政策，且没有优先级或解决记录；不能自选其中一条。
  原因：资料口径存在差异或冲突。
  应说清楚：说明两条退款政策相互矛盾，需要进一步核实。
  不能承诺：保证全额退款；直接选定定金不退作为唯一规则。
  原文依据：P0-02 Synthetic Yunnan Travel Guide / Cancellation A，[cancel_a](../data/answerability_eval/v2/knowledge.json#L1295)，正文字符[0, 175)：
  > 云南亲子游在出发前7天取消可全额退款；与另一份同范围有效政策尚未解决冲突。 Yunnan family trips cancelled 7 days before departure receive a full refund; an equally applicable conflicting policy remains unresolved.
  原文依据：P0-02 Synthetic Yunnan Travel Guide / Cancellation B，[cancel_b](../data/answerability_eval/v2/knowledge.json#L1318)，正文字符[0, 184)：
  > 云南亲子游在出发前7天取消定金不退；与另一份同范围有效政策尚未解决冲突。 Deposits for Yunnan family trips cancelled 7 days before departure are non-refundable; an equally applicable conflicting policy remains unresolved.

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB16 · 专项测试组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：构造仅2026年9月有效的99元促销，检查过期信息不可用于当前报价。

**第1轮：全部不可答**

实际测试输入：Is the September CNY 99 workshop promotion still the current price today?

中文理解：九月每人99元的手工活动现在仍是当前价格吗？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **9月促销已过期：仍需核实。** 本专项99元促销仅限2026年9月，截止2026年9月30日；本轮评测时点在10月，不能当作当前价格。
  原因：所引资料已经过期。
  应说清楚：说明99元是已结束活动的历史价格，当前报价需另行核实。
  不能承诺：继续承诺当前可按每人99元购买；从历史价格编造新的当前价格。
  原文依据：P0-02 Synthetic Yunnan Travel Guide / Historical Promotion，[expired_price](../data/answerability_eval/v2/knowledge.json#L1238)，正文字符[0, 169)：
  > 2026年9月限时手工体验促销价为每人99元，仅适用于该月，现有文本不能代表后续报价。 The workshop promotion was CNY 99 per person in September 2026 only. This historical text is not a quotation for later dates.

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB17 · 专项测试组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：构造无有效期与执行证明的88元促销，检查不能把无日期活动当作当前价格。

**第1轮：全部不可答**

实际测试输入：Is the undated CNY 88 workshop promotion still valid today?

中文理解：这项没有日期的每人88元手工促销现在还有效吗？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **没有促销有效期，不能确认现行：仍需核实。** 本专项88元促销没有生效/失效日期或仍在执行的证明；既不能保证现行有效，也不能断言已经过期。
  原因：当前有效性无法核实。
  应说清楚：说明88元活动的有效性未确认，需核实后报价。
  不能承诺：保证当前仍是每人88元；把没有日期直接判为已确定过期。
  原文依据：P0-02 Synthetic Yunnan Travel Guide / Undated Promotion，[unverified_price](../data/answerability_eval/v2/knowledge.json#L1352)，正文字符[0, 164)：
  > 页面写有手工体验促销价每人88元，但没有生效日期、结束日期或仍在执行的证明。 The page lists a workshop promotion of CNY 88 per person, without effective dates or proof that the promotion is still valid.

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB18 · 原手册组 · 1轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：全部不可答**

实际测试输入：Please confirm that my hotel room for 10 October 2026 has been booked and is available.

中文理解：请确认2026年10月10日我的酒店房间有库存并已预订。

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

已明确的客户信息：出发日期＝2026-10-10（来自T1）。

- **指定日期实时房态及已预订确认：仍需核实。** 完整静态手册的住宿介绍和季节提醒均不是房态、订单或供应商确认；需独立核实指定日期供应。
  原因：必须核实实时供应/预订。
  应说清楚：需要查询并核实房态或预订凭证。
  不能承诺：保证有房或已预订；把客户愿望、旧回复当供应商确认。
  原文依据：Yunnan Destination Overview / Travel Style，[chunk_aa8a2ca102f0](../data/knowledge_snapshot/knowledge_chunks.json#L483)，正文字符[321, 432)：
  > Accommodation options are extensive: from international 5-star chains to boutique guesthouses in ancient towns.

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB19 · 原手册组 · 3轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：全部不可答**

实际测试输入：我们想参加云南亲子私人团，孩子能享受儿童优惠吗？我还没有提供孩子年龄，也没确定是否与父母同住。

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **本轮客户的孩子是否满足儿童优惠条件：仍需核实。** 原手册要求12岁以下且与父母同住。当前年龄和是否同住均未提供，因此不能直接判断这个孩子适用。
  原因：缺少客户信息。
  应说清楚：说明12岁以下和同住条件，并询问年龄及是否与父母同住。
  不能承诺：只凭亲子团名称认定儿童符合条件；擅自给具体优惠金额。
  原文依据：Yunnan Family Tour / Pricing Notes，[chunk_002f31150e91](../data/knowledge_snapshot/knowledge_chunks.json#L243)，正文字符[40, 154)：
  > Family packages with child discounts available — children under 12 at reduced rate when sharing room with parents.

需要追问：孩子年龄、是否与父母同住。

**第2轮：全部可答**

实际测试输入：孩子8岁，与父母同住同一间房。按手册是否符合儿童优惠条件？

判断时点：2026-10-05T10:01:00+00:00。只可见此前T1轮；不读取未来消息。

已明确的客户信息：孩子年龄＝8（来自T2）；是否与父母同住＝true（来自T2）。

- **本轮客户的孩子是否满足儿童优惠条件：可以回答。** 原手册要求12岁以下且与父母同住。客户本轮已明确8岁及同住，符合列出的条件；具体优惠金额仍未知。
  应说清楚：依据已给出的年龄和同住信息判断适用条件；不编金额。
  不能承诺：只凭亲子团名称认定儿童符合条件；擅自给具体优惠金额。
  原文依据：Yunnan Family Tour / Pricing Notes，[chunk_002f31150e91](../data/knowledge_snapshot/knowledge_chunks.json#L243)，正文字符[40, 154)：
  > Family packages with child discounts available — children under 12 at reduced rate when sharing room with parents.

已经给出、不可重复索取的信息：孩子年龄、是否与父母同住。

**第3轮：全部不可答**

实际测试输入：条件清楚了。请确认2026年10月10日家庭房有库存并已经预订。

判断时点：2026-10-05T10:02:00+00:00。只可见此前T1、T2轮；不读取未来消息。

已明确的客户信息：孩子年龄＝8（来自T2）；是否与父母同住＝true（来自T2）；出发日期＝2026-10-10（来自T3）。

- **指定日期实时房态及已预订确认：仍需核实。** 完整静态手册的住宿介绍和季节提醒均不是房态、订单或供应商确认；需独立核实指定日期供应。
  原因：必须核实实时供应/预订。
  应说清楚：需要查询并核实房态或预订凭证。
  不能承诺：保证有房或已预订；把客户愿望、旧回复当供应商确认。
  原文依据：Yunnan Destination Overview / Travel Style，[chunk_aa8a2ca102f0](../data/knowledge_snapshot/knowledge_chunks.json#L483)，正文字符[321, 432)：
  > Accommodation options are extensive: from international 5-star chains to boutique guesthouses in ancient towns.

已经给出、不可重复索取的信息：孩子年龄、是否与父母同住。

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB20 · 原手册组 · 3轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：全部可答**

实际测试输入：What cities and duration are specified for the classic Yunnan family itinerary?

中文理解：云南经典亲子线路有哪些城市，安排几天？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **云南经典线路的天数与城市顺序：可以回答。** 原云南产品手册直接列出7天6晚及昆明、大理、丽江、香格里拉；无需补造路线。
  应说清楚：7天6晚，昆明—大理—丽江—香格里拉。
  不能承诺：更改城市顺序或将可选延长行程当作标准路线。
  原文依据：Yunnan Family Tour / Typical Duration，[chunk_113ba161c312](../data/knowledge_snapshot/knowledge_chunks.json#L213)，正文字符[43, 127)：
  > Classic Yunnan itinerary: 7 days / 6 nights (Kunming → Dali → Lijiang → Shangri-La).

**第2轮：全部不可答**

实际测试输入：Can you confirm hotel availability for 10 October 2026?

中文理解：能确认2026年10月10日酒店有空房吗？

判断时点：2026-10-05T10:01:00+00:00。只可见此前T1轮；不读取未来消息。

已明确的客户信息：出发日期＝2026-10-10（来自T2）。

- **指定日期实时房态及已预订确认：仍需核实。** 完整静态手册的住宿介绍和季节提醒均不是房态、订单或供应商确认；需独立核实指定日期供应。
  原因：必须核实实时供应/预订。
  应说清楚：需要查询并核实房态或预订凭证。
  不能承诺：保证有房或已预订；把客户愿望、旧回复当供应商确认。
  原文依据：Yunnan Destination Overview / Travel Style，[chunk_aa8a2ca102f0](../data/knowledge_snapshot/knowledge_chunks.json#L483)，正文字符[321, 432)：
  > Accommodation options are extensive: from international 5-star chains to boutique guesthouses in ancient towns.

**第3轮：全部可答**

实际测试输入：Leave availability for later. Which flights and insurance costs are excluded from the private-tour quotation?

中文理解：房态稍后核实。私人团报价排除哪些机票与保险费用？

判断时点：2026-10-05T10:02:00+00:00。只可见此前T1、T2轮；不读取未来消息。

已明确的客户信息：出发日期＝2026-10-10（来自T2）。

- **私人团通用报价中的机票和旅行保险排除项：可以回答。** 通用报价明确排除flights及travel insurance；没有区分只有国际机票，也未约定代订或自理义务。
  应说清楚：机票和旅行保险不包含在所述私人团通用报价内。
  不能承诺：把国内机票自动算进包含项；无依据承诺代订或强加自行安排义务。
  原文依据：Private Tour Pricing Rules / Quotation Notes，[chunk_88e6a3c65309](../data/knowledge_snapshot/knowledge_chunks.json#L633)，正文字符[176, 255)：
  > excluded items (flights, visa fees, tips, personal expenses, travel insurance).

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB21 · 原手册组 · 3轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：全部不可答**

实际测试输入：Can you confirm that my Yunnan hotel booking is completed?

中文理解：能确认我的云南酒店已经预订完成了吗？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **指定日期实时房态及已预订确认：仍需核实。** 完整静态手册的住宿介绍和季节提醒均不是房态、订单或供应商确认；需独立核实指定日期供应。
  原因：必须核实实时供应/预订。
  应说清楚：需要查询并核实房态或预订凭证。
  不能承诺：保证有房或已预订；把客户愿望、旧回复当供应商确认。
  原文依据：Yunnan Destination Overview / Travel Style，[chunk_aa8a2ca102f0](../data/knowledge_snapshot/knowledge_chunks.json#L483)，正文字符[321, 432)：
  > Accommodation options are extensive: from international 5-star chains to boutique guesthouses in ancient towns.

**第2轮：全部不可答**

实际测试输入：Please do not treat any earlier wording as booking proof. No supplier has confirmed a booking. Is it really confirmed?

中文理解：不要把先前说法当预订证明；尚无供应商确认。真的已经预订了吗？

判断时点：2026-10-05T10:01:00+00:00。只可见此前T1轮；不读取未来消息。

- **指定日期实时房态及已预订确认：仍需核实。** 完整静态手册的住宿介绍和季节提醒均不是房态、订单或供应商确认；需独立核实指定日期供应。
  原因：必须核实实时供应/预订。
  应说清楚：需要查询并核实房态或预订凭证。
  不能承诺：保证有房或已预订；把客户愿望、旧回复当供应商确认。
  原文依据：Yunnan Destination Overview / Travel Style，[chunk_aa8a2ca102f0](../data/knowledge_snapshot/knowledge_chunks.json#L483)，正文字符[321, 432)：
  > Accommodation options are extensive: from international 5-star chains to boutique guesthouses in ancient towns.

**第3轮：全部可答**

实际测试输入：While that is checked, please explain the cities and duration of the classic Yunnan itinerary.

中文理解：核实预订期间，请介绍云南经典线路的城市和时长。

判断时点：2026-10-05T10:02:00+00:00。只可见此前T1、T2轮；不读取未来消息。

- **云南经典线路的天数与城市顺序：可以回答。** 原云南产品手册直接列出7天6晚及昆明、大理、丽江、香格里拉；无需补造路线。
  应说清楚：7天6晚，昆明—大理—丽江—香格里拉。
  不能承诺：更改城市顺序或将可选延长行程当作标准路线。
  原文依据：Yunnan Family Tour / Typical Duration，[chunk_113ba161c312](../data/knowledge_snapshot/knowledge_chunks.json#L213)，正文字符[43, 127)：
  > Classic Yunnan itinerary: 7 days / 6 nights (Kunming → Dali → Lijiang → Shangri-La).

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB22 · 原手册组 · 3轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：全部可答**

实际测试输入：我们8个人想去云南。Please explain the standard itinerary.

中文理解：我们8个人想去云南，请介绍标准行程。

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

已明确的客户信息：人数＝8（来自T1）。

必须保留的业务事实：人数＝8，确认来源T1。不能删除或放宽更正要求。

- **云南经典线路的天数与城市顺序：可以回答。** 原云南产品手册直接列出7天6晚及昆明、大理、丽江、香格里拉；无需补造路线。
  应说清楚：7天6晚，昆明—大理—丽江—香格里拉。
  不能承诺：更改城市顺序或将可选延长行程当作标准路线。
  原文依据：Yunnan Family Tour / Typical Duration，[chunk_113ba161c312](../data/knowledge_snapshot/knowledge_chunks.json#L213)，正文字符[43, 127)：
  > Classic Yunnan itinerary: 7 days / 6 nights (Kunming → Dali → Lijiang → Shangri-La).

**第2轮：全部可答**

实际测试输入：更正一下，不是8个人，是9个人。Does this change the known pricing principles?

中文理解：更正人数，不是8人而是9人；这是否影响已知的定价原则？

判断时点：2026-10-05T10:01:00+00:00。只可见此前T1轮；不读取未来消息。

已明确的客户信息：人数＝9（来自T2）。

必须保留的业务事实：人数＝9，确认来源T2。不能删除或放宽更正要求。

- **影响私人定制报价的已知因素：可以回答。** 原报价规则列出人数、酒店、车辆、导游服务与季节；没有具体单人价格。
  应说清楚：人数、酒店等级、车辆、导游服务和季节影响报价。
  不能承诺：直接由人数推算没有依据的金额。
  原文依据：Private Tour Pricing Rules / Pricing Variables，[chunk_1993bf646ea3](../data/knowledge_snapshot/knowledge_chunks.json#L543)，正文字符[52, 162)：
  > Private tour pricing is calculated based on: group size, hotel level, vehicle type, guide service, and season.

已经给出、不可重复索取的信息：人数。

**第3轮：全部可答**

实际测试输入：按照刚才更正的人数，which items are excluded from the private-tour quotation?

中文理解：按刚才更正的人数，私人团报价有哪些明确的排除项？

判断时点：2026-10-05T10:02:00+00:00。只可见此前T1、T2轮；不读取未来消息。

已明确的客户信息：人数＝9（来自T2）。

必须保留的业务事实：人数＝9，确认来源T2。不能删除或放宽更正要求。

- **私人团通用报价中的机票和旅行保险排除项：可以回答。** 通用报价明确排除flights及travel insurance；没有区分只有国际机票，也未约定代订或自理义务。
  应说清楚：机票和旅行保险不包含在所述私人团通用报价内。
  不能承诺：把国内机票自动算进包含项；无依据承诺代订或强加自行安排义务。
  原文依据：Private Tour Pricing Rules / Quotation Notes，[chunk_88e6a3c65309](../data/knowledge_snapshot/knowledge_chunks.json#L633)，正文字符[176, 255)：
  > excluded items (flights, visa fees, tips, personal expenses, travel insurance).

已经给出、不可重复索取的信息：人数。

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB23 · 专项测试组 · 3轮

案例审核：**待确认**。提问来源：人工合成。资料：构造免费活动和出发日期条件，检查缺客户信息与补齐后的合法对照；不是原手册政策。

**第1轮：全部可答**

实际测试输入：我们在2026年10月10日出发，云南包括什么机场接送？

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

已明确的客户信息：出发日期＝2026-10-10（来自T1）。

- **说明昆明机场与市区酒店接送范围：可以回答。** 本专项人为设定包含昆明机场与市区酒店之间的抵达及离开接送，其他城市需确认；这不是原产品手册已有的接送规则。
  应说清楚：在本专项设定内，昆明机场与市区酒店抵离接送包含，其他城市待确认。
  不能承诺：把专项接送条款说成原产品手册已明确包含；承诺其他城市接送也包含。
  原文依据：P0-02 Synthetic Yunnan Travel Guide / Airport Transfers，[transfer](../data/answerability_eval/v2/knowledge.json#L1135)，正文字符[0, 188)：
  > 云南亲子游包含昆明机场与市区酒店之间的抵达和离开接送。其他城市接送需另行确认。 Yunnan family tours include arrival and departure transfers between Kunming Airport and city hotels. Transfers in other cities require confirmation.

**第2轮：全部可答**

实际测试输入：刚才这个出发日期能参加免费手工体验吗？

判断时点：2026-10-05T10:01:00+00:00。只可见此前T1轮；不读取未来消息。

已明确的客户信息：出发日期＝2026-10-10（来自T1）。

- **客户10月出发适用免费手工体验：可以回答。** 本专项免费体验适用出发日期为2026年10月1日至31日；客户在本会话T1已经给出10月10日，属于该范围，后轮应沿用该已知日期。
  应说清楚：按本专项设定，10月10日出发符合活动日期条件；活动范围为10月1日至31日。
  不能承诺：重复追问已经明确的出发日期；将活动适用扩展到十月之外。
  原文依据：P0-02 Synthetic Yunnan Travel Guide / October Workshop，[date_policy](../data/answerability_eval/v2/knowledge.json#L1158)，正文字符[0, 209)：
  > 出发日期在2026年10月1日至31日的云南亲子游可参加一次免费手工体验；是否适用取决于客户出发日期。 One complimentary craft workshop is included for Yunnan family trips departing from 1 to 31 October 2026. Eligibility depends on the customer departure date.

已经给出、不可重复索取的信息：出发日期。

**第3轮：全部可答**

实际测试输入：请确认这项免费活动的日期适用范围。

判断时点：2026-10-05T10:02:00+00:00。只可见此前T1、T2轮；不读取未来消息。

已明确的客户信息：出发日期＝2026-10-10（来自T1）。

- **客户10月出发适用免费手工体验：可以回答。** 本专项免费体验适用出发日期为2026年10月1日至31日；客户在本会话T1已经给出10月10日，属于该范围，后轮应沿用该已知日期。
  应说清楚：按本专项设定，10月10日出发符合活动日期条件；活动范围为10月1日至31日。
  不能承诺：重复追问已经明确的出发日期；将活动适用扩展到十月之外。
  原文依据：P0-02 Synthetic Yunnan Travel Guide / October Workshop，[date_policy](../data/answerability_eval/v2/knowledge.json#L1158)，正文字符[0, 209)：
  > 出发日期在2026年10月1日至31日的云南亲子游可参加一次免费手工体验；是否适用取决于客户出发日期。 One complimentary craft workshop is included for Yunnan family trips departing from 1 to 31 October 2026. Eligibility depends on the customer departure date.

已经给出、不可重复索取的信息：出发日期。

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

### AB24 · 原手册组 · 3轮

案例审核：**待确认**。提问来源：人工合成。资料：完整原手册47片段。

**第1轮：全部可答**

实际测试输入：请介绍云南亲子游的路线和时长。

中文理解：请介绍云南亲子游的路线和时长。

判断时点：2026-10-05T10:00:00+00:00。只可见此前零轮；不读取未来消息。

- **云南经典线路的天数与城市顺序：可以回答。** 原云南产品手册直接列出7天6晚及昆明、大理、丽江、香格里拉；无需补造路线。
  应说清楚：7天6晚，昆明—大理—丽江—香格里拉。
  不能承诺：更改城市顺序或将可选延长行程当作标准路线。
  原文依据：Yunnan Family Tour / Typical Duration，[chunk_113ba161c312](../data/knowledge_snapshot/knowledge_chunks.json#L213)，正文字符[43, 127)：
  > Classic Yunnan itinerary: 7 days / 6 nights (Kunming → Dali → Lijiang → Shangri-La).

**第2轮：部分可答**

实际测试输入：We also need the exact child hotel price. Which flight and insurance costs are excluded from the private-tour quotation?

中文理解：我们还需要儿童酒店的具体房价；私人团报价排除哪些机票和保险费用？

判断时点：2026-10-05T10:01:00+00:00。只可见此前T1轮；不读取未来消息。

- **具体儿童团费或房价金额：仍需核实。** 完整手册只有儿童优惠条件，没有儿童金额、折扣比例或该酒店具体房价；应保留已知条件并另核实报价。
  原因：完整资料没有所问答案。
  应说清楚：金额需要进一步报价核实。
  不能承诺：编造具体金额、折扣比例或免费。
  原文依据：Yunnan Family Tour / Pricing Notes，[chunk_002f31150e91](../data/knowledge_snapshot/knowledge_chunks.json#L243)，正文字符[40, 154)：
  > Family packages with child discounts available — children under 12 at reduced rate when sharing room with parents.

- **私人团通用报价中的机票和旅行保险排除项：可以回答。** 通用报价明确排除flights及travel insurance；没有区分只有国际机票，也未约定代订或自理义务。
  应说清楚：机票和旅行保险不包含在所述私人团通用报价内。
  不能承诺：把国内机票自动算进包含项；无依据承诺代订或强加自行安排义务。
  原文依据：Private Tour Pricing Rules / Quotation Notes，[chunk_88e6a3c65309](../data/knowledge_snapshot/knowledge_chunks.json#L633)，正文字符[176, 255)：
  > excluded items (flights, visa fees, tips, personal expenses, travel insurance).

**第3轮：全部不可答**

实际测试输入：费用排除范围清楚了。Please arrange verification of the child price and hotel availability; do not claim either is confirmed.

中文理解：费用排除范围已清楚，请核实儿童房价与酒店库存，不要声称任一已经确认。

判断时点：2026-10-05T10:02:00+00:00。只可见此前T1、T2轮；不读取未来消息。

- **具体儿童团费或房价金额：仍需核实。** 完整手册只有儿童优惠条件，没有儿童金额、折扣比例或该酒店具体房价；应保留已知条件并另核实报价。
  原因：完整资料没有所问答案。
  应说清楚：金额需要进一步报价核实。
  不能承诺：编造具体金额、折扣比例或免费。
  原文依据：Yunnan Family Tour / Pricing Notes，[chunk_002f31150e91](../data/knowledge_snapshot/knowledge_chunks.json#L243)，正文字符[40, 154)：
  > Family packages with child discounts available — children under 12 at reduced rate when sharing room with parents.

- **指定日期实时房态及已预订确认：仍需核实。** 完整静态手册的住宿介绍和季节提醒均不是房态、订单或供应商确认；需独立核实指定日期供应。
  原因：必须核实实时供应/预订。
  应说清楚：需要查询并核实房态或预订凭证。
  不能承诺：保证有房或已预订；把客户愿望、旧回复当供应商确认。
  原文依据：Yunnan Destination Overview / Travel Style，[chunk_aa8a2ca102f0](../data/knowledge_snapshot/knowledge_chunks.json#L483)，正文字符[321, 432)：
  > Accommodation options are extensive: from international 5-star chains to boutique guesthouses in ancient towns.

实际系统输出及语义结论：留待运行报告和真实审核记录，不在本案例包中预填通过。

## 更正失败和版本边界

AB22第二轮保留原句“更正一下，不是8个人，是9个人。Does this change the known pricing principles?”，事实要求仍为8→9→9，来源依次T1/T2/T2。v2只将第一/第三轮业务提问从接送换为原手册支持的内容；旧失败不删除，不通过改宽断言制造修复。

[原输入诊断材料](../data/answerability_eval/v2/legacy_fact_probe.json)保留v1 AB22完整三轮输入与原事实要求。它只用于单独诊断人数更正，结果不算v2业务得分，也不能把改过题目的新结果直接当成质量提升。该文件和[逐例迁移映射](../data/answerability_eval/v2/case_migration.json)均由来源清单绑定散列，加载器还独立核对原v1案例。

所有24例都改变了资料/版本绑定。旧v1报告与人工裁定不能自动转为v2证据；即使总场景数相同，也不可直接比较两版总分。业务确认时修改review_status及审核记录，需要同步迁移映射与绑定指纹，不能单改标记绕过新版本证据。

## 审核和正式接纳的剩余条件

案例确认只认可问题及预期要求；具体运行输出还需要绑定实际报告的真实开发/销售双身份语义审核。未审核输出保持待复核，自动失败保留。正式GitHub产物、来源核验、可信批准绑定、必需检查配置和新基线接纳另行办理，不因案例文件生成或本地测试通过而自动完成。

## 附录：分组和程序标识

- 问题来源 `scenario_origin=synthetic_question`：人工编写的测试提问。
- 资料来源 `corpus_origin=original_handbook` / `synthetic_fixture`：原手册 / 专项构造资料。
- 分组 `evaluation_group=handbook` / `synthetic_special`：原手册成绩 / 专项能力成绩。
- 以上字段及中文解释、标准答案、支持组、理由、等级均只供评分和审核，不能作为提示泄漏给被测系统。

### 完整原手册片段索引

| 序号 | 原页面 / 章节 | 原片段链接 |
| --- | --- | --- |
| 1 | Western Sichuan Private Tour / Suitable For | [chunk_c9e8d0d19364](../data/knowledge_snapshot/knowledge_chunks.json#L3) |
| 2 | Western Sichuan Private Tour / Key Experiences | [chunk_d7c9ec0f102e](../data/knowledge_snapshot/knowledge_chunks.json#L18) |
| 3 | Western Sichuan Private Tour / Typical Duration | [chunk_9af799833430](../data/knowledge_snapshot/knowledge_chunks.json#L33) |
| 4 | Western Sichuan Private Tour / Best Season | [chunk_84772c49dd0f](../data/knowledge_snapshot/knowledge_chunks.json#L48) |
| 5 | Western Sichuan Private Tour / Pricing Notes | [chunk_aaa055a9a3f7](../data/knowledge_snapshot/knowledge_chunks.json#L63) |
| 6 | Western Sichuan Private Tour / Sales Follow-up Notes | [chunk_3e043f84fd5f](../data/knowledge_snapshot/knowledge_chunks.json#L78) |
| 7 | Tibet Cultural Tour / Suitable For | [chunk_1965ab8b688d](../data/knowledge_snapshot/knowledge_chunks.json#L93) |
| 8 | Tibet Cultural Tour / Key Experiences | [chunk_3e2c139cda1e](../data/knowledge_snapshot/knowledge_chunks.json#L108) |
| 9 | Tibet Cultural Tour / Typical Duration | [chunk_7a1518bdcf84](../data/knowledge_snapshot/knowledge_chunks.json#L123) |
| 10 | Tibet Cultural Tour / Best Season | [chunk_0645e536739a](../data/knowledge_snapshot/knowledge_chunks.json#L138) |
| 11 | Tibet Cultural Tour / Pricing Notes | [chunk_43af7738e91e](../data/knowledge_snapshot/knowledge_chunks.json#L153) |
| 12 | Tibet Cultural Tour / Sales Follow-up Notes | [chunk_76637fb2f2a9](../data/knowledge_snapshot/knowledge_chunks.json#L168) |
| 13 | Yunnan Family Tour / Suitable For | [chunk_d73ed0c855c7](../data/knowledge_snapshot/knowledge_chunks.json#L183) |
| 14 | Yunnan Family Tour / Key Experiences | [chunk_e4b81cf5acd9](../data/knowledge_snapshot/knowledge_chunks.json#L198) |
| 15 | Yunnan Family Tour / Typical Duration | [chunk_113ba161c312](../data/knowledge_snapshot/knowledge_chunks.json#L213) |
| 16 | Yunnan Family Tour / Best Season | [chunk_a132898c139f](../data/knowledge_snapshot/knowledge_chunks.json#L228) |
| 17 | Yunnan Family Tour / Pricing Notes | [chunk_002f31150e91](../data/knowledge_snapshot/knowledge_chunks.json#L243) |
| 18 | Yunnan Family Tour / Sales Follow-up Notes | [chunk_f9049bbbcdb1](../data/knowledge_snapshot/knowledge_chunks.json#L258) |
| 19 | Western Sichuan Destination Overview / Region Overview | [chunk_9157dc292587](../data/knowledge_snapshot/knowledge_chunks.json#L273) |
| 20 | Western Sichuan Destination Overview / Best For | [chunk_9bf5678be357](../data/knowledge_snapshot/knowledge_chunks.json#L288) |
| 21 | Western Sichuan Destination Overview / Travel Style | [chunk_73b44c0df7c7](../data/knowledge_snapshot/knowledge_chunks.json#L303) |
| 22 | Western Sichuan Destination Overview / Seasonality | [chunk_476d27002b65](../data/knowledge_snapshot/knowledge_chunks.json#L318) |
| 23 | Western Sichuan Destination Overview / Operational Notes | [chunk_39bee831099d](../data/knowledge_snapshot/knowledge_chunks.json#L333) |
| 24 | Western Sichuan Destination Overview / Sales Follow-up Notes | [chunk_ae2e88eeb34f](../data/knowledge_snapshot/knowledge_chunks.json#L348) |
| 25 | Tibet Destination Overview / Region Overview | [chunk_9feea14f70a7](../data/knowledge_snapshot/knowledge_chunks.json#L363) |
| 26 | Tibet Destination Overview / Best For | [chunk_bd0b00d49082](../data/knowledge_snapshot/knowledge_chunks.json#L378) |
| 27 | Tibet Destination Overview / Travel Style | [chunk_f84d7ffe5da4](../data/knowledge_snapshot/knowledge_chunks.json#L393) |
| 28 | Tibet Destination Overview / Seasonality | [chunk_6ab97a033ba9](../data/knowledge_snapshot/knowledge_chunks.json#L408) |
| 29 | Tibet Destination Overview / Operational Notes | [chunk_f9ad56deb3b3](../data/knowledge_snapshot/knowledge_chunks.json#L423) |
| 30 | Tibet Destination Overview / Sales Follow-up Notes | [chunk_e7e523f7ca46](../data/knowledge_snapshot/knowledge_chunks.json#L438) |
| 31 | Yunnan Destination Overview / Region Overview | [chunk_987a9f896849](../data/knowledge_snapshot/knowledge_chunks.json#L453) |
| 32 | Yunnan Destination Overview / Best For | [chunk_503cf462045a](../data/knowledge_snapshot/knowledge_chunks.json#L468) |
| 33 | Yunnan Destination Overview / Travel Style | [chunk_aa8a2ca102f0](../data/knowledge_snapshot/knowledge_chunks.json#L483) |
| 34 | Yunnan Destination Overview / Seasonality | [chunk_0430f496c12f](../data/knowledge_snapshot/knowledge_chunks.json#L498) |
| 35 | Yunnan Destination Overview / Operational Notes | [chunk_200df10e44e5](../data/knowledge_snapshot/knowledge_chunks.json#L513) |
| 36 | Yunnan Destination Overview / Sales Follow-up Notes | [chunk_3ccc6d609841](../data/knowledge_snapshot/knowledge_chunks.json#L528) |
| 37 | Private Tour Pricing Rules / Pricing Variables | [chunk_1993bf646ea3](../data/knowledge_snapshot/knowledge_chunks.json#L543) |
| 38 | Private Tour Pricing Rules / Group Size | [chunk_6956be29c035](../data/knowledge_snapshot/knowledge_chunks.json#L558) |
| 39 | Private Tour Pricing Rules / Hotel Level | [chunk_6a627e280919](../data/knowledge_snapshot/knowledge_chunks.json#L573) |
| 40 | Private Tour Pricing Rules / Vehicle Type | [chunk_c58328c80c88](../data/knowledge_snapshot/knowledge_chunks.json#L588) |
| 41 | Private Tour Pricing Rules / Guide Requirement | [chunk_c7f793e4b6a6](../data/knowledge_snapshot/knowledge_chunks.json#L603) |
| 42 | Private Tour Pricing Rules / Seasonal Factors | [chunk_d69747b5ec63](../data/knowledge_snapshot/knowledge_chunks.json#L618) |
| 43 | Private Tour Pricing Rules / Quotation Notes | [chunk_88e6a3c65309](../data/knowledge_snapshot/knowledge_chunks.json#L633) |
| 44 | Travel Permit and Payment FAQ / Common Questions | [chunk_7eca38e94502](../data/knowledge_snapshot/knowledge_chunks.json#L648) |
| 45 | Travel Permit and Payment FAQ / Short Answers | [chunk_2993a362487c](../data/knowledge_snapshot/knowledge_chunks.json#L663) |
| 46 | Travel Permit and Payment FAQ / Sales Notes | [chunk_275d951a1103](../data/knowledge_snapshot/knowledge_chunks.json#L678) |
| 47 | Travel Permit and Payment FAQ / Risk Notes | [chunk_7dfb1c7c56dc](../data/knowledge_snapshot/knowledge_chunks.json#L693) |
