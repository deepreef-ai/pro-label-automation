"""LOCKED test 6: AI safety (SPEC 1 "LLM" row, SPEC 4b).

Gateway part: fallback chain, skipping, local mode, anonymisation, cache, JSON mode.
Chat part: `chat.tools` / `chat.service` never write through the API; the deterministic
router works when every LLM provider fails. `chat` is imported inside the tests so the
gateway tests run even before the chat module exists.

No network: every provider is a fake object.
"""
import json

import pytest

from core.llm.anonymizer import Anonymizer
from core.llm.cache import AnswerCache
from core.llm.gateway import LLMGateway, LLMUnavailable

pytestmark = pytest.mark.integration

REAL_NAMES = ["Fresh Juice Co.", "Sunrise Pharma"]


# ---- fakes ---------------------------------------------------------------------------------

class FakeProvider:
    """Records every call; answers with ``reply`` (str or callable(messages) -> str)."""

    def __init__(self, name, reply="ok", *, fail=False, available=True, is_local=False):
        self.name = name
        self.reply = reply
        self.fail = fail
        self.available = available
        self.is_local = is_local
        self.calls = []

    def complete(self, messages, json_schema=None, timeout=None):
        self.calls.append([dict(m) for m in messages])
        if self.fail:
            raise RuntimeError(f"{self.name} is down (429)")
        return self.reply(messages) if callable(self.reply) else self.reply

    def sent_text(self):
        return "\n".join(str(m.get("content", "")) for call in self.calls for m in call)


def down(name, **kw):
    return FakeProvider(name, fail=True, **kw)


def msgs(text):
    return [{"role": "user", "content": text}]


class FakeApi:
    """Stand-in for the public HTTP API client handed to chat tools. Records every call."""

    def __init__(self):
        self.gets = []
        self.posts = []
        self.puts = []

    def get(self, path, *a, **kw):
        self.gets.append(path)
        return {"items": [], "total": 0}

    def post(self, path, body=None, *a, **kw):
        self.posts.append((path, body))
        return {"detail": "should never be called"}

    def put(self, path, body=None, *a, **kw):
        self.puts.append((path, body))
        return {"detail": "should never be called"}

    def writes(self):
        return self.posts + self.puts


def all_down_gateway():
    return LLMGateway(
        providers=[down("gemini"), down("groq"), down("ollama", is_local=True)],
        mode="cloud",
        cache=False,
    )


# ---- gateway: fallback / skipping / local mode ---------------------------------------------

def test_fallback_to_next_provider_and_all_fail_raises():
    first, second = down("gemini"), FakeProvider("groq", "hello")
    gw = LLMGateway(providers=[first, second], mode="cloud", cache=False)
    res = gw.complete(msgs("hi"), purpose="chat")
    assert res.provider == "groq" and res.text == "hello" and not res.cached
    assert len(first.calls) == 1 and len(second.calls) == 1

    gw = LLMGateway(providers=[down("gemini"), down("groq")], mode="cloud", cache=False)
    with pytest.raises(LLMUnavailable) as exc:
        gw.complete(msgs("hi"), purpose="chat")
    assert [p for p, _ in exc.value.errors] == ["gemini", "groq"]


def test_unavailable_providers_skipped_and_local_mode_uses_only_local():
    no_key = FakeProvider("gemini", "from gemini", available=False)
    groq = FakeProvider("groq", "from groq")
    gw = LLMGateway(providers=[no_key, groq], mode="cloud", cache=False)
    assert gw.complete(msgs("hi"), purpose="chat").provider == "groq"
    assert no_key.calls == []

    cloud = FakeProvider("groq", "cloud answer")
    local = FakeProvider("ollama", "local answer", is_local=True)
    gw = LLMGateway(providers=[cloud, local], mode="local", cache=False)
    res = gw.complete(msgs("hi"), purpose="chat")
    assert res.provider == "ollama" and res.text == "local answer"
    assert cloud.calls == []

    gw = LLMGateway(providers=[FakeProvider("groq", "x")], mode="local", cache=False)
    with pytest.raises(LLMUnavailable):
        gw.complete(msgs("hi"), purpose="chat")


