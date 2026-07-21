# API Contract

## Day 5 grounded sources and recommendation boundary

RAG runs only after validation, feature extraction, security detection, and `PolicyV1`. It may add sanitized `sources` and update recommendation provenance, but it cannot change `LeadDecision`.

```text
valid non-spam lead
-> LeadFeatures
-> PolicyV1 LeadDecision (final)
-> deterministic query builder
-> configured RAG backend
-> sanitized Top 3 sources
-> deterministic recommendation
```

Runtime backends are `disabled`, `keyword_rrf`, and `bge_rrf`. The default `keyword_rrf` path uses the local public knowledge snapshot and does not require network access. The BGE service uses port `8001`, separate from the FastAPI port.

`RAG_REQUIRED=false` keeps the API available when retrieval fails: `sources=[]`, `retrieval_method=unavailable`, and `recommendation_method=generic_template`. `RAG_REQUIRED=true` fails startup or returns HTTP 503 with public code `rag_unavailable`; it never invents sources.

Invalid and spam leads do not call RAG. Suspected prompt injection never invokes an LLM recommendation generator. The current Day 5 implementation intentionally keeps live recommendation on the generic deterministic template.

Only these public source fields are returned:

```text
chunk_id
source_title
section
rank
```

Internal chunk text, Notion page IDs, source paths, and retrieval scores are never included in the API response.

## Day 4 runtime mode and provider lifecycle

The API creates one feature extractor when the application starts and reuses it for every request. `APP_MODE` chooses that extractor:

| `APP_MODE` | Extractor | External network |
|---|---|---:|
| `demo` | Saved demo fixture, with rule fallback when an ID is missing | Disabled |
| `rule_only` | Deterministic rule features | Disabled |
| `live` | Configured OpenAI feature client, with approved rule fallbacks | Must be explicitly enabled |

Offline modes never construct the OpenAI client, even if API-key environment variables are present. Live configuration is validated before the application accepts traffic. The reusable live client is closed when the application shuts down.

Approved live runtime failures such as timeout, rate limit, provider unavailability, invalid JSON, or schema failure return HTTP 200 through deterministic rule fallback. The response records the real path in `analysis_result.metadata`.

Non-fallback provider errors use stable transport responses without returning secret values or raw provider errors:

| Provider failure | HTTP status | Public error code |
|---|---:|---|
| Authentication failure | 503 | `authentication_error` |
| Runtime configuration failure | 503 | `configuration_error` |
| Unexpected client failure | 500 | `internal_error` |

## Day 3 analysis contract update

The authoritative `analysis_result` structure is now nested:

```text
analysis_result
|- features
|- security_signals
|- decision
|  |- lead_type
|  |- lead_subtype
|  |- disposition
|  |- intent_level
|  |- lead_score
|  |- score_breakdown
|  |- needs_review
|  |- review_reasons
|  `- policy_version
|- lead_summary
|- recommended_action
|- followup_email_draft
`- metadata
   |- execution_mode
   |- analysis_method
   |- recommendation_method
   |- retrieval_method
   |- provider
   |- model
   |- prompt_version
   `- fallback_reason
