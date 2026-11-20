# core.llm — LLM gateway (free AI only)

Every model call goes through `get_gateway().complete(messages, purpose=..., json_schema=None)`,
which returns `LLMResult(text, provider, cached, data)` or raises `LLMUnavailable`
(callers then use a deterministic fallback). The LLM never computes money or stock.
One small httpx client talks to every provider (all are OpenAI-compatible); no SDKs.

## Providers and env vars

| Provider | Base URL | Key env | Model (env override) |
|---|---|---|---|
| gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `GEMINI_API_KEY` | `gemini-2.0-flash` (`GEMINI_MODEL`) |
| groq | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` | `llama-3.3-70b-versatile` (`GROQ_MODEL`) |
| openrouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | `meta-llama/llama-3.3-70b-instruct:free` (`OPENROUTER_MODEL`) |
| huggingface | `https://router.huggingface.co/v1` | `HF_TOKEN` | `meta-llama/Llama-3.1-8B-Instruct` (`HF_MODEL`) |
| ollama (local) | `OLLAMA_URL` (default `http://localhost:11434/v1`) | none | `qwen2.5:3b` (`OLLAMA_MODEL`) |

Free model names change; override with the env vars above. A provider with no key is skipped.

Other env: `AI_MODE` (`cloud` default | `local`), `LLM_TIMEOUT` (cloud seconds, 20),
`LLM_LOCAL_TIMEOUT` (Ollama seconds, 90), `LLM_CACHE_PATH` (default `data/llm_cache.json`),
`LLM_CACHE_RECORD=1` (save live answers into the cache). Keys live only in your local `.env`/shell, never in git.

## Fallback order

- `cloud`: gemini -> groq -> openrouter -> huggingface -> ollama
- `local`: ollama only

On error, timeout, 429 or an unparseable JSON reply the next provider is tried.
If all fail: `LLMUnavailable` (`.errors` = list of `(provider, message)`).

## Cache

For scripted demo questions the gateway first checks the answer cache
(`AnswerCache`, key = SHA-256 of the lower-cased, whitespace-collapsed message
contents). Hits return `provider="cache", cached=True`. Restrict with
`LLMGateway(cache_purposes={"chat"})`; disable with `cache=False` or per call `complete(..., cache=False)`.

## Privacy rule

In cloud mode, if an `Anonymizer` is set, known client/vendor names are replaced by
stable aliases (`Client-017`, `Vendor-003`) before the request leaves the machine
and restored in the reply. Ollama (local) always sees real names.

```python
anon = Anonymizer({"Acme Labels Pvt Ltd": "Client-017"})   # or Anonymizer(loader_fn)
text, mapping = anon.anonymize("Why is Acme Labels Pvt Ltd locked?")
anon.restore("Client-017 has an overdue invoice", mapping)
```

## Tests: inject fakes (no network)

A provider is any object with `name`, `available`, optional `is_local`, and
`complete(messages, json_schema=None, timeout=None) -> str` (raise to simulate failure).

```python
gw = LLMGateway(providers=[FakeDown("gemini"), FakeOk("groq", "hi")], mode="cloud",
                cache=AnswerCache(tmp_path / "c.json"))
assert gw.complete([{"role": "user", "content": "q"}], purpose="chat").provider == "groq"
set_gateway(gw)   # make get_gateway() return it; set_gateway(None) resets
```
In `local` mode only providers with `is_local=True` (or named `ollama`) are tried.
