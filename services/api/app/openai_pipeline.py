import json
from typing import Any

from app.config import settings


class OpenAIPipelineError(RuntimeError):
    pass


def openai_enabled() -> bool:
    return bool(settings.openai_api_key)


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    if not openai_enabled():
        raise OpenAIPipelineError("OPENAI_API_KEY is not configured.")

    OpenAI, OpenAIError = _load_openai()
    client = OpenAI(api_key=settings.openai_api_key)
    try:
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=texts,
        )
    except OpenAIError as exc:
        raise OpenAIPipelineError(f"OpenAI embedding request failed: {exc}") from exc
    return [item.embedding for item in response.data]


def generate_signal_json(prompt: dict[str, Any]) -> dict[str, Any]:
    if not openai_enabled():
        raise OpenAIPipelineError("OPENAI_API_KEY is not configured.")

    schema = {
        **prompt["json_schema"],
        "additionalProperties": False,
    }
    for property_schema in schema.get("properties", {}).values():
        if isinstance(property_schema, dict) and property_schema.get("type") == "array":
            item_schema = property_schema.get("items")
            if isinstance(item_schema, dict):
                item_schema.setdefault("additionalProperties", False)

    OpenAI, OpenAIError = _load_openai()
    client = OpenAI(api_key=settings.openai_api_key)
    try:
        response = client.responses.create(
            model=settings.openai_model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are LocalSignal's food intelligence analyst. "
                        "Use only the supplied JSON payload and return JSON only."
                    ),
                },
                {"role": "user", "content": json.dumps(prompt, default=str)},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "localsignal_signal_interpretation",
                    "schema": schema,
                    "strict": True,
                }
            },
        )
    except OpenAIError as exc:
        raise OpenAIPipelineError(f"OpenAI generation request failed: {exc}") from exc

    try:
        return json.loads(response.output_text)
    except (AttributeError, json.JSONDecodeError) as exc:
        raise OpenAIPipelineError("OpenAI generation did not return valid JSON.") from exc


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in values) + "]"


def _load_openai():
    try:
        from openai import OpenAI, OpenAIError
    except ImportError as exc:
        raise OpenAIPipelineError("The openai package is not installed. Run pip install -r services/api/requirements.txt.") from exc
    return OpenAI, OpenAIError
