# chat: chatbot backend (task C1)

## Wiring (API owner)

In `apps/api/app/main.py`:

```python
import chat.router
app.include_router(chat.router.router)   # POST /api/chat, GET /api/chat/suggestions
```

Role checks for other endpoints already apply: chat tools call the app in-process
(`httpx.ASGITransport`) with the caller's `X-Role`.

## Modules

| File | What |
|---|---|
| `tools.py` | `Tool`, `ToolContext(role, api)`, `TOOLS`. Read tools only `api.get`; draft tools return `{"type":"draft","entity","endpoint","body","payload","summary"}` and never write. |
| `rag.py` | Document index (`data/raw` docs, else `docs/*.md` + `contract/SPEC.md`). fastembed `BAAI/bge-small-en-v1.5` when the model is on disk, else BM25. Build: `PYTHONPATH=apps/api python -m chat.rag --build`. Cache in `data/rag/` (git-ignored). |
| `graph.py` | LangGraph agent, JSON tool-call protocol over `core.llm.get_gateway()`, max 3 tool steps. |
| `service.py` | `answer()` per SPEC 4b: navigation router -> agent -> deterministic templates when the LLM is unavailable. Actions are sanitised (navigate + tool drafts only). |
| `router.py` | FastAPI routes. |
| `api_client.py` | In-process API client. |

Env: `CHAT_RAG_MODE=keyword` forces keyword search; `CHAT_RAG_DOWNLOAD=1` lets the server download the embedding model on first use.
