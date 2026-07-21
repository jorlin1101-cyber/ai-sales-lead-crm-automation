import json
import os

from openai import OpenAI
from pydantic import ValidationError

from lead_cleaner.schemas.policy import ExtractedLeadFeatures
from lead_cleaner.services.llm_errors import (
    LLMClientError,
    LLMConfigurationError,
    LLMInvalidJSONError,
    LLMSchemaValidationError,
)


def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL")

    if not api_key:
        raise LLMConfigurationError("OPENAI_API_KEY or DEEPSEEK_API_KEY is missing.")

    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)

    return OpenAI(api_key=api_key)


def get_openai_model() -> str:
    model = os.getenv("OPENAI_MODEL") or os.getenv("DEEPSEEK_MODEL")

    if not model:
        raise LLMConfigurationError("OPENAI_MODEL or DEEPSEEK_MODEL is missing.")

    return model


def is_deepseek_configured(model: str) -> bool:
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL") or ""
    return "deepseek" in base_url.lower() or model.lower().startswith("deepseek-")


def parse_json_extracted_features(raw_content: str) -> ExtractedLeadFeatures:
    """Parse provider JSON into the restricted feature-extraction contract."""

    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as error:
        raise LLMInvalidJSONError(f"LLM returned invalid feature JSON: {error}") from error

    try:
        return ExtractedLeadFeatures.model_validate(data)
    except ValidationError as error:
        raise LLMSchemaValidationError(
            f"LLM feature JSON failed schema validation: {error}"
        ) from error


def call_deepseek_structured_feature_extraction(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
) -> ExtractedLeadFeatures:
    """Request constrained lead features through DeepSeek JSON mode."""

    schema = json.dumps(ExtractedLeadFeatures.model_json_schema(), ensure_ascii=False)
    example = json.dumps(
        {
            "customer_kind": "agency",
            "group_size": 20,
            "mentions_specific_dates": True,
            "asks_for_price": True,
            "asks_for_availability": False,
            "requests_private_or_custom_service": True,
            "requests_partnership": False,
            "contains_spam_or_promotion": False,
            "destinations": ["Sichuan"],
            "language": "en",
        },
        ensure_ascii=False,
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"{user_prompt}\n\n"
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
            max_tokens=800,
        )
    except Exception as error:
        raise LLMClientError(f"DeepSeek structured feature extraction failed: {error}") from error

    choices = getattr(response, "choices", None)
    raw_content = choices[0].message.content if choices else None

    if not raw_content:
        raise LLMInvalidJSONError("DeepSeek returned empty structured feature output.")

    return parse_json_extracted_features(raw_content)


def call_openai_structured_feature_extraction(
    system_prompt: str,
    user_prompt: str,
) -> ExtractedLeadFeatures:
    """Call the configured provider and return only constrained lead features."""

    client = get_openai_client()
    model = get_openai_model()

    if is_deepseek_configured(model):
        return call_deepseek_structured_feature_extraction(
            client=client,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    try:
        response = client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text_format=ExtractedLeadFeatures,
        )
    except Exception as error:
        raise LLMClientError(f"OpenAI structured feature extraction failed: {error}") from error

    parsed_result = response.output_parsed
    if parsed_result is None:
        raise LLMInvalidJSONError("OpenAI returned empty structured feature output.")

    try:
        return ExtractedLeadFeatures.model_validate(parsed_result)
    except ValidationError as error:
        raise LLMSchemaValidationError(
            f"OpenAI feature output failed schema validation: {error}"
        ) from error
