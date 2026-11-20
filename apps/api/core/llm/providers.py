"""OpenAI-compatible chat-completions providers (free tiers + local Ollama).

One small httpx client serves every provider, because Gemini, Groq, OpenRouter,
Hugging Face and Ollama all expose ``POST {base_url}/chat/completions``.

Keys are read from environment variables at call time and never logged.
A provider whose key env var is empty is ``available == False`` and is skipped
by the gateway.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

Message = dict  # {"role": "system"|"user"|"assistant", "content": str}

DEFAULT_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "20"))
LOCAL_TIMEOUT = float(os.getenv("LLM_LOCAL_TIMEOUT", "90"))


class ProviderError(Exception):
    """A single provider failed (HTTP error, 429, timeout, bad payload)."""

    def __init__(self, provider: str, message: str, status: int | None = None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status = status


@dataclass
class Provider:
    """Static configuration for one OpenAI-compatible endpoint."""

    name: str
    base_url: str
    default_model: str
    api_key_env: str | None = None  # None = no key needed (local)
    model_env: str | None = None
    base_url_env: str | None = None
    is_local: bool = False
    json_mode: bool = False  # send response_format={"type":"json_object"}
    timeout: float = DEFAULT_TIMEOUT
    extra_headers: dict = field(default_factory=dict)

    @property
    def api_key(self) -> str | None:
        if not self.api_key_env:
            return None
        return (os.getenv(self.api_key_env) or "").strip() or None

    @property
    def model(self) -> str:
        if self.model_env:
            return (os.getenv(self.model_env) or "").strip() or self.default_model
        return self.default_model

    @property
    def url(self) -> str:
        base = self.base_url
        if self.base_url_env:
            base = (os.getenv(self.base_url_env) or "").strip() or base
        return base.rstrip("/")

    @property
    def available(self) -> bool:
        return self.api_key_env is None or self.api_key is not None


class OpenAICompatibleProvider:
    """Calls ``/chat/completions`` for one :class:`Provider` config.

    Duck-typed interface used by the gateway (fakes only need these):
    ``name: str``, ``available: bool``, ``is_local: bool``,
    ``complete(messages, json_schema=None, timeout=None) -> str``.
    """

    def __init__(self, config: Provider):
        self.config = config

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def available(self) -> bool:
        return self.config.available

    @property
    def is_local(self) -> bool:
        return self.config.is_local

    def __repr__(self) -> str:  # never include the key
        return f"OpenAICompatibleProvider({self.name}, model={self.config.model})"

    def complete(
        self,
        messages: list[Message],
        json_schema: dict | None = None,
        timeout: float | None = None,
    ) -> str:
        import httpx  # lazy: keeps import of core.llm cheap and test-friendly

        cfg = self.config
        headers = {"Content-Type": "application/json", **cfg.extra_headers}
        key = cfg.api_key
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body: dict[str, Any] = {
            "model": cfg.model,
            "messages": messages,
            "temperature": 0.2,
        }
        if json_schema is not None and cfg.json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            resp = httpx.post(
                f"{cfg.url}/chat/completions",
                json=body,
                headers=headers,
                timeout=timeout or cfg.timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(cfg.name, "timeout") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(cfg.name, f"connection error: {type(exc).__name__}") from exc
        if resp.status_code == 429:
            raise ProviderError(cfg.name, "rate limited (429)", 429)
        if resp.status_code >= 400:
            raise ProviderError(cfg.name, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)
        try:
            text = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ProviderError(cfg.name, "unexpected response shape") from exc
        if not text or not str(text).strip():
            raise ProviderError(cfg.name, "empty reply")
        return str(text)


# Fallback order for cloud mode. Model names change often: override via env.
PROVIDER_CONFIGS: dict[str, Provider] = {
    "gemini": Provider(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        default_model="gemini-2.0-flash",
        api_key_env="GEMINI_API_KEY",
        model_env="GEMINI_MODEL",
    ),
    "groq": Provider(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        default_model="llama-3.3-70b-versatile",
        api_key_env="GROQ_API_KEY",
        model_env="GROQ_MODEL",
        json_mode=True,
    ),
    "openrouter": Provider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="meta-llama/llama-3.3-70b-instruct:free",
        api_key_env="OPENROUTER_API_KEY",
        model_env="OPENROUTER_MODEL",
        extra_headers={"X-Title": "pro-label-automation-demo"},
    ),
    "huggingface": Provider(
        name="huggingface",
        base_url="https://router.huggingface.co/v1",
        default_model="meta-llama/Llama-3.1-8B-Instruct",
        api_key_env="HF_TOKEN",
        model_env="HF_MODEL",
    ),
    "ollama": Provider(
        name="ollama",
        base_url="http://localhost:11434/v1",
        base_url_env="OLLAMA_URL",
        default_model="qwen2.5:3b",
        model_env="OLLAMA_MODEL",
        is_local=True,
        json_mode=True,
        timeout=LOCAL_TIMEOUT,
    ),
}

CLOUD_ORDER = ["gemini", "groq", "openrouter", "huggingface", "ollama"]
LOCAL_ORDER = ["ollama"]


def default_providers(mode: str = "cloud") -> list[OpenAICompatibleProvider]:
    """Provider chain for ``mode`` ("cloud" or "local")."""
    order = LOCAL_ORDER if mode == "local" else CLOUD_ORDER
    return [OpenAICompatibleProvider(PROVIDER_CONFIGS[n]) for n in order]
