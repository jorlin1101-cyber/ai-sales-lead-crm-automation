# Day Review - LLM Client Testing

## What I built

Today I completed the LLM client layer and its unit tests.

## Key concepts

- `llm_client.py` only handles OpenAI API client logic.
- Business fallback logic should stay in a higher-level service.
- `LLMClientError` provides a unified error type for LLM client failures.
- Unit tests should not call the real OpenAI API.
- `monkeypatch.setattr()` can replace real functions with fake ones during tests.
- Fake classes only need to implement the attributes and methods used by the production code.
- `client.responses.parse(...)` returns a response object.
- `response.output_parsed` contains the parsed `LeadAnalysisResult`.

## Test design

The tests were derived from the execution path of `call_openai_structured_analysis()`:

1. Read client
2. Read model
3. Call `client.responses.parse(...)`
4. Read `response.output_parsed`
5. Raise error if parsed output is empty
6. Return parsed result if valid

## Important lesson

A unit test should verify my own code behavior, not the availability of external services.
