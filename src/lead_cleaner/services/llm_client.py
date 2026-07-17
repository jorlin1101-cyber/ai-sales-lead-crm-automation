import json
import os

from openai import OpenAI
from pydantic import ValidationError

from lead_cleaner.schemas.ai_output import LeadAnalysisResult


class LLMClientError(Exception):
    """Raised when the LLM client fails to return a valid result."""

def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL")

    if not api_key:
        raise LLMClientError("OPENAI_API_KEY or DEEPSEEK_API_KEY is missing.")

    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)

    return OpenAI(api_key=api_key)


def get_openai_model() -> str:
    model = os.getenv("OPENAI_MODEL") or os.getenv("DEEPSEEK_MODEL")

    if not model:
        raise LLMClientError("OPENAI_MODEL or DEEPSEEK_MODEL is missing.")

    return model


def is_deepseek_configured(model: str) -> bool:
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL") or ""
    return "deepseek" in base_url.lower() or model.lower().startswith("deepseek-")


def parse_json_analysis_result(raw_content: str) -> LeadAnalysisResult:
    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as error:
        raise LLMClientError(f"LLM returned invalid JSON: {error}") from error

    try:
        return LeadAnalysisResult.model_validate(data)
    except ValidationError as error:
        raise LLMClientError(f"LLM JSON failed schema validation: {error}") from error


def call_deepseek_structured_analysis(client: OpenAI, model: str, prompt: str) -> LeadAnalysisResult:
    schema = json.dumps(LeadAnalysisResult.model_json_schema(), ensure_ascii=False)
    example = json.dumps(
        {
            "lead_type": "B2B",
            "lead_subtype": "Agency",
            "intent_level": "High",
            "lead_score": 88,
            "lead_summary": "A travel agency lead is asking for a custom China itinerary for a 20-person group.",
            "recommended_action": "Review the lead and prepare a tailored follow-up asking for missing trip details.",
            "followup_email_draft": "Thank you for your inquiry. We would be happy to help plan your China itinerary.",
            "analysis_method": "llm",
            "confidence": 0.9,
        },
        ensure_ascii=False,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an AI sales lead analyst. Return only one valid JSON object. "
                        "Do not use Markdown or code fences. Use enum values exactly as provided. "
                        "Use numbers for lead_score and confidence."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        "Return JSON that validates against this JSON Schema:\n"
                        f"{schema}\n\n"
                        "Example of the exact shape and value style:\n"
                        f"{example}\n\n"
                        "Return only the final JSON object."
                    ),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=1200,
        )
    except Exception as error:
        raise LLMClientError(f"DeepSeek structured analysis failed: {error}") from error

    raw_content = response.choices[0].message.content if response.choices else None

    if not raw_content:
        raise LLMClientError("DeepSeek returned empty structured output.")

    return parse_json_analysis_result(raw_content)


def call_openai_structured_analysis(prompt: str) -> LeadAnalysisResult:
    """
    Call the configured LLM and return a LeadAnalysisResult.

    This function only handles the LLM API call.
    Business fallback logic should not be placed here.
    """
    client = get_openai_client()
    model = get_openai_model()

    if is_deepseek_configured(model):
        return call_deepseek_structured_analysis(client, model, prompt)

    try:
        response = client.responses.parse(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": "You are an AI sales lead analyst. Return only structured output.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            text_format=LeadAnalysisResult,
        )
    except Exception as error:
        raise LLMClientError(f"OpenAI structured analysis failed: {error}") from error

    parsed_result = response.output_parsed

    if not parsed_result:
        raise LLMClientError("OpenAI returned empty structured output.")

    return parsed_result