```

The LLM only produces restricted business features. Deterministic code supplies security signals and server-owned facts, and `PolicyV1` alone produces the final decision. The removed flat paths such as `analysis_result.lead_score` and `analysis_result.analysis_method` must not be used.

Current downstream paths are:

```text
analysis_result.decision.lead_score
analysis_result.decision.intent_level
analysis_result.decision.disposition
analysis_result.metadata.execution_mode
analysis_result.metadata.analysis_method
analysis_result.metadata.fallback_reason
```

Current execution modes are `demo`, `live`, and `rule_only`. Current analysis methods are `llm_features`, `demo_fixture`, and `rule_features`. When live LLM feature extraction fails, the response schema stays unchanged and metadata records `execution_mode=live`, `analysis_method=rule_features`, and a server-owned fallback reason.

The older flat examples later in this document are retained only as Day 2 history and are superseded by this section.

## Overview

This document defines the API contract for the AI Sales Lead CRM Automation project.

The main API endpoint is:

```text
POST /process-lead
```

This endpoint is called by n8n or other external workflow tools. It receives one raw lead, processes it through the backend service layer, and returns a structured processing result.

The API is designed around stable data contracts. Downstream workflow tools should rely on the response schema instead of parsing unstructured text.

The design decision behind Contract V2 is recorded in:

```text
docs/adr/0001-lead-contract-v2.md
```

---

## Endpoint

```text
POST /process-lead
```

## Responsibility

`/process-lead` receives a raw inbound lead and returns a structured lead processing result.

Internally, the API triggers the following processing steps:

```text
RawLeadInput
→ clean_lead()
→ validate_lead()
→ invalid: return without analysis
→ valid: analyze_lead()
→ LeadProcessingResult
```

An invalid lead does not call the analyzer and returns `analysis_result=null` and `sources=[]`.

The `analyze_lead()` step uses an LLM-first strategy:

```text
Try LLM analysis
→ if successful, return LLM-based LeadAnalysisResult
→ if LLM fails, use rule-based fallback
→ return rule_fallback LeadAnalysisResult
```

This ensures the system can still return a usable result even when the LLM provider fails, returns invalid JSON, or produces output that does not pass schema validation.

---

## Request Body

The endpoint accepts a `RawLeadInput` object.

Example request:

```json
{
  "external_lead_id": "website-form-001",
  "name": "Maria Garcia",
  "email": "maria@example.com",
  "company_name": "Spain Travel Agency",
  "message": "We want a quotation for a 20 people private custom China tour in September. Please help us plan the itinerary and price.",
  "source": "Website"
}
```

### Request Fields

| Field | Type | Required | Limit | Description |
|---|---|---:|---:|---|
| `external_lead_id` | string or null | No | 100 | Identifier supplied by an external form, workflow, or CRM. |
| `name` | string or null | No | 200 | Contact name. |
| `email` | string | Yes | 320 | Contact email. Format is checked during domain validation. |
| `company_name` | string or null | No | 300 | Company or organization name. |
| `message` | string | Yes | 1–5000 | Original inquiry message. |
| `source` | string or null | No | 100 | Blank or null values become `Unknown` after cleaning. |

Unknown fields are forbidden. For example, `company` is rejected with HTTP 422. External adapters must explicitly map it to `company_name` before calling the API.

### Transport Errors and Domain-Invalid Leads

| Input case | HTTP status | Result |
|---|---:|---|
| Missing `email` | 422 | Request-structure error |
| `email=""` | 200 | Invalid with `empty_email` |
| Malformed email | 200 | Invalid with `invalid_email_format` |
| Missing `message` | 422 | Request-structure error |
| `message=""` | 422 | Request-structure error |
| `message="   "` | 200 | Invalid with `empty_message_after_cleaning` |
| Unknown field such as `company` | 422 | `extra_forbidden` |
| Message longer than 5000 characters | 422 | Request-structure error |

HTTP 422 means the request does not satisfy the API structure. HTTP 200 with `is_valid=false` means the request structure is acceptable, but the lead contains business-invalid data that may still need to be recorded.

---

## Cleaning Rules

The service generates its own `lead_id`, preserves `external_lead_id`, trims leading and trailing whitespace, converts email to lowercase, converts missing names to empty strings, and converts a blank or null source to `Unknown`.

`external_lead_id` is a trace identifier. The current MVP does not claim database-level idempotency or uniqueness for it.

---

## Historical Day 2 Response Body (superseded by the Day 3 contract above)

The endpoint returns a `LeadProcessingResult`.

Example response for a valid lead:

```json
{
  "cleaned_lead": {
    "lead_id": "45fc3a33-ee13-4660-8dab-9fbb01fd10ea",
    "external_lead_id": "website-form-001",
    "name": "Maria Garcia",
    "email": "maria@example.com",
    "company_name": "Spain Travel Agency",
    "message": "We want a quotation for a 20 people private custom China tour in September. Please help us plan the itinerary and price.",
    "source": "Website"
  },
  "validation_result": {
    "is_valid": true,
    "error_codes": []
  },
  "analysis_result": {
    "lead_type": "B2B",
    "lead_subtype": "Agency",
    "intent_level": "High",
    "lead_score": 85,
    "lead_summary": "Maria Garcia from Spain Travel Agency requests a quotation and itinerary for a private custom China tour for 20 people in September.",
    "recommended_action": "Review the lead and prepare a tailored response. Confirm exact travel dates, preferred destinations, budget range, and special requirements before sending a proposal.",
    "followup_email_draft": "Dear Maria,\n\nThank you for reaching out to us...",
    "analysis_method": "rule_fallback",
    "confidence": 0.55
  },
  "sources": []
}
```

---

## Response Fields

### cleaned_lead

`cleaned_lead` contains normalized lead data.

| Field        |   Type | Description                                     |
| ------------ | -----: | ----------------------------------------------- |
| lead_id      | string | Unique lead identifier generated by the system. |
| external_lead_id | string or null | Identifier supplied by the external source. |
| name         | string | Cleaned contact name.                           |
| email        | string | Lowercased and trimmed email.                   |
| company_name | string | Cleaned company name.                           |
| message      | string | Cleaned inquiry message.                        |
| source       | string | Cleaned lead source.                            |

---

### validation_result

`validation_result` describes whether the cleaned lead is valid for analysis.

| Field | Type | Description |
|---|---|---|
| `is_valid` | boolean | Whether the lead passed domain validation. |
| `error_codes` | array of strings | Zero or more machine-readable validation errors. |

Allowed `error_codes` values:

```text
empty_email
invalid_email_format
empty_message_after_cleaning
```

Required invariants:

- `is_valid=true` requires `error_codes=[]`.
- `is_valid=false` requires at least one error code.

---

### Historical flat analysis_result (do not use)

`analysis_result` contains the unified lead analysis output.

It may come from either:

```text
llm
rule_fallback
```

| Field                |    Type | Description                                          |
| -------------------- | ------: | ---------------------------------------------------- |
| lead_type            |  string | Lead category: `B2B`, `B2C`, or `Unknown`.           |
| lead_subtype         |  string | More specific lead subtype.                          |
| intent_level         |  string | Intent level: `High`, `Medium`, `Low`, or `Unknown`. |
| lead_score           | integer | Lead score from 0 to 100.                            |
| lead_summary         |  string | Summary of the lead inquiry.                         |
| recommended_action   |  string | Recommended next action for the sales team.          |
| followup_email_draft |  string | Draft follow-up email for human review.              |
| analysis_method      |  string | Analysis source: `llm` or `rule_fallback`.           |
| confidence           |  number | Confidence score from 0 to 1.                        |

Allowed `lead_type` values:

```text
B2B
B2C
Unknown
```

Allowed `lead_subtype` values:

```text
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

