"""Replace real client/vendor names with stable aliases before cloud calls.

``Anonymizer({"Acme Labels Pvt Ltd": "Client-017", "Sun Films": "Vendor-003"})``

* matching is case-insensitive, whole-word, longest name first;
* ``anonymize(text) -> (text, mapping)`` where ``mapping`` is ``{alias: real_name}``;
* ``restore(text, mapping)`` puts the real names back into the model reply.

The gateway applies it only in cloud mode (local Ollama sees real names).
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Union

NamesSource = Union[dict, Callable[[], dict]]


def _word_pattern(words: Iterable[str]) -> re.Pattern | None:
    words = sorted({w for w in words if w and w.strip()}, key=len, reverse=True)
    if not words:
        return None
    alt = "|".join(re.escape(w) for w in words)
    # (?<!\w)/(?!\w) instead of \b so names ending in "." or ")" still match.
    return re.compile(rf"(?<!\w)(?:{alt})(?!\w)", re.IGNORECASE)


def build_aliases(clients: Iterable[str] = (), vendors: Iterable[str] = ()) -> dict:
    """Helper: ``{name: "Client-001", ...}`` numbered in the given order."""
    out: dict[str, str] = {}
    for i, n in enumerate(clients, 1):
        out.setdefault(n, f"Client-{i:03d}")
    for i, n in enumerate(vendors, 1):
        out.setdefault(n, f"Vendor-{i:03d}")
    return out


class Anonymizer:
    def __init__(self, names: NamesSource):
        """``names`` is ``{real_name: alias}`` or a zero-arg loader returning it
        (called lazily once; call :meth:`refresh` to reload)."""
        self._source = names
        self._names: dict | None = None
        self._pattern: re.Pattern | None = None
        self._lookup: dict = {}

    def refresh(self) -> None:
        src = self._source() if callable(self._source) else self._source
        self._names = {str(k).strip(): str(v) for k, v in (src or {}).items() if str(k).strip()}
        self._lookup = {k.lower(): (k, v) for k, v in self._names.items()}
        self._pattern = _word_pattern(self._names)

    @property
    def names(self) -> dict:
        if self._names is None:
            self.refresh()
        return dict(self._names or {})

    def anonymize(self, text: str) -> tuple[str, dict]:
        if self._names is None:
            self.refresh()
        mapping: dict[str, str] = {}
        if not text or self._pattern is None:
            return text, mapping

        def sub(m: re.Match) -> str:
            real, alias = self._lookup[m.group(0).lower()]
            mapping[alias] = real
            return alias

        return self._pattern.sub(sub, text), mapping

    @staticmethod
    def restore(text: str, mapping: dict) -> str:
        if not text or not mapping:
            return text
        pattern = _word_pattern(mapping)
        lookup = {a.lower(): real for a, real in mapping.items()}
        return pattern.sub(lambda m: lookup[m.group(0).lower()], text)