# ---- gateway: anonymisation ----------------------------------------------------------------

def test_cloud_mode_never_sends_real_client_names_and_restores_them():
    anon = Anonymizer({"Fresh Juice Co.": "Client-017", "Sunrise Pharma": "Client-018"})

    def echo_aliases(messages):
        text = messages[-1]["content"]
        assert "Client-017" in text and "Client-018" in text
        return "Client-017 is locked; Client-018 is fine."

    cloud = FakeProvider("gemini", echo_aliases)
    gw = LLMGateway(providers=[cloud], mode="cloud", cache=False, anonymizer=anon)
    question = "Why is Fresh Juice Co. locked but not Sunrise Pharma? (fresh juice co. again)"
    res = gw.complete(
        [{"role": "system", "content": "Clients: Fresh Juice Co., Sunrise Pharma"},
         {"role": "user", "content": question}],
        purpose="chat",
    )
    sent = cloud.sent_text().lower()
    for name in REAL_NAMES:
        assert name.lower() not in sent
    assert "fresh juice" not in sent and "sunrise" not in sent
    assert res.text == "Fresh Juice Co. is locked; Sunrise Pharma is fine."

    local = FakeProvider("ollama", "Fresh Juice Co. has an overdue invoice", is_local=True)
    gw = LLMGateway(providers=[local], mode="local", cache=False, anonymizer=anon)
    res = gw.complete(msgs(question), purpose="chat")
    assert "Fresh Juice Co." in local.sent_text()  # local model sees real names
    assert res.text == "Fresh Juice Co. has an overdue invoice"


# ---- gateway: cache and JSON mode ----------------------------------------------------------

def test_cache_hit_returns_cache_and_skips_provider(tmp_path):
    cache_file = tmp_path / "llm_cache.json"
    provider = FakeProvider("groq", "Debtors are on the Money screen.")
    gw = LLMGateway(providers=[provider], mode="cloud", cache=AnswerCache(cache_file), record=True)
    first = gw.complete(msgs("Who are my debtors?"), purpose="chat")
    assert first.provider == "groq" and len(provider.calls) == 1
    assert cache_file.exists()

    second = gw.complete(msgs("  who are   MY debtors? "), purpose="chat")
    assert second.provider == "cache" and second.cached is True
    assert second.text == first.text
    assert len(provider.calls) == 1

    # A fresh gateway reading the same file also answers from cache, with all providers down.
    gw2 = LLMGateway(providers=[down("groq")], mode="cloud", cache=AnswerCache(cache_file))
    assert gw2.complete(msgs("Who are my debtors?"), purpose="chat").provider == "cache"


def test_json_mode_parses_json_inside_prose():
    schema = {"type": "object", "required": ["intent", "to"],
              "properties": {"intent": {"type": "string"}, "to": {"type": "string"}}}
    reply = 'Sure! Here is the plan:\n```json\n{"intent": "navigate", "to": "/money"}\n```\nDone.'
    bad = FakeProvider("gemini", "I cannot answer in JSON, sorry.")
    good = FakeProvider("groq", reply)
    gw = LLMGateway(providers=[bad, good], mode="cloud", cache=False)
    res = gw.complete(msgs("show debtors"), purpose="chat", json_schema=schema)
    assert res.provider == "groq"
    assert res.data == {"intent": "navigate", "to": "/money"}


# ---- chat (SPEC 4b): built by task C1 ------------------------------------------------------

SAMPLE_ARGS = {
    "id": "JC-1301", "job_id": "JC-1301", "job_card": "JC-1301", "job_card_id": "JC-1301",
    "client": "Fresh Juice Co.", "client_name": "Fresh Juice Co.", "client_id": 1,
    "vendor": "Sun Films", "vendor_id": 1, "item": "BOPP 30mic", "item_id": 1,
    "query": "Fresh Juice Co.", "q": "Fresh Juice Co.", "text": "status", "screen": "money",
    "status": "open", "qty": 100, "quantity": 100, "date": "2026-11-20",
    "from": "2026-11-01", "to": "2026-11-20", "limit": 5, "reason": "demo",
}


