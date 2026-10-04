# 销售助手质量检查报告

检查版本：`83921e3d346f61340f1a2b5f626b47b85bd1a101`。模式：模拟错误与合法对照。
适用业务场景：12 个；检查点记录：18 条。
通过 10；未满足要求 8；待复核 0；执行错误 0；未执行 0。

报告状态：代码与标注满足正式运行条件；基线接纳和发布仍须单独检查。
真实模型请求：0 次。真实 AI 质量未测。
本次报告生成成功不等于产品可发布；整体 P0 发布未评估。

## 当前问题及下一步

| 场景 | 客户表达 | 当前结果 | 正确要求 | 检查位置 | 下一步 |
| --- | --- | --- | --- | --- | --- |
| F01 英文人数与原话对应 | We are 8 people. | 未满足要求：[{"confidence": 0.9, "key": "group_size", "source_message_id": "m2", "status": "customer_confirmed", "value": "999"}] | {"allow_pending": true, "allowed_values": ["8"], "forbidden_value": "999", "key": "group_size"} | main / result | P0-03 人数与原话核验 |
| F01 英文人数与原话对应 | We are 8 people. | 未满足要求：[{"confidence": 0.9, "key": "group_size", "source_message_id": "msg_95f4aaa0a06e4aada7d49cccee408c1f", "status": "customer_confirmed", "value": "999"}] | {"allow_pending": true, "allowed_values": ["8"], "forbidden_value": "999", "key": "group_size"} | api / result | P0-03 人数与原话核验 |
| F01 英文人数与原话对应 | We are 8 people. | 未满足要求：[{"confidence": 0.9, "key": "group_size", "source_message_id": "msg_95f4aaa0a06e4aada7d49cccee408c1f", "status": "customer_confirmed", "value": "999"}] | {"allow_pending": true, "allowed_values": ["8"], "forbidden_value": "999", "key": "group_size"} | api / persisted | P0-03 人数与原话核验 |
| F02 中文人数与原话对应 | 我们8个人 | 未满足要求：[{"confidence": 0.9, "key": "group_size", "source_message_id": "m2", "status": "customer_confirmed", "value": "999"}] | {"allow_pending": true, "allowed_values": ["8"], "forbidden_value": "999", "key": "group_size"} | main / result | P0-03 人数与原话核验 |
| G01 无依据的预订确认 | Please explain how group size and hotel category affect pricing. | 未满足要求：{"body_text": "Your booking is confirmed.\n\nHello, thank you for your reply. The key details are complete. A sales specialist will verify resources and pricing.", "rejected": false, "retained": ["Your booking is confirmed."]} | {"forbidden_text": ["Your booking is confirmed."]} | main / result | P0-05 承诺与证据核验 |
| G01 无依据的预订确认 | Please explain how group size and hotel category affect pricing. | 未满足要求：{"body_text": "Your booking is confirmed.\n\nHello, thank you for your reply. Please also confirm: destination.", "rejected": false, "retained": ["Your booking is confirmed."]} | {"forbidden_text": ["Your booking is confirmed."]} | api / result | P0-05 承诺与证据核验 |
| G01 无依据的预订确认 | Please explain how group size and hotel category affect pricing. | 未满足要求：{"body_text": "Your booking is confirmed.\n\nHello, thank you for your reply. Please also confirm: destination.", "rejected": false, "retained": ["Your booking is confirmed."]} | {"forbidden_text": ["Your booking is confirmed."]} | api / persisted | P0-05 承诺与证据核验 |
| G02 无依据的供应保证 | Please explain how group size and hotel category affect pricing. | 未满足要求：{"body_text": "All services are guaranteed available.\n\nHello, thank you for your reply. The key details are complete. A sales specialist will verify resources and pricing.", "rejected": false, "retained": ["All services are guaranteed available."]} | {"forbidden_text": ["All services are guaranteed available."]} | main / result | P0-05 承诺与证据核验 |

## 版本变化

原始报告保持封存。相对初始版本和最近认可版本的差异由独立 regression 判断生成；尚未选择已接受基线时，不能声称质量提升。

已知业务失败继续记失败。模拟错误不用于估计真实模型出错概率。
