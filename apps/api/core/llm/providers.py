"""LLM providers: many free OpenAI-compatible tiers, Claude via the Anthropic SDK, local Ollama.

* :class:`OpenAICompatibleProvider` - one small httpx client for every endpoint that
  exposes ``POST {base_url}/chat/completions`` (Gemini, Groq, Cerebras, SambaNova,
  Mistral, NVIDIA, GitHub Models, OpenRouter, Hugging Face, Ollama).
* :class:`AnthropicProvider` - Claude through the official ``anthropic`` SDK
  (imported lazily, so ``core.llm`` works without it installed). Paid.

Multiple keys per provider: ``<KEY>``, ``<KEY>_2`` ... ``<KEY>_9`` (e.g. ``GEMINI_API_KEY_2``).
Each key is a *bucket*. Calls round-robin across a provider's healthy buckets; on
429 / quota / 5xx / timeout / bad key the bucket cools down for ``LLM_COOLDOWN_SECONDS``
(default 60) and the next bucket is tried. When no bucket is healthy the provider
reports ``available == False`` and the gateway moves to the next provider.

Keys are read from environment variables at call time and are never logged or
put in error messages (only the env var *name* identifies a bucket).
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

Message = dict  # {"role": "system"|"user"|"assistant", "content": str}

DEFAULT_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "20"))
LOCAL_TIMEOUT = float(os.getenv("LLM_LOCAL_TIMEOUT", "90"))
MAX_KEYS = 9


def cooldown_seconds() -> float:
    try:
        return float(os.getenv("LLM_COOLDOWN_SECONDS", "60"))
    except ValueError:
        return 60.0


class ProviderError(Exception):
    """A single provider failed (HTTP error, 429, timeout, refusal, bad payload).

    ``cooldown`` = park this key bucket for ``LLM_COOLDOWN_SECONDS`` (429, quota,
    payment, rejected key, retired model, 5xx, timeout, connection error).
    ``retryable`` = another key of the *same* provider may succeed right now
    (429, quota, rejected key, 5xx). Timeouts cool the bucket but move on to the
    next provider, so a slow provider never costs ``keys x timeout``. Bad
    requests, refusals and bad replies skip straight to the next provider.
    """

    def __init__(self, provider: str, message: str, status: int | None = None,
                 retryable: bool | None = None, cooldown: bool | None = None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status = status
        if retryable is None:
            retryable = status is not None and (status in (401, 402, 403, 429) or status >= 500)
        if cooldown is None:
            cooldown = retryable or status is None or status in (404, 408, 410)
        self.retryable = retryable
        self.cooldown = cooldown


@dataclass
class Provider:
    """Static configuration for one endpoint."""

    name: str
    base_url: str
    default_model: str
    api_key_env: str | None = None  # None = no key needed (local)
    model_env: str | None = None
    base_url_env: str | None = None
    is_local: bool = False
    json_mode: bool = False  # send response_format={"type":"json_object"}
    timeout: float = DEFAULT_TIMEOUT
    timeout_env: str | None = None
    extra_headers: dict = field(default_factory=dict)
    paid: bool = False
    kind: str = "openai"  # "openai" (chat/completions) | "anthropic" (Messages API SDK)

    def key_envs(self) -> list[str]:
        """Env var names of every key bucket that is set (``<KEY>``, ``<KEY>_2`` .. ``_9``)."""
        if not self.api_key_env:
            return []
        names = [self.api_key_env] + [f"{self.api_key_env}_{i}" for i in range(2, MAX_KEYS + 1)]
        return [n for n in names if (os.getenv(n) or "").strip()]

    @property
    def api_key(self) -> str | None:
        envs = self.key_envs()
        return os.getenv(envs[0]).strip() if envs else None

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
    def request_timeout(self) -> float:
        if self.timeout_env:
            try:
                return float(os.getenv(self.timeout_env) or self.timeout)
            except ValueError:
                pass
        return self.timeout

    @property
    def available(self) -> bool:
        return self.api_key_env is None or bool(self.key_envs())


# ---------------------------------------------------------------- key buckets (shared state)

_state_lock = threading.Lock()
_cooling: dict[tuple[str, str], float] = {}  # (provider, key env name) -> monotonic expiry
_rr: dict[str, int] = {}  # provider -> round-robin counter


def _healthy(provider: str, envs: list[str]) -> list[str]:
    now = time.monotonic()
    with _state_lock:
        return [e for e in envs if _cooling.get((provider, e), 0.0) <= now]


def _cool_down(provider: str, env: str) -> None:
    with _state_lock:
        _cooling[(provider, env)] = time.monotonic() + cooldown_seconds()


def _rotate(provider: str, envs: list[str]) -> list[str]:
    if len(envs) < 2:
        return envs
    with _state_lock:
        i = _rr.get(provider, 0)
        _rr[provider] = i + 1
    i %= len(envs)
    return envs[i:] + envs[:i]


def reset_cooldowns() -> None:
    """Forget every cooldown and round-robin position (tests, settings reload)."""
    with _state_lock:
        _cooling.clear()
        _rr.clear()


class _KeyRotatingProvider:
    """Duck-typed interface used by the gateway (fakes only need these):
    ``name: str``, ``available: bool``, ``is_local: bool``,
    ``complete(messages, json_schema=None, timeout=None) -> str``.
    Subclasses implement ``_call(key, messages, json_schema, timeout)``.
    """

    def __init__(self, config: Provider):
        self.config = config

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def is_local(self) -> bool:
        return self.config.is_local

    @property
    def paid(self) -> bool:
        return self.config.paid

    @property
    def model(self) -> str:
        return self.config.model

    @property
    def keys(self) -> int:
        """Number of configured key buckets (never the keys themselves)."""
        return len(self.config.key_envs())

    @property
    def available(self) -> bool:
        if self.config.api_key_env is None:
            return True
        return bool(_healthy(self.name, self.config.key_envs()))

    def __repr__(self) -> str:  # never include a key
        return f"{type(self).__name__}({self.name}, model={self.config.model}, keys={self.keys})"

    def complete(
        self,
        messages: list[Message],
        json_schema: dict | None = None,
        timeout: float | None = None,
    ) -> str:
        cfg = self.config
        if cfg.api_key_env is None:
            return self._call(None, messages, json_schema, timeout)
        buckets = _rotate(self.name, _healthy(self.name, cfg.key_envs()))
        if not buckets:
            raise ProviderError(self.name, "no key configured or all keys cooling down", 429)
        last: ProviderError | None = None
        for env in buckets:
            key = (os.getenv(env) or "").strip()
            if not key:
                continue
            try:
                return self._call(key, messages, json_schema, timeout)
            except ProviderError as exc:
                last = exc
                if exc.cooldown:
                    _cool_down(self.name, env)  # this key is throttled/broken: park it
                if not exc.retryable:
                    raise
        raise last or ProviderError(self.name, "no usable key", 429)

    def _call(self, key: str | None, messages, json_schema, timeout) -> str:  # pragma: no cover
        raise NotImplementedError


class OpenAICompatibleProvider(_KeyRotatingProvider):
    """Calls ``/chat/completions`` for one :class:`Provider` config."""

    def _call(self, key, messages, json_schema, timeout) -> str:
        import httpx  # lazy: keeps import of core.llm cheap and test-friendly

        cfg = self.config
        headers = {"Content-Type": "application/json", **cfg.extra_headers}
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
                timeout=timeout or cfg.request_timeout,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(cfg.name, "timeout", retryable=False, cooldown=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(cfg.name, f"connection error: {type(exc).__name__}", retryable=False,
                                cooldown=True) from exc
        if resp.status_code == 429:
            raise ProviderError(cfg.name, "rate limited (429)", 429)
        if resp.status_code >= 400:
            raise ProviderError(cfg.name, f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)
        try:
            text = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ProviderError(cfg.name, "unexpected response shape", retryable=False, cooldown=True) from exc
        if not text or not str(text).strip():
            raise ProviderError(cfg.name, "empty reply", retryable=False, cooldown=False)
        return str(text)


class AnthropicProvider(_KeyRotatingProvider):
    """Claude through the official ``anthropic`` SDK (Messages API).

    Thinking is left at the model default (adaptive on Claude Opus 5.5);
    ``ANTHROPIC_EFFORT`` (default ``low``) is the speed/cost knob. A
    ``refusal`` stop reason raises :class:`ProviderError` so the gateway falls
    back to the next provider.
    """

    _clients: dict[str, Any] = {}
    _clients_lock = threading.Lock()

    def _client(self, key: str, timeout: float):
        import anthropic  # lazy: optional dependency

        cache_key = f"{id(self)}:{hash(key)}:{timeout}"
        with self._clients_lock:
            client = self._clients.get(cache_key)
            if client is None:
                # Retries are ours (next key / next provider), so the SDK does not retry.
                client = anthropic.Anthropic(api_key=key, max_retries=0, timeout=timeout)
                self._clients[cache_key] = client
        return client

    @staticmethod
    def _split(messages: list[Message], json_schema: dict | None) -> tuple[str, list[dict]]:
        system = [str(m.get("content", "")) for m in messages if m.get("role") == "system"]
        turns = [
            {"role": m.get("role"), "content": str(m.get("content", ""))}
            for m in messages
            if m.get("role") in ("user", "assistant")
        ]
        if json_schema is not None:
            system.append("Return only the JSON object: no prose, no code fences.")
        if not turns or turns[0]["role"] != "user":
            turns.insert(0, {"role": "user", "content": "(continue)"})
        return "\n\n".join(s for s in system if s.strip()), turns

    def _call(self, key, messages, json_schema, timeout) -> str:
        cfg = self.config
        try:
            import anthropic
        except ImportError as exc:
            raise ProviderError(cfg.name, "anthropic SDK not installed", retryable=False, cooldown=True) from exc
        system, turns = self._split(messages, json_schema)
        kwargs: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": 4096,
            "messages": turns,
            "output_config": {"effort": (os.getenv("ANTHROPIC_EFFORT") or "low").strip()},
        }
        if system:
            kwargs["system"] = system
        try:
            resp = self._client(key, timeout or cfg.request_timeout).messages.create(**kwargs)
        except anthropic.APITimeoutError as exc:
            raise ProviderError(cfg.name, "timeout", retryable=False, cooldown=True) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(cfg.name, f"connection error: {type(exc).__name__}", retryable=False,
                                cooldown=True) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderError(cfg.name, "rate limited (429)", 429) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(cfg.name, f"HTTP {exc.status_code}: {str(exc.message)[:200]}",
                                exc.status_code) from exc
        if resp.stop_reason == "refusal":
            category = getattr(getattr(resp, "stop_details", None), "category", None)
            raise ProviderError(cfg.name, f"refusal ({category or 'unspecified'})", retryable=False, cooldown=False)
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        if not text.strip():
            raise ProviderError(cfg.name, f"empty reply (stop_reason={resp.stop_reason})", retryable=False,
                                cooldown=False)
        if json_schema is not None:
            from .gateway import extract_json  # lazy: gateway imports this module

            try:
                extract_json(text)
            except ValueError as exc:
                raise ProviderError(cfg.name, "reply was not JSON", retryable=False, cooldown=False) from exc
        return text


# Every known provider. Model names change often: override via env.
PROVIDER_CONFIGS: dict[str, Provider] = {
    "anthropic": Provider(
        name="anthropic",
        base_url="https://api.anthropic.com",
        default_model="claude-opus-5-5",
        api_key_env="ANTHROPIC_API_KEY",
        model_env="ANTHROPIC_MODEL",
        timeout=60.0,
        timeout_env="ANTHROPIC_TIMEOUT",
        paid=True,
        kind="anthropic",
    ),
    "groq": Provider(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        default_model="openai/gpt-oss-120b",
        api_key_env="GROQ_API_KEY",
        model_env="GROQ_MODEL",
        json_mode=True,
    ),
    "cerebras": Provider(
        name="cerebras",
        base_url="https://api.cerebras.ai/v1",
        default_model="gpt-oss-120b",
        api_key_env="CEREBRAS_API_KEY",
        model_env="CEREBRAS_MODEL",
    ),
    "gemini": Provider(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        default_model="gemini-flash-latest",
        api_key_env="GEMINI_API_KEY",
        model_env="GEMINI_MODEL",
    ),
    "sambanova": Provider(
        name="sambanova",
        base_url="https://api.sambanova.ai/v1",
        default_model="Meta-Llama-3.3-70B-Instruct",
        api_key_env="SAMBANOVA_API_KEY",
        model_env="SAMBANOVA_MODEL",
    ),
    "mistral": Provider(
        name="mistral",
        base_url="https://api.mistral.ai/v1",
        default_model="mistral-small-latest",
        api_key_env="MISTRAL_API_KEY",
        model_env="MISTRAL_MODEL",
        json_mode=True,
    ),
    "nvidia": Provider(
        name="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        default_model="nvidia/nemotron-3.5-lightning-30b-a3b",
        api_key_env="NVIDIA_API_KEY",
        model_env="NVIDIA_MODEL",
    ),
    "github": Provider(
        name="github",
        base_url="https://models.github.ai/inference",
        default_model="openai/gpt-4.1-mini",
        api_key_env="GITHUB_MODELS_TOKEN",
        model_env="GITHUB_MODELS_MODEL",
    ),
    "openrouter": Provider(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        default_model="nvidia/nemotron-3.5-lightning:free",
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

# Default cloud order: Claude first when its key is set (most capable, paid), then the
# fastest free tiers. Override with LLM_ORDER (e.g. put free ones first to save money).
CLOUD_ORDER = [
    "anthropic", "groq", "cerebras", "gemini", "sambanova", "mistral",
    "nvidia", "github", "openrouter", "huggingface", "ollama",
]
LOCAL_ORDER = ["ollama"]


def cloud_order() -> list[str]:
    """``LLM_ORDER`` (comma list of provider names) or :data:`CLOUD_ORDER`. Unknown names are ignored."""
    raw = os.getenv("LLM_ORDER") or ""
    names = [n.strip().lower() for n in raw.split(",") if n.strip()]
    names = [n for n in dict.fromkeys(names) if n in PROVIDER_CONFIGS]
    return names or list(CLOUD_ORDER)


def make_provider(config: Provider) -> _KeyRotatingProvider:
    if config.kind == "anthropic":
        return AnthropicProvider(config)
    return OpenAICompatibleProvider(config)


def default_providers(mode: str = "cloud") -> list[_KeyRotatingProvider]:
    """Provider chain for ``mode`` ("cloud" or "local")."""
    order = LOCAL_ORDER if mode == "local" else cloud_order()
    return [make_provider(PROVIDER_CONFIGS[n]) for n in order]
