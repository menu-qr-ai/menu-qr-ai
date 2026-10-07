import json
import logging
import time

from openai import OpenAI, OpenAIError

from app.core.config import settings


logger = logging.getLogger("app.ai")


class OpenAIService:
    def __init__(self) -> None:
        self.client = (
            OpenAI(
                api_key=settings.openai_api_key,
                timeout=settings.openai_timeout_seconds,
                max_retries=settings.openai_max_retries,
            )
            if settings.openai_api_key
            else None
        )

    @property
    def is_configured(self) -> bool:
        return self.client is not None

    def json_completion(self, *, system: str, prompt: str) -> dict:
        if not self.client:
            return {"error": "No OPENAI_API_KEY"}

        started_at = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
        except OpenAIError as exc:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            # Only the exception class is logged: provider messages may echo request data.
            logger.warning(
                "openai_request_failed model=%s duration_ms=%s error=%s",
                settings.openai_model,
                duration_ms,
                type(exc).__name__,
            )
            return {"error": "AI service unavailable"}
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info(
            "openai_request_completed model=%s duration_ms=%s",
            settings.openai_model,
            duration_ms,
        )

        content = response.choices[0].message.content or "{}"
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.exception("openai_invalid_json_response")
            return {"error": "Invalid AI response"}
        if not isinstance(parsed, dict):
            return {"error": "Invalid AI response"}
        return parsed


openai_service = OpenAIService()
