# Grounded Recommendation

This document defines the current optional LLM recommendation boundary. The public API contract
does not gain new fields: successful output still uses `recommended_action`,
`followup_email_draft`, `metadata.recommendation_method`, and sanitized `sources`.

## Purpose

`PolicyV1` remains the only owner of lead score, intent, disposition, and review status. After the
decision is frozen, RAG may retrieve up to three chunks. An optional generator can then draft a
human-reviewed action and email using only that evidence.

```text
validated lead
-> constrained features
-> security signals
-> PolicyV1 freezes LeadDecision
-> Top 3 RAG retrieval
-> optional grounded recommendation
-> human review
```

The generator does not send email, call CRM tools, or alter `LeadDecision`.

## Configuration

The feature is disabled by default:

```text
GROUNDED_RECOMMENDATION_ENABLED=false
RECOMMENDATION_MAX_OUTPUT_TOKENS=1024
```

Enabling it requires all of the following:

```text
APP_MODE=live
ALLOW_NETWORK=true
LLM_PROVIDER=openai
OPENAI_API_KEY=<configured outside source control>
OPENAI_MODEL=<Structured Outputs capable model>
RAG_BACKEND=keyword_rrf or bge_rrf
GROUNDED_RECOMMENDATION_ENABLED=true
```

`RECOMMENDATION_MAX_OUTPUT_TOKENS` accepts 256–2048. The 1024 default is a generation budget, not
a target email length.

## Execution Gate

The model is called only when:

1. the optional generator exists;
2. `decision.disposition == "qualified"`;
3. `decision.needs_review == false`;
4. neither lead nor knowledge injection is suspected;
5. retrieval succeeded through `keyword_rrf` or `bge_rrf`;
6. at least one chunk was retrieved.

Spam, nurture, manual-review, invalid, injection-suspected, disabled-RAG, and unavailable-RAG
paths keep their deterministic behavior.

## Prompt and Data Boundary

English and Simplified Chinese system prompts contain equivalent rules. Known `en` and `zh`
features select their matching prompt. For `mixed`, a deterministic CJK/Latin character count
selects the dominant script; `unknown` defaults to English.

The user message contains bounded JSON with:

- customer name, company, message, and source;
- canonical features and the frozen policy decision;
- chunk ID, public title, section, rank, and text.

It excludes the lead email, internal lead IDs, external lead ID, Notion page ID, private source
path, and retrieval score.

Both lead content and chunk text are marked as untrusted. Embedded instructions are data and must
not be executed.

## Structured Output and Citation Validation

The private `GroundedRecommendationDraft` contains:

```text
recommended_action
followup_email_draft
cited_chunk_ids (1..3)
```

The API checks that citations are unique and that every ID belongs to the exact retrieved chunk
whitelist. A structurally valid but invented ID is rejected.

The citation list remains internal in v0.3.0. The existing public `sources` array continues to
expose only:

```text
chunk_id | source_title | section | rank
```

## Failure and Fallback

The OpenAI response boundary explicitly handles:

- incomplete responses, including output-token truncation;
- refusals nested inside message content;
- missing or invalid structured output;
- unknown or duplicate citations;
- timeout, rate limit, connection, authentication, and request failures.

Any runtime recommendation failure produces a safe structured log and returns the existing
deterministic template. It never changes the already-frozen decision. Configuration is validated
at startup.

The same incomplete/refusal response guard is also applied to live feature extraction.

## Evaluation

[`data/recommendation_eval/golden_cases.json`](../data/recommendation_eval/golden_cases.json)
contains 12 human-calibrated English, Chinese, and mixed-language cases. It covers unsupported
prices, availability promises, dates, permits, payment policy, embedded instructions, source
combination, and citation whitelisting.

Offline CI validates the dataset contract and all orchestration boundaries with fake clients. It
does not call OpenAI or claim model-quality scores. A real model run must be reviewed separately
against each case's required and forbidden behaviors.

## Source of Truth

- Prompt: `src/lead_cleaner/services/recommendation_prompt_builder.py`
- Private schema and protocol: `src/lead_cleaner/services/recommendation_generator.py`
- OpenAI client: `src/lead_cleaner/services/openai_recommendation_generator.py`
- Orchestration and fallback: `src/lead_cleaner/services/rag_grounding.py`
- Tests: `tests/test_openai_recommendation_generator.py`,
  `tests/test_rag_grounding.py`, and `tests/test_api_recommendation_integration.py`
