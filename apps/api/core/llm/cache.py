"""Answer cache for scripted demo questions.

A JSON file (env ``LLM_CACHE_PATH``, default ``data/llm_cache.json``)::

    {"<sha256>": {"prompt": "...", "text": "...", "purpose": "chat"}}

The key is the SHA-256 of the normalised prompt: message contents joined,
lower-cased, whitespace collapsed (roles are ignored). The prompt may be a
string or a list of chat messages.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Union

Prompt = Union[str, list]

DEFAULT_CACHE_PATH = "data/llm_cache.json"


def normalise_prompt(prompt: Prompt) -> str:
    if isinstance(prompt, (list, tuple)):
        prompt = "\n".join(str(m.get("content", "")) for m in prompt)
    return re.sub(r"\s+", " ", str(prompt)).strip().lower()


def prompt_key(prompt: Prompt) -> str:
    return hashlib.sha256(normalise_prompt(prompt).encode("utf-8")).hexdigest()


class AnswerCache:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("LLM_CACHE_PATH") or DEFAULT_CACHE_PATH)
        self._data: dict | None = None

    def _load(self) -> dict:
        if self._data is None:
            try:
                with open(self.path, encoding="utf-8") as fh:
                    data = json.load(fh)
                self._data = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                self._data = {}
        return self._data

    def reload(self) -> None:
        self._data = None

    def get(self, prompt: Prompt) -> str | None:
        entry = self._load().get(prompt_key(prompt))
        if isinstance(entry, dict):
            return entry.get("text")
        return entry if isinstance(entry, str) else None

    def put(self, prompt: Prompt, text: str, purpose: str | None = None) -> None:
        data = self._load()
        data[prompt_key(prompt)] = {
            "prompt": normalise_prompt(prompt),
            "text": text,
            "purpose": purpose,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def __len__(self) -> int:
        return len(self._load())
