# core.llm: LLM gateway (many providers, many keys, hedged requests)

Every model call goes through `get_gateway().complete(messages, purpose=..., json_schema=None)`,
which returns `LLMResult(text, provider, cached, data, errors)` or raises `LLMUnavailable`
(callers then use a deterministic fallback). The LLM never computes money or stock.

Every provider is optional: it is used only when its key is set. OpenAI-compatible
providers share one small httpx client; Claude uses the official `anthropic` SDK
(imported lazily, so the module works without it installed).

## Providers and env vars

| Provider | Endpoint | Key env (+ `_2` .. `_9`) | Default model (env override) | Cost |
|---|---|---|---|---|
| anthropic (Claude) | Anthropic Messages API (official SDK) | `ANTHROPIC_API_KEY` | `claude-opus-5-5` (`ANTHROPIC_MODEL`) | **paid** |
| groq | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` | `openai/gpt-oss-120b` (`GROQ_MODEL`) | free tier |
| cerebras | `https://api.cerebras.ai/v1` | `CEREBRAS_API_KEY` | `gpt-oss-120b` (`CEREBRAS_MODEL`) | free tier |
| gemini | `https://generativelanguage.googleapis.com/v1beta/openai` | `GEMINI_API_KEY` | `gemini-flash-latest` (`GEMINI_MODEL`) | free tier |
| sambanova | `https://api.sambanova.ai/v1` | `SAMBANOVA_API_KEY` | `Meta-Llama-3.3-70B-Instruct` (`SAMBANOVA_MODEL`) | free tier |
| mistral | `https://api.mistral.ai/v1` | `MISTRAL_API_KEY` | `mistral-small-latest` (`MISTRAL_MODEL`) | free tier |
| nvidia | `https://integrate.api.nvidia.com/v1` | `NVIDIA_API_KEY` | `nvidia/nemotron-3.5-lightning-30b-a3b` (`NVIDIA_MODEL`) | free credits |
| github (GitHub Models) | `https://models.github.ai/inference` | `GITHUB_MODELS_TOKEN` | `openai/gpt-4.1-mini` (`GITHUB_MODELS_MODEL`) | free tier |
| openrouter | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | `nvidia/nemotron-3.5-lightning:free` (`OPENROUTER_MODEL`) | free (`:free` models) |
| huggingface | `https://router.huggingface.co/v1` | `HF_TOKEN` | `meta-llama/Llama-3.1-8B-Instruct` (`HF_MODEL`) | free tier |
| ollama (local) | `OLLAMA_URL` (default `http://localhost:11434/v1`) | none | `qwen2.5:3b` (`OLLAMA_MODEL`) | free, local |

Free model names change often (several Llama 3.3 ids were retired in 2026); override with the
model env vars. Claude: `ANTHROPIC_EFFORT` (`low` default; `medium`/`high` = slower, smarter,
pricier) and `ANTHROPIC_TIMEOUT` (seconds, 60). Thinking stays at the model default (adaptive);
no temperature/thinking budget is sent. A `refusal` stop reason counts as a provider error, so
the gateway falls back to the next provider.

## Order

`LLM_ORDER` (comma list) sets the cloud chain. Default:

`anthropic, groq, cerebras, gemini, sambanova, mistral, nvidia, github, openrouter, huggingface, ollama`

Claude comes first when its key is set (most capable); the fastest free tiers follow.
Providers without a key are skipped. `AI_MODE=local` uses Ollama only.

**Cost:** Claude Opus 5.5 is paid (about $4 per million input tokens and $20 per million
output tokens). To save money put the free ones first, e.g.
`LLM_ORDER=groq,gemini,cerebras,mistral,openrouter,anthropic,ollama`, or leave
`ANTHROPIC_API_KEY` empty. With hedging on (below) a raced Claude call is billed even when a
free provider answers first.

## Multiple keys (rotation and cooldown)

Each provider reads `<KEY>`, `<KEY>_2` .. `<KEY>_9` (e.g. `GEMINI_API_KEY_2`). Each key is a
*bucket*; calls round-robin across a provider's healthy buckets. On 429 / quota / payment
required / rejected key / 5xx the bucket cools down for `LLM_COOLDOWN_SECONDS` (default 60) and
the next bucket is tried at once. A timeout, connection error or retired model (404/410) also
cools the bucket but moves straight to the next provider. A provider with every bucket cooling
is skipped. Bad JSON, refusals and bad requests go to the next provider without a cooldown.

## Parallel (hedged) requests

`LLM_PARALLEL` (default 2): the first N available providers are raced in threads; the first
good answer wins and the others are ignored. Each failure starts the next provider in the
chain, so at most N calls are in flight. `LLM_PARALLEL=1` is strictly sequential.
A gateway built with an explicit `providers=` list (tests) is sequential unless
`parallel=` is also passed: `LLMGateway(providers=[...], parallel=2)`.

If all fail: `LLMUnavailable` (`.errors` = list of `(provider, message)`).

Other env: `AI_MODE` (`cloud` default | `local`), `LLM_TIMEOUT` (cloud seconds, 20),
`LLM_LOCAL_TIMEOUT` (Ollama seconds, 90), `LLM_CACHE_PATH` (default `data/llm_cache.json`),
`LLM_CACHE_RECORD=1` (save live answers into the cache).

## Cache

The answer cache is checked first, before any provider. For scripted demo questions the gateway
first checks `AnswerCache` (key = SHA-256 of the lower-cased, whitespace-collapsed message
contents). Hits return `provider="cache", cached=True`. Restrict with
`LLMGateway(cache_purposes={"chat"})`; disable with `cache=False` or per call `complete(..., cache=False)`.

## Privacy rule

In cloud mode, if an `Anonymizer` is set, known client/vendor names are replaced by
stable aliases (`Client-017`, `Vendor-003`) before the request leaves the machine, for
**every** non-local provider (Claude included), and restored in the reply. Only Ollama
(local) sees real names.

```python
anon = Anonymizer({"Acme Labels Pvt Ltd": "Client-017"})   # or Anonymizer(loader_fn)
text, mapping = anon.anonymize("Why is Acme Labels Pvt Ltd locked?")
anon.restore("Client-017 has an overdue invoice", mapping)
```

Keys live only in your local `.env`/shell, never in git. They are read at call time and never
logged; a bucket is identified only by its env var name.

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
`reset_cooldowns()` clears key cooldowns between tests.
