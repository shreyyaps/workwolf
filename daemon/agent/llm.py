import asyncio
import json
import os
import re
from contextvars import ContextVar, Token
from typing import Any


class AgentDependencyError(RuntimeError):
    pass


_REQUEST_API_KEY: ContextVar[str | None] = ContextVar(
    "wolfie_gemini_api_key",
    default=None,
)
_REQUEST_MODEL: ContextVar[str | None] = ContextVar(
    "wolfie_gemini_model",
    default=None,
)
_REQUEST_THINKING_LEVEL: ContextVar[str | None] = ContextVar(
    "wolfie_gemini_thinking_level",
    default=None,
)

DEFAULT_GEMINI_MODEL = "gemini-flash-latest"


def set_request_api_key(api_key: str | None) -> Token[str | None]:
    clean_key = api_key.strip() if isinstance(api_key, str) else None
    return _REQUEST_API_KEY.set(clean_key or None)


def reset_request_api_key(token: Token[str | None]) -> None:
    _REQUEST_API_KEY.reset(token)


def set_request_model(model: str | None) -> Token[str | None]:
    clean_model = model.strip() if isinstance(model, str) else None
    return _REQUEST_MODEL.set(clean_model or None)


def reset_request_model(token: Token[str | None]) -> None:
    _REQUEST_MODEL.reset(token)


def set_request_thinking_level(thinking_level: str | None) -> Token[str | None]:
    clean_level = thinking_level.strip() if isinstance(thinking_level, str) else None
    return _REQUEST_THINKING_LEVEL.set(clean_level or None)


def reset_request_thinking_level(token: Token[str | None]) -> None:
    _REQUEST_THINKING_LEVEL.reset(token)


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        stripped = stripped[start : end + 1]
    return json.loads(stripped)


class GeminiClient:
    def __init__(self, api_key: str | None = None) -> None:
        try:
            from google import genai
            from google.genai import types
        except ModuleNotFoundError as exc:
            raise AgentDependencyError(
                "Missing google-genai. Run `uv sync` or `uv add google-genai`."
            ) from exc

        self._genai = genai
        self._types = types
        request_api_key = api_key or _REQUEST_API_KEY.get()
        if request_api_key:
            self._client = genai.Client(api_key=request_api_key)
        else:
            self._client = genai.Client()
        self.model = (
            _REQUEST_MODEL.get()
            or os.getenv("WOLFIE_GEMINI_MODEL")
            or DEFAULT_GEMINI_MODEL
        )
        self.thinking_level = (
            _REQUEST_THINKING_LEVEL.get()
            or os.getenv("WOLFIE_GEMINI_THINKING_LEVEL")
            or "HIGH"
        )

    def _generate_text_sync(self, prompt: str) -> str:
        config_kwargs: dict[str, Any] = {}
        thinking_level = getattr(
            self._types.ThinkingLevel,
            self.thinking_level.upper(),
            self._types.ThinkingLevel.HIGH,
        )
        config_kwargs["thinking_config"] = self._types.ThinkingConfig(
            thinking_level=thinking_level
        )

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._types.GenerateContentConfig(**config_kwargs),
            )
        except Exception as exc:
            raise RuntimeError(
                f"Gemini request failed for model {self.model!r}: {exc}"
            ) from exc
        return response.text or ""

    async def generate_json(self, prompt: str) -> dict[str, Any]:
        text = await asyncio.to_thread(self._generate_text_sync, prompt)
        try:
            return _extract_json(text)
        except Exception as exc:
            raise RuntimeError(f"Gemini returned non-JSON output: {text[:1000]}") from exc
