"""
YukiShadow - LLM Abstraction Layer

Design:
  - BaseLLMClient: abstract interface (chat, stream_chat)
  - OllamaClient / OpenAIClient / AnthropicClient: concrete implementations
  - LLMRouter: picks the right client based on:
      1. Explicit `provider` argument
      2. Per-skill override (SKILL_PROVIDER_OVERRIDES env var)
      3. Global default (LLM_DEFAULT_PROVIDER env var)

To add a new provider: subclass BaseLLMClient and register in LLMRouter._build_client().
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator

logger = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Message:
    role: str   # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    tokens_used: int = 0


# ── Abstract base ─────────────────────────────────────────────────────────────

class BaseLLMClient(ABC):

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs,
    ) -> LLMResponse: ...

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[Message],
        model: str | None = None,
        **kwargs,
    ) -> AsyncIterator[str]: ...


# ── Ollama ────────────────────────────────────────────────────────────────────

class OllamaClient(BaseLLMClient):

    def __init__(self, base_url: str, default_model: str):
        import ollama
        self._client = ollama.AsyncClient(host=base_url)
        self.default_model = default_model

    async def chat(self, messages, model=None, **kwargs) -> LLMResponse:
        m = model or self.default_model
        resp = await self._client.chat(
            model=m,
            messages=[{"role": msg.role, "content": msg.content} for msg in messages],
            **kwargs,
        )
        return LLMResponse(
            content=resp.message.content,
            model=m,
            provider="ollama",
            tokens_used=getattr(resp, "eval_count", 0) or 0,
        )

    async def stream_chat(self, messages, model=None, **kwargs) -> AsyncIterator[str]:
        m = model or self.default_model
        async for chunk in await self._client.chat(
            model=m,
            messages=[{"role": msg.role, "content": msg.content} for msg in messages],
            stream=True,
            **kwargs,
        ):
            if chunk.message.content:
                yield chunk.message.content


# ── OpenAI (also works with LM Studio / any OpenAI-compatible endpoint) ───────

class OpenAIClient(BaseLLMClient):

    def __init__(self, api_key: str, base_url: str, default_model: str):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.default_model = default_model

    async def chat(self, messages, model=None, **kwargs) -> LLMResponse:
        m = model or self.default_model
        resp = await self._client.chat.completions.create(
            model=m,
            messages=[{"role": msg.role, "content": msg.content} for msg in messages],
            **kwargs,
        )
        return LLMResponse(
            content=resp.choices[0].message.content or "",
            model=m,
            provider="openai",
            tokens_used=resp.usage.total_tokens if resp.usage else 0,
        )

    async def stream_chat(self, messages, model=None, **kwargs) -> AsyncIterator[str]:
        m = model or self.default_model
        stream = await self._client.chat.completions.create(
            model=m,
            messages=[{"role": msg.role, "content": msg.content} for msg in messages],
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


# ── Anthropic ─────────────────────────────────────────────────────────────────

class AnthropicClient(BaseLLMClient):

    def __init__(self, api_key: str, default_model: str):
        import anthropic
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self.default_model = default_model

    def _split_messages(self, messages: list[Message]):
        system = next((m.content for m in messages if m.role == "system"), None)
        others = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        return system, others

    async def chat(self, messages, model=None, **kwargs) -> LLMResponse:
        m = model or self.default_model
        system, others = self._split_messages(messages)
        kwargs.setdefault("max_tokens", 4096)
        resp = await self._client.messages.create(
            model=m,
            system=system,
            messages=others,
            **kwargs,
        )
        return LLMResponse(
            content=resp.content[0].text,
            model=m,
            provider="anthropic",
            tokens_used=resp.usage.input_tokens + resp.usage.output_tokens,
        )

    async def stream_chat(self, messages, model=None, **kwargs) -> AsyncIterator[str]:
        m = model or self.default_model
        system, others = self._split_messages(messages)
        kwargs.setdefault("max_tokens", 4096)
        async with self._client.messages.stream(
            model=m,
            system=system,
            messages=others,
            **kwargs,
        ) as stream:
            async for text in stream.text_stream:
                yield text


# ── Router ────────────────────────────────────────────────────────────────────

class LLMRouter:
    """
    Routes LLM requests to the right provider.

    Priority (highest to lowest):
      1. Explicit `provider` argument in the call
      2. Per-skill override from SKILL_PROVIDER_OVERRIDES
      3. Global LLM_DEFAULT_PROVIDER
    """

    def __init__(self):
        # Lazy-import settings to avoid circular imports at module load time
        from core.config import settings
        self._settings = settings
        self._clients: dict[str, BaseLLMClient] = {}

    def _build_client(self, provider: str) -> BaseLLMClient:
        s = self._settings
        if provider == "ollama":
            return OllamaClient(s.llm_ollama_base_url, s.llm_ollama_default_model)
        if provider == "openai":
            if not s.llm_openai_api_key:
                raise ValueError("LLM_OPENAI_API_KEY is not set")
            return OpenAIClient(s.llm_openai_api_key, s.llm_openai_base_url, s.llm_openai_default_model)
        if provider == "anthropic":
            if not s.llm_anthropic_api_key:
                raise ValueError("LLM_ANTHROPIC_API_KEY is not set")
            return AnthropicClient(s.llm_anthropic_api_key, s.llm_anthropic_default_model)
        raise ValueError(f"Unknown LLM provider: '{provider}'. Choose: ollama | openai | anthropic")

    def _get_client(self, provider: str) -> BaseLLMClient:
        if provider not in self._clients:
            self._clients[provider] = self._build_client(provider)
        return self._clients[provider]

    def resolve_provider(self, skill_name: str | None = None, provider: str | None = None) -> str:
        if provider:
            return provider
        if skill_name:
            override = self._settings.skill_provider_overrides.get(skill_name)
            if override:
                return override
        return self._settings.llm_default_provider

    def get_client(
        self,
        skill_name: str | None = None,
        provider: str | None = None,
    ) -> BaseLLMClient:
        p = self.resolve_provider(skill_name=skill_name, provider=provider)
        return self._get_client(p)

    async def chat(
        self,
        messages: list[Message],
        skill_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        **kwargs,
    ) -> LLMResponse:
        client = self.get_client(skill_name=skill_name, provider=provider)
        return await client.chat(messages, model=model, **kwargs)

    async def stream_chat(
        self,
        messages: list[Message],
        skill_name: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        client = self.get_client(skill_name=skill_name, provider=provider)
        async for chunk in client.stream_chat(messages, model=model, **kwargs):
            yield chunk


# Singleton
llm_router = LLMRouter()
