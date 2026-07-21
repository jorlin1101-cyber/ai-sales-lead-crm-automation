# LLM Provider Configuration

> **Historical configuration notes:** examples using `llm`, `rule_fallback`, or the old flat analysis result describe the pre-Day-3 implementation. Current feature extraction uses `ExtractedLeadFeatures`; Day 4 will finalize runtime modes and provider provenance.

## Overview

This project supports an LLM-first lead analysis strategy with rule-based fallback.

The lead analysis layer can use:

```text
OpenAI
DeepSeek
Rule-based fallback
```

The main output schema is:

```text
LeadAnalysisResult
```

Downstream systems such as n8n and Notion should consume `analysis_result` only. They should not depend on the internal provider implementation.

---

## Current LLM Flow

The current lead analysis flow is:

```text
CleanedLead
→ build_lead_analysis_prompt()
→ call LLM provider
→ parse JSON output
→ validate with LeadAnalysisResult
→ return analysis_result
```

If the LLM path succeeds:

```text
analysis_method = llm
```

If the LLM path fails:

```text
analysis_method = rule_fallback
```

Failure cases include:

```text
missing API key
missing model name
network or proxy error
provider API error
invalid JSON response
Pydantic schema validation failure
empty LLM output
```

---

## Environment Variables

### DeepSeek

Use these environment variables when running the project with DeepSeek:

```powershell
$env:DEEPSEEK_API_KEY="your-deepseek-api-key"
$env:DEEPSEEK_BASE_URL="https://api.deepseek.com"
$env:DEEPSEEK_MODEL="deepseek-v4-flash"
```

If a local proxy is required:

```powershell
$env:HTTP_PROXY="http://127.0.0.1:12000"
$env:HTTPS_PROXY="http://127.0.0.1:12000"
$env:ALL_PROXY="http://127.0.0.1:12000"
$env:NO_PROXY="127.0.0.1,localhost"
```

`NO_PROXY` is important because local FastAPI requests should not be routed through the proxy.

Example local FastAPI URL:

```text
http://127.0.0.1:8000/process-lead
```

---

### OpenAI

Use these environment variables when running the project with OpenAI:

```powershell
$env:OPENAI_API_KEY="your-openai-api-key"
$env:OPENAI_MODEL="your-openai-model"
```

If a custom OpenAI-compatible endpoint is needed:

```powershell
$env:OPENAI_BASE_URL="your-provider-base-url"
```

---

## Why DeepSeek Requires `base_url`

The OpenAI Python SDK sends requests to the OpenAI API by default.

DeepSeek provides an OpenAI-compatible API interface, but the SDK must be explicitly configured to send requests to DeepSeek.

For DeepSeek, the client must use:

```python
OpenAI(
    api_key=deepseek_api_key,
    base_url="https://api.deepseek.com",
)
```

Without `base_url`, the SDK will not correctly target the DeepSeek API service.

This was the root cause of the earlier fallback behavior: the project had a DeepSeek key and model, but the client was still configured like a pure OpenAI client.

---

## OpenAI Structured Outputs vs DeepSeek JSON Mode

### OpenAI Structured Outputs

OpenAI Structured Outputs allow the model response to follow a supplied JSON Schema.

In this project, the OpenAI path can use a schema-based structured output approach, where the model output is expected to match the `LeadAnalysisResult` schema more strictly.

This reduces the risk of:

```text
missing required fields
invalid enum values
wrong field types
out-of-range numbers
```

---

### DeepSeek JSON Mode

DeepSeek JSON Output uses:

```python
response_format={"type": "json_object"}
```

This guides the model to return valid JSON.

However, valid JSON does not guarantee valid business schema.

For example, this is valid JSON:

```json
{
  "intent_level": "high",
  "confidence": "0.9"
}
```

But it is invalid for this project because:

```text
intent_level must be one of: High, Medium, Low, Unknown
confidence must be a number between 0 and 1
```

Therefore, the DeepSeek path must use:

```text
JSON mode
→ json.loads()
→ LeadAnalysisResult.model_validate()
→ fallback if validation fails
```

---

## Why Pydantic Validation Is Required

LLM output must not be written directly into CRM.

The system validates LLM output before it reaches n8n or Notion.

The validation chain is:

```text
LLM raw response
→ JSON parsing
→ Pydantic validation
→ LeadAnalysisResult
→ LeadProcessingResult.analysis_result
→ n8n routing
→ Notion CRM
```

Pydantic protects the CRM from:

```text
missing fields
invalid enum values
wrong field types
invalid lead_score range
invalid confidence range
empty required text fields
malformed JSON
```

If validation fails, the system raises `LLMClientError`.

The upper analysis layer catches this error and returns a rule-based fallback result.

---

## Fallback Strategy

The system treats LLM providers as unreliable external services.

The lead analyzer follows this strategy:

```text
Try LLM analysis
→ if successful, return LeadAnalysisResult with analysis_method = llm
→ if LLMClientError occurs, return rule-based fallback LeadAnalysisResult
```

Fallback can be triggered by:

```text
API failure
network timeout
proxy failure
invalid model
invalid JSON
schema validation error
empty response
```

The fallback result still uses the same output schema:

```text
LeadAnalysisResult
```

This keeps downstream workflow stable.

n8n and Notion always consume:

```text
analysis_result
```

They do not need to know whether the result came from:

```text
llm
rule_fallback
```

---

## Why `analysis_result` Is the Stable Output Contract

Earlier versions of the project returned:

```text
score_result
```

That only represented rule-based scoring.

The current project returns:

```text
analysis_result
```

because the analysis now includes:

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

This makes the API response useful for:

```text
CRM writing
sales review
lead prioritization
email draft generation
fallback tracking
LLM quality evaluation
```

---

## Manual LLM Validation Command

After setting environment variables and starting FastAPI, test the LLM path manually:

```powershell
$body = @{
    name = "Maria Garcia"
    email = "maria@example.com"
    company_name = "Spain Travel Agency"
    message = "We want a quotation for a 20 people private custom China tour in September. Please help us plan the itinerary and price."
    source = "manual-llm-test"
} | ConvertTo-Json

$response = Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/process-lead" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body

$response.analysis_result.analysis_method
$response.analysis_result | ConvertTo-Json -Depth 10
```

Expected result:

```text
llm
```

The returned `analysis_result` must include:

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

---

## Validation Checklist

Before running the full n8n workflow, verify:

```text
pytest passes
FastAPI /health returns {"status": "ok"}
manual /process-lead test returns analysis_method = llm
LLM output fields are complete
LLM output passes LeadAnalysisResult validation
no API keys are committed to files
```

Current validated result:

```text
pytest: 104 passed, 1 warning
manual LLM test analysis_method: llm
n8n full LLM workflow: passed
valid leads analysis_method: llm
Notion Lead CRM write: passed
Processing Log write: passed
```

---

## Security Rules

Never commit API keys.

Do not write provider keys into:

```text
source code
README
run-summary.md
test files
Notion pages
screenshots
```

Use environment variables instead.

For local development, environment variables can be set in PowerShell before starting FastAPI.

For deployment, use a secure environment variable system provided by the hosting platform.