Allowed `intent_level` values:

```text
High
Medium
Low
Unknown
```

Allowed `analysis_method` values:

```text
llm
rule_fallback
```

The current analysis contract will be refactored in later stages so the LLM cannot directly control final business scoring. This document does not claim that work is already complete.

---

### sources

`sources` is always present as an array. Each future source will use:

| Field | Type | Description |
|---|---|---|
| `chunk_id` | string | Public knowledge chunk identifier. |
| `source_title` | string | Sanitized source title. |
| `section` | string | Sanitized section name. |
| `rank` | integer | Retrieval rank from 1 to 3. |

At the current Day 2 stage, RAG has not yet been connected to `/process-lead`, so `sources` is an empty list. Real sanitized Top 3 sources are a Day 5 task.

---

## Invalid Lead Behavior

If the lead fails validation, the API still returns a `LeadProcessingResult`, but `analysis_result` will be `null`.

Example response:

```json
{
  "cleaned_lead": {
    "lead_id": "12345",
    "external_lead_id": "website-form-invalid-001",
    "name": "Bad Lead",
    "email": "invalid-email",
    "company_name": "Example Corp",
    "message": "I am interested in a China tour.",
    "source": "Website"
  },
  "validation_result": {
    "is_valid": false,
    "error_codes": [
      "invalid_email_format"
    ]
  },
  "analysis_result": null,
  "sources": []
}
```

Invalid leads must not enter analyzer, LLM, RAG, recommendation, or intent-level routing.

In n8n, invalid leads should be routed before accessing:

```text
analysis_result.intent_level
```

because `analysis_result` is `null` for invalid leads.

---

## Historical Day 2 rationale (superseded)

Earlier versions of the project returned `score_result`, which only represented rule-based scoring.

The current system returns `analysis_result` because lead analysis now includes more than scoring:

```text
lead_type
lead_subtype
intent_level
lead_score
lead_summary
recommended_action
followup_email_draft
analysis_method
confidence
```

`analysis_result` is the unified downstream contract.

It can be generated by:

```text
LLM analysis
Rule-based fallback
```

This allows n8n, Notion, and other CRM integrations to consume one stable response structure without caring whether the result came from the LLM or fallback rules.

---

## Historical Day 2 n8n paths (superseded)

n8n should use these fields:

```text
validation_result.is_valid
analysis_result.intent_level
analysis_result.analysis_method
analysis_result.lead_score
```

Recommended routing:

```text
IF validation_result.is_valid == false
→ Invalid branch

IF validation_result.is_valid == true
→ Switch analysis_result.intent_level
   → High
   → Medium
   → Low
```

Legacy input mapping must be explicit:

```text
company → company_name
```

The FastAPI contract does not silently perform this mapping.

Notion CRM should write from the standardized n8n fields generated after routing and preparation.

---

## Contract Rule

Downstream systems should not depend on internal service functions such as:

```text
clean_lead()
validate_lead()
score_lead()
analyze_lead()
```

They should only depend on the public API response contract:

```text
LeadProcessingResult
```

This keeps the workflow stable even if internal implementation details change.

The response contains cleaned email and message data, so the endpoint is currently intended for internal workflow use. Logs, reports, screenshots, and public examples must use sanitized data.

