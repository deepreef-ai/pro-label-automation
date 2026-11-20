"""The single entry point for every model call in the app.

    from core.llm import get_gateway, LLMUnavailable
    try:
        res = get_gateway().complete(messages, purpose="chat")
    except LLMUnavailable:
        ...  # deterministic fallback

Flow of ``complete``: answer cache -> anonymize (cloud mode only) -> provider
chain in order (skip unavailable, on any error/timeout/429 try the next) ->
restore names -> optional JSON extraction/validation. If every provider fails,
``LLMUnavailable`` is raised. The LLM never computes money or stock.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from .anonymizer import Anonymizer
from .cache import AnswerCache
from .providers import default_providers

log = logging.getLogger(__name__)

MODES = ("cloud", "local")


class LLMError(Exception):
    """Base class for gateway errors."""


class LLMUnavailable(LLMError):
    """No provider could answer. ``errors`` lists ``(provider, message)``."""

    def __init__(self, message: str = "no LLM provider available", errors: list | None = None):
        super().__init__(message)
        self.errors = errors or []


@dataclass
class LLMResult:
    text: str
    provider: str  # provider name, or "cache"
    cached: bool = False
    data: Any = None  # parsed JSON when json_schema was given
    errors: list = field(default_factory=list)  # failures before success


# ---------------------------------------------------------------- JSON helpers

def extract_json(text: str) -> Any:
    """Leniently return the first JSON object (or array) found in ``text``.

    Handles ```json fences and prose around the JSON. Raises ``ValueError``.
    """
    if text is None:
        raise ValueError("no text")
    s = str(text).strip()
    try:
        return json.loads(s)
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    for opener in ("{", "["):
        i = s.find(opener)
        while i != -1:
            try:
                obj, _ = decoder.raw_decode(s, i)
                return obj
            except ValueError:
                i = s.find(opener, i + 1)
    raise ValueError("no JSON object found in reply")


_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "integer": int, "number": (int, float), "null": type(None),
}


def validate_json(data: Any, schema: dict | None) -> None:
    """Lenient check: top-level type, ``required`` keys, property types.
    Raises ``ValueError``. Unknown keywords are ignored."""
    if not schema:
        return
    expected = schema.get("type")
    if isinstance(expected, str) and expected in _TYPES:
        if expected in ("integer", "number") and isinstance(data, bool):
            raise ValueError(f"expected {expected}")
        if not isinstance(data, _TYPES[expected]):
            raise ValueError(f"expected {expected}, got {type(data).__name__}")
    if isinstance(data, dict):
        missing = [k for k in schema.get("required", []) if k not in data]
        if missing:
            raise ValueError(f"missing keys: {missing}")
        for key, sub in (schema.get("properties") or {}).items():
            if key in data and isinstance(sub, dict) and data[key] is not None:
                validate_json(data[key], sub)


def _json_instruction(schema: dict) -> dict:
    return {
        "role": "system",
        "content": (
            "Reply with ONLY one valid JSON object, no prose and no code fences. "
            "It must match this JSON schema:\n" + json.dumps(schema, ensure_ascii=False)
        ),
    }


# ---------------------------------------------------------------- gateway

class LLMGateway:
    def __init__(
        self,
        providers: list | None = None,
        mode: str | None = None,
        cache: AnswerCache | bool | None = None,
        anonymizer: Anonymizer | None = None,
        cache_purposes: Iterable[str] | None = None,
        record: bool | None = None,
    ):
        """
        providers: ordered chain (objects with ``name``, ``available``,
            ``complete(messages, json_schema=None, timeout=None) -> str``,
            optional ``is_local``). Default: built from ``mode``.
        mode: "cloud" | "local"; default env ``AI_MODE`` or "cloud".
        cache: AnswerCache, True/None = default file cache, False = off.
        anonymizer: applied to outgoing messages in cloud mode only.
        cache_purposes: purposes that may be answered from cache; None = all.
        record: also store live answers in the cache (env ``LLM_CACHE_RECORD=1``).
        """
        self.mode = (mode or os.getenv("AI_MODE") or "cloud").strip().lower()
        if self.mode not in MODES:
            raise ValueError(f"AI mode must be one of {MODES}, got {self.mode!r}")
        self._custom_providers = providers is not None
        self.providers = list(providers) if providers is not None else default_providers(self.mode)
        if cache is False:
            self.cache = None
        elif cache is None or cache is True:
            self.cache = AnswerCache()
        else:
            self.cache = cache
        self.anonymizer = anonymizer
        self.cache_purposes = set(cache_purposes) if cache_purposes is not None else None
        if record is None:
            record = os.getenv("LLM_CACHE_RECORD", "").strip() in ("1", "true", "yes")
        self.record = record

    # -- configuration

    def set_mode(self, mode: str) -> None:
        """Switch cloud/local at runtime (e.g. after PUT /api/settings)."""
        mode = mode.strip().lower()
        if mode not in MODES:
            raise ValueError(f"AI mode must be one of {MODES}")
        self.mode = mode
        if not self._custom_providers:
            self.providers = default_providers(mode)

    def chain(self) -> list:
        """Providers that will be tried, in order (local mode = local only)."""
        if self.mode == "local":
            return [p for p in self.providers if _is_local(p)]
        return list(self.providers)

    def status(self) -> list[dict]:
        return [
            {"name": p.name, "available": _available(p), "local": _is_local(p)}
            for p in self.chain()
        ]

    # -- main call

    def complete(
        self,
        messages: list | str,
        *,
        purpose: str,
        json_schema: dict | None = None,
        cache: bool = True,
        timeout: float | None = None,
    ) -> LLMResult:
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        messages = [dict(m) for m in messages]

        use_cache = (
            cache and self.cache is not None
            and (self.cache_purposes is None or purpose in self.cache_purposes)
        )
        if use_cache:
            hit = self.cache.get(messages)
            if hit is not None:
                try:
                    data = self._parse(hit, json_schema)
                    return LLMResult(text=hit, provider="cache", cached=True, data=data)
                except ValueError:
                    log.warning("cached answer for purpose=%s failed JSON check; ignoring", purpose)

        out_messages = messages
        if json_schema is not None:
            out_messages = [_json_instruction(json_schema)] + out_messages

        errors: list = []
        for provider in self.chain():
            name = getattr(provider, "name", type(provider).__name__)
            if not _available(provider):
                continue
            mapping: dict = {}
            send = out_messages
            if self.anonymizer is not None and self.mode == "cloud" and not _is_local(provider):
                send, mapping = self._anonymize(out_messages)
            try:
                raw = provider.complete(send, json_schema=json_schema, timeout=timeout)
                text = Anonymizer.restore(raw, mapping) if mapping else raw
                data = self._parse(text, json_schema)
            except Exception as exc:  # error, timeout, 429, bad JSON -> next
                log.warning("LLM provider %s failed (purpose=%s): %s", name, purpose, exc)
                errors.append((name, str(exc)))
                continue
            if use_cache and self.record:
                try:
                    self.cache.put(messages, text, purpose)
                except OSError as exc:
                    log.warning("could not write LLM cache: %s", exc)
            return LLMResult(text=text, provider=name, cached=False, data=data, errors=errors)

        raise LLMUnavailable(
            "all LLM providers failed" if errors else "no LLM provider configured", errors
        )

    # -- helpers

    def _anonymize(self, messages: list) -> tuple[list, dict]:
        mapping: dict = {}
        out = []
        for m in messages:
            m = dict(m)
            if isinstance(m.get("content"), str):
                m["content"], found = self.anonymizer.anonymize(m["content"])
                mapping.update(found)
            out.append(m)
        return out, mapping

    @staticmethod
    def _parse(text: str, json_schema: dict | None) -> Any:
        if json_schema is None:
            return None
        data = extract_json(text)
        validate_json(data, json_schema)
        return data


def _available(p) -> bool:
    return bool(getattr(p, "available", True))


def _is_local(p) -> bool:
    return bool(getattr(p, "is_local", False)) or getattr(p, "name", "") == "ollama"


# ---------------------------------------------------------------- singleton

_gateway: LLMGateway | None = None
_lock = threading.Lock()


def get_gateway() -> LLMGateway:
    """Process-wide gateway built from env on first use."""
    global _gateway
    if _gateway is None:
        with _lock:
            if _gateway is None:
                _gateway = LLMGateway()
    return _gateway


def set_gateway(gateway: LLMGateway | None) -> None:
    """Replace (or with ``None`` reset) the singleton, e.g. in tests."""
    global _gateway
    with _lock:
        _gateway = gateway
