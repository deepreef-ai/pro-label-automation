"""LLM gateway: free cloud tiers with a local fallback, behind one interface.

All model calls in the app go through :func:`get_gateway` /
:class:`LLMGateway.complete`. Cloud mode tries Gemini -> Groq -> OpenRouter ->
Hugging Face -> Ollama; local mode uses Ollama only. If nothing answers,
:class:`LLMUnavailable` is raised and callers use deterministic fallbacks.

Swapping to Claude / AWS Bedrock later
--------------------------------------
It is just another provider entry. Either:

* add a :class:`Provider` to ``PROVIDER_CONFIGS`` pointing at any
  OpenAI-compatible endpoint (e.g. an Anthropic OpenAI-compatible endpoint or a
  Bedrock access gateway) with its key env var and model env var, and put its
  name first in ``CLOUD_ORDER``; or
* write a small class with ``name``, ``available``, ``is_local`` and
  ``complete(messages, json_schema=None, timeout=None) -> str`` that calls the
  native SDK (e.g. boto3 ``bedrock-runtime`` ``converse``), and pass it in
  ``LLMGateway(providers=[...])``.

Nothing else (cache, anonymizer, JSON handling, callers) changes.
"""
from .anonymizer import Anonymizer, build_aliases
from .cache import AnswerCache, normalise_prompt, prompt_key
from .gateway import (
    LLMError,
    LLMGateway,
    LLMResult,
    LLMUnavailable,
    extract_json,
    get_gateway,
    set_gateway,
    validate_json,
)
from .providers import (
    CLOUD_ORDER,
    LOCAL_ORDER,
    PROVIDER_CONFIGS,
    OpenAICompatibleProvider,
    Provider,
    ProviderError,
    default_providers,
)

__all__ = [
    "Anonymizer", "build_aliases",
    "AnswerCache", "normalise_prompt", "prompt_key",
    "LLMError", "LLMGateway", "LLMResult", "LLMUnavailable",
    "extract_json", "validate_json", "get_gateway", "set_gateway",
    "CLOUD_ORDER", "LOCAL_ORDER", "PROVIDER_CONFIGS",
    "OpenAICompatibleProvider", "Provider", "ProviderError", "default_providers",
]
