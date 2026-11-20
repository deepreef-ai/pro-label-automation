"""LLM gateway: many providers and keys with fallback, behind one interface.

All model calls in the app go through :func:`get_gateway` /
:class:`LLMGateway.complete`. Cloud mode walks ``LLM_ORDER`` (default: Claude,
then Groq, Cerebras, Gemini, SambaNova, Mistral, NVIDIA, GitHub Models,
OpenRouter, Hugging Face, Ollama), skipping providers without a key, rotating
across each provider's keys (``<KEY>``, ``<KEY>_2`` .. ``_9``) with cooldowns, and
racing ``LLM_PARALLEL`` providers at once for speed. Local mode uses Ollama only.
If nothing answers, :class:`LLMUnavailable` is raised and callers use
deterministic fallbacks. See ``README.md`` in this folder.
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
    AnthropicProvider,
    OpenAICompatibleProvider,
    Provider,
    ProviderError,
    cloud_order,
    default_providers,
    reset_cooldowns,
)

__all__ = [
    "Anonymizer", "build_aliases",
    "AnswerCache", "normalise_prompt", "prompt_key",
    "LLMError", "LLMGateway", "LLMResult", "LLMUnavailable",
    "extract_json", "validate_json", "get_gateway", "set_gateway",
    "CLOUD_ORDER", "LOCAL_ORDER", "PROVIDER_CONFIGS",
    "AnthropicProvider", "OpenAICompatibleProvider", "Provider", "ProviderError",
    "cloud_order", "default_providers", "reset_cooldowns",
]
