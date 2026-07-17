# MVP Batch Test Report - 2026-05-29

## 1. Test Goal

This test validates whether the AI Sales Lead CRM MVP can process a batch of 12 processed leads, route valid and invalid leads correctly, run AI analysis on valid leads, write successful results to Notion Leads Table, record execution logs, and trigger internal notification for high-value B2B leads.

## 2. Test Workflow

Workflow name:

`AI Sales Lead CRM MVP - Batch Full 12 Test`

Webhook path:

`ai-sales-lead-batch-full-12-test`

Execution ID:

`367`

## 3. Test Input

Input file:

`data/processed-leads-batch-test.json`

The test input was copied from `data/processed-leads.json`, with `_full_01` appended to each `lead_id` to avoid mixing this full-batch run with earlier Notion test pages.

Total leads:

| Metric | Value |
|---|---:|
| Total leads | 12 |
| Expected valid leads | 10 |
| Expected invalid leads | 2 |

## 4. Execution Result

| Metric | Value |
|---|---:|
| Normalize output items | 12 |
| IF true branch items | 10 |
| IF false branch items | 2 |
| AI output items | 10 |
| Parse Success | 10 |
| Parse Failed | 0 |
| Leads created in Notion | 10 |
| Success logs created | 10 |
| Skipped logs created | 2 |
| Failed logs created | 0 |
| High-value B2B notifications triggered | 1 |

## 5. Key Sample Checks

### Mark Chen

| Field | Result |
|---|---|
| lead_id | `lead_059efed9_full_01` |
| lead_type | `B2B` |
| b2b_category | `Overseas Travel Agency` |
| intent_level | `High` |
| lead_score | `85` |
| notification triggered | Yes |

### Daniel Harper

| Field | Result |
|---|---|
| lead_id | `lead_15b68668_full_01` |
| lead_type | `B2C` |
| b2b_category | `None` |
| intent_level | `Medium` |
| lead_score | `65` |
| notification triggered | No |

### Cheap SEO Team

| Field | Result |
|---|---|
| lead_id | `lead_3e19bb9c_full_01` |
| lead_type | `Spam / Low-value` |
| b2b_category | `None` |
| intent_level | `Low` |
| lead_score | `5` |
| follow_up_email empty | Yes |
| notification triggered | No |

### Invalid Leads

| Lead | Result |
|---|---|
| `lead_c85964c1_full_01` missing name | Did not enter AI, did not create Lead page, wrote Processing Log with `status = Skipped`, `step_name = AI Lead Analysis`, `error_message = Name is required` |
| `lead_d55fb7a6_full_01` null name | Did not enter AI, did not create Lead page, wrote Processing Log with `status = Skipped`, `step_name = AI Lead Analysis`, `error_message = Name is required` |

## 6. Other Lead Classification Results

| Lead | lead_type | b2b_category | intent_level | lead_score |
|---|---|---|---|---:|
| Emma Wilson | `B2C` | `None` | `Medium` | 65 |
| Sofia Martinez | `B2C` | `None` | `Medium` | 60 |
| Lina Park | `B2B` | `Content Creator / Media` | `Medium` | 60 |
| Oliver Smith | `B2C` | `None` | `Medium` | 55 |
| Rachel Brown | `B2C` | `None` | `High` | 85 |
| 王先生 | `B2B` | `Local Partner` | `Medium` | 65 |
| Messy Source User | `B2C` | `None` | `Medium` | 60 |

Rachel Brown was classified as `B2C / High / 85`, but did not trigger internal notification because the notification rule requires `lead_type = B2B`, `intent_level = High`, and `lead_score >= 80`.

## 7. Issues Found

1. The first POST attempt failed because `processed-leads-batch-test.json` was written with a UTF-8 BOM. n8n rejected the request body as invalid JSON.
2. Earlier 4-lead testing showed prompt-rule interference: a B2C scoring guard caused Mark Chen to be downgraded to `Medium / 65` until a B2B high-value protection rule was added.
3. Batch workflows cannot use `.first()` for item-specific data access. It would incorrectly reuse the first lead across all items.

## 8. Fixes Applied

1. Rewrote `data/processed-leads-batch-test.json` as UTF-8 without BOM before POSTing to n8n.
2. Added B2C scoring guard so clear one-day B2C inquiries are usually Medium, not automatically 80+.
3. Added B2B high-value protection so clear overseas travel agency, DMC, or ground-operator cooperation leads are not downgraded by B2C scoring rules.
4. Replaced `.first()` batch access with item-safe access and `Merge - Lead + AI Output` using `mergeByPosition`.
5. Used a separate `Batch Full 12 Test` workflow to avoid changing the previously validated 4-lead full test workflow.

## 9. Conclusion

The batch MVP test result is:

- [x] Passed
- [ ] Failed
- [ ] Partially passed

Summary:

The workflow successfully processed 12 processed leads as a batch. It normalized 12 items, routed 10 valid leads to AI, skipped 2 invalid leads, parsed all 10 AI outputs successfully, created 10 Notion Lead pages, created 10 Success logs and 2 Skipped logs, created 0 Failed logs, and triggered 1 high-value B2B notification for Mark Chen.
