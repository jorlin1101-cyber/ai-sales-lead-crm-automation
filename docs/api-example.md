# API Example

下面是本地 `demo + keyword_rrf` 路径的完整示例。`lead_id` 每次运行都会重新生成。

## Request

```powershell
$body = @{
    external_lead_id = "n8n-demo-high-001"
    name = "Demo High Lead"
    email = "high@example.com"
    company_name = "Example Travel Agency"
    message = "Please quote a private Chengdu tour for 20 travelers in September."
    source = "README-demo"
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "http://127.0.0.1:8000/process-lead" `
    -ContentType "application/json" `
    -Headers @{"X-Request-ID" = "api-example-001"} `
    -Body $body
```

## Response

```json
{
  "cleaned_lead": {
    "lead_id": "0cbc5168-ac60-42cd-8663-d307c9fd7d17",
    "external_lead_id": "n8n-demo-high-001",
    "name": "Demo High Lead",
    "email": "high@example.com",
    "company_name": "Example Travel Agency",
    "message": "Please quote a private Chengdu tour for 20 travelers in September.",
    "source": "README-demo"
  },
  "validation_result": {
    "is_valid": true,
    "error_codes": []
  },
  "analysis_result": {
    "features": {
      "customer_kind": "agency",
      "group_size": 20,
      "mentions_specific_dates": true,
      "asks_for_price": true,
      "asks_for_availability": false,
      "requests_private_or_custom_service": true,
      "requests_partnership": false,
      "contains_spam_or_promotion": false,
      "destinations": ["Chengdu"],
      "language": "en",
      "company_name_present": true,
      "cleaned_message_length": 66,
      "conflict_codes": []
    },
    "security_signals": {
      "injection_suspected": false,
      "matched_pattern_codes": [],
      "knowledge_injection_suspected": false
    },
    "decision": {
      "lead_type": "B2B",
      "lead_subtype": "Agency",
      "disposition": "qualified",
      "intent_level": "High",
      "lead_score": 100,
      "score_breakdown": [
        {
          "component": "customer_fit",
          "points": 30,
          "max_points": 30,
          "reason_codes": ["customer_kind_agency"]
        },
        {
          "component": "intent_strength",
          "points": 30,
          "max_points": 30,
          "reason_codes": [
            "asks_for_price",
            "mentions_specific_dates",
            "requests_private_or_custom_service"
          ]
        },
        {
          "component": "order_value_proxy",
          "points": 25,
          "max_points": 25,
          "reason_codes": ["group_size_at_least_10"]
        },
        {
          "component": "information_completeness",
          "points": 15,
          "max_points": 15,
          "reason_codes": [
            "company_name_present",
            "message_length_at_least_30",
            "group_size_known",
            "specific_dates_known",
            "destination_known"
          ]
        }
      ],
      "needs_review": false,
      "review_reasons": [],
      "policy_version": "policy-v1"
    },
    "lead_summary": "Analysis generated from an explicit offline demo fixture and the deterministic lead policy.",
    "recommended_action": "Review the lead and prepare a tailored response using these retrieved knowledge sections: Private Tour Pricing Rules — Pricing Variables; Private Tour Pricing Rules — Group Size; Private Tour Pricing Rules — Quotation Notes. Confirm dates, group details, budget, and any special requirements before sending a proposal.",
    "followup_email_draft": "",
    "metadata": {
      "execution_mode": "demo",
      "analysis_method": "demo_fixture",
      "recommendation_method": "demo_template",
      "retrieval_method": "keyword_rrf",
      "provider": null,
      "model": null,
      "prompt_version": null,
      "fallback_reason": null
    }
  },
  "sources": [
    {
      "chunk_id": "chunk_1993bf646ea3",
      "source_title": "Private Tour Pricing Rules",
      "section": "Pricing Variables",
      "rank": 1
    },
    {
      "chunk_id": "chunk_6956be29c035",
      "source_title": "Private Tour Pricing Rules",
      "section": "Group Size",
      "rank": 2
    },
    {
      "chunk_id": "chunk_88e6a3c65309",
      "source_title": "Private Tour Pricing Rules",
      "section": "Quotation Notes",
      "rank": 3
    }
  ]
}
```

Response Header:

```text
X-Request-ID: api-example-001
```
