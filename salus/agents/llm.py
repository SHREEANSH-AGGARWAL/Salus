"""
LLM client factory for the Salus agent pipeline.

Creates a LangChain BaseChatModel based on the LLMConfig provider setting.

Supported providers:
    - "ollama"  (default, free, local, offline-capable)
    - "google"  (Gemini free tier, 60 req/min)
    - "openai"  (GPT-4o, paid)

Set via environment:
    SALUS_LLM__PROVIDER=ollama
    SALUS_LLM__MODEL=llama3.1:8b
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from salus.config import LLMConfig

logger = structlog.get_logger()


def create_llm(config: LLMConfig) -> BaseChatModel:
    """Factory: instantiate the configured LLM provider.

    Args:
        config: LLMConfig with provider, model, timeout, temperature settings.

    Returns:
        A LangChain BaseChatModel ready for use.

    Raises:
        ImportError: If the required provider package is not installed.
        ValueError: If the provider is not recognised.
    """
    provider = config.provider.lower()
    logger.info("creating_llm", provider=provider, model=config.model)

    if provider == "ollama":
        return _create_ollama(config)
    elif provider == "google":
        return _create_google(config)
    elif provider == "openai":
        return _create_openai(config)
    else:
        raise ValueError(
            f"Unknown LLM provider: '{provider}'. "
            f"Supported: 'ollama', 'google', 'openai'. "
            f"Set SALUS_LLM__PROVIDER in your environment."
        )


def _create_ollama(config: LLMConfig) -> BaseChatModel:
    """Create a ChatOllama instance (free, local, offline)."""
    try:
        from langchain_ollama import ChatOllama
    except ImportError as e:
        raise ImportError(
            "langchain-ollama is not installed. Run: pip install 'salus[ai]'"
        ) from e

    return ChatOllama(
        model=config.model,
        base_url=config.ollama_base_url,
        temperature=config.temperature,
        # Ollama doesn't use timeout at the langchain level — handled by circuit-breaker
    )


def _create_google(config: LLMConfig) -> BaseChatModel:
    """Create a ChatGoogleGenerativeAI instance (Gemini free tier)."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as e:
        raise ImportError(
            "langchain-google-genai is not installed. Run: pip install langchain-google-genai"
        ) from e

    return ChatGoogleGenerativeAI(
        model=config.model,
        temperature=config.temperature,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
    )


def _create_openai(config: LLMConfig) -> BaseChatModel:
    """Create a ChatOpenAI instance."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise ImportError(
            "langchain-openai is not installed. Run: pip install 'salus[ai]'"
        ) from e

    return ChatOpenAI(
        model=config.model,
        temperature=config.temperature,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
    )
