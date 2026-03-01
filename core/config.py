"""
YukiShadow - Unified Configuration

All settings are read from environment variables or .env file.
Nested sub-config objects are constructed from flat env vars for easy override.
"""

from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_name: str = "YukiShadow"
    debug: bool = False
    timezone: str = "Asia/Shanghai"

    # ── LLM ──────────────────────────────────────────────────────────────────
    # Default provider used when no override is specified.
    # Supported: "ollama" | "openai" | "anthropic"
    llm_default_provider: str = "ollama"

    # Ollama  (local, no API key required)
    llm_ollama_base_url: str = "http://localhost:11434"
    llm_ollama_default_model: str = "qwen3.5:27b"

    # OpenAI  (or any OpenAI-compatible endpoint, e.g. LM Studio)
    llm_openai_api_key: Optional[str] = None
    llm_openai_base_url: str = "https://api.openai.com/v1"
    llm_openai_default_model: str = "gpt-4o"

    # Anthropic
    llm_anthropic_api_key: Optional[str] = None
    llm_anthropic_default_model: str = "claude-sonnet-4-6"

    # Per-skill provider overrides.
    # Format: "skill_name=provider,skill2=provider2"
    # Example: "code_review=anthropic,translation=openai"
    llm_skill_overrides: str = ""

    # ── Discord ───────────────────────────────────────────────────────────────
    discord_bot_token: str = ""
    # Default channel where reminder/system notifications are sent
    discord_notification_channel_id: int = 0
    discord_command_prefix: str = "!"

    # ── Redis (message bus + task queue) ──────────────────────────────────────
    redis_url: str = "redis://localhost:6379"

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./yukishadow.db"

    # ── ChromaDB (vector store / RAG) ─────────────────────────────────────────
    chroma_host: str = "localhost"
    chroma_port: int = 8001

    # ── MQTT (Jetson edge node) ───────────────────────────────────────────────
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883

    # ── Service ports ─────────────────────────────────────────────────────────
    orchestrator_port: int = 8080
    discord_service_port: int = 8090   # Discord bot sidecar HTTP server
    mcp_port: int = 8765  # Reserved; currently MCP runs over stdio

    # ── Computed helpers ──────────────────────────────────────────────────────
    @property
    def skill_provider_overrides(self) -> dict[str, str]:
        """Parse 'skill=provider,skill2=provider2' → dict."""
        if not self.llm_skill_overrides:
            return {}
        result: dict[str, str] = {}
        for pair in self.llm_skill_overrides.split(","):
            pair = pair.strip()
            if "=" in pair:
                skill, provider = pair.split("=", 1)
                result[skill.strip()] = provider.strip()
        return result

    @property
    def orchestrator_base_url(self) -> str:
        return f"http://localhost:{self.orchestrator_port}"

    @property
    def discord_service_url(self) -> str:
        return f"http://localhost:{self.discord_service_port}"


# Singleton – import this everywhere
settings = Settings()