def _make_ctx(role, api):
    from chat import tools as chat_tools

    ctx_cls = getattr(chat_tools, "ToolContext", None)
    if ctx_cls is None:
        from chat.service import ToolContext as ctx_cls
    return ctx_cls(role=role, api=api)


def _action_types(reply):
    return [a.get("type") for a in (reply.actions or [])]


def test_every_tool_is_read_or_draft():
    from chat.tools import TOOLS

    assert TOOLS, "chat.tools.TOOLS must not be empty"
    for key, tool in TOOLS.items():
        assert tool.mode in {"read", "draft"}, f"{key}: mode {tool.mode!r}"
        assert tool.name and tool.description
    assert any(t.mode == "draft" for t in TOOLS.values()), "at least one draft tool expected"


def test_tools_never_write_and_drafts_have_shape():
    from chat.tools import TOOLS

    for role in ("owner", "store"):
        for key, tool in TOOLS.items():
            api = FakeApi()
            ctx = _make_ctx(role, api)
            if tool.mode == "draft":
                out = tool.run(dict(SAMPLE_ARGS), ctx)
                assert isinstance(out, dict), key
                assert out.get("type") == "draft", f"{key}: {out!r}"
                assert isinstance(out.get("endpoint"), str) and out["endpoint"].startswith("/api"), key
                assert isinstance(out.get("body"), dict), key
                assert isinstance(out.get("summary"), str) and out["summary"], key
                json.dumps(out)  # must be JSON-serialisable for the UI
            else:
                try:
                    out = tool.run(dict(SAMPLE_ARGS), ctx)
                except Exception:  # a read tool may reject sample args; it still must not write
                    out = None
                if out is not None:
                    assert isinstance(out, dict), key
            assert api.writes() == [], f"tool {key} ({tool.mode}) wrote: {api.writes()}"


def test_answer_open_job_card_deterministic_fallback():
    from chat.service import answer

    api = FakeApi()
    reply = answer("open JC-1301", gateway=all_down_gateway(), api=api)
    assert isinstance(reply.reply, str)
    assert {"type": "navigate", "to": "/jobs/JC-1301"} in [
        {"type": a.get("type"), "to": a.get("to")} for a in reply.actions
    ]
    assert isinstance(reply.sources, list)
    assert api.writes() == []


def test_answer_show_debtors_navigates_to_money():
    from chat.service import answer

    api = FakeApi()
    reply = answer("show debtors", gateway=all_down_gateway(), api=api)
    assert any(a.get("type") == "navigate" and a.get("to") == "/money" for a in reply.actions)
    assert api.writes() == []


def test_release_lock_request_as_store_never_writes():
    from chat.service import answer

    prompt = "release the lock for Fresh Juice Co."
    # 1) no LLM at all, 2) an LLM that tries to make the app act directly.
    hostile = FakeProvider("groq", json.dumps({
        "reply": "Done, lock released.",
        "tool": "release_lock", "args": {"client": "Client-017"},
        "actions": [{"type": "execute", "method": "POST",
                     "endpoint": "/api/clients/1/release-lock", "body": {}}],
    }))
    gateways = [all_down_gateway(),
                LLMGateway(providers=[hostile], mode="cloud", cache=False)]
    for gw in gateways:
        api = FakeApi()
        reply = answer(prompt, role="store", gateway=gw, api=api)
        assert api.writes() == [], f"chat wrote through the API: {api.writes()}"
        for action in reply.actions:
            # Only drafts (user confirms in UI) or harmless navigation; nothing executed.
            assert action.get("type") in {"draft", "navigate"}, action
            if action.get("type") == "draft":
                assert set(action) >= {"endpoint", "body", "summary"}
