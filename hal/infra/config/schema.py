"""Configuration schema using Pydantic."""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class _StrictModel(BaseModel):
    """Base for all config sub-models. Rejects unknown keys."""

    model_config = ConfigDict(extra="forbid")


class TelegramConfig(_StrictModel):
    """Telegram channel configuration."""

    enabled: bool = False
    token: str = ""  # Bot token from @BotFather
    allow_from: list[str] = Field(default_factory=list)  # Allowed user IDs or usernames
    send_progress: bool = True  # Send interim assistant intent text before tool execution
    send_tool_hints: bool = True  # Send interim tool-call hint lines (↳ tool(...))
    proxy: str | None = (
        None  # HTTP/SOCKS5 proxy URL, e.g. "http://127.0.0.1:7890" or "socks5://127.0.0.1:1080"
    )


class ChannelsConfig(_StrictModel):
    """Configuration for chat channels."""

    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    outbound_poll_timeout_s: float = Field(default=1.0, gt=0)  # Outbound dispatch poll interval


class HistoryConfig(_StrictModel):
    """Conversation history context configuration.

    Controls how historical messages are prepared before sending to the LLM.
    Older assistant messages are truncated to reduce in-context learning
    contamination (where the model picks up formatting/style from its own
    earlier outputs).
    """

    max_messages: int = 50  # Max messages loaded from daily log
    recent_full_turns: int = 3  # Recent assistant messages kept verbatim
    assistant_truncate_tokens: int = 50  # Max tokens for older assistant messages
    max_history_tokens: int = 0  # 0 = unlimited; hard cap on total history tokens
    memory_budget_tokens: int = 0  # 0 = unlimited; token budget for MEMORY.md injection
    history_days: int = 1  # 1 = today only; 2+ includes previous days
    recall_max_total_tokens: int = 500  # Max tokens injected from retrieved memory fragments
    recall_max_per_item_tokens: int = 125  # Max tokens per retrieved memory fragment


class AgentDefaults(_StrictModel):
    """Default agent configuration."""

    workspace: str = "~/.hal"
    model: str = "anthropic/claude-opus-4-5"
    max_tokens: int = 8192
    temperature: float = 0.7
    max_tool_iterations: int = 20
    summary_model: str = "default"  # Model for post-loop summaries; "default" uses main model
    worker_model: str = "default"  # Model for worker agents; "default" uses main
    history: HistoryConfig = Field(default_factory=HistoryConfig)


class AgentsConfig(_StrictModel):
    """Agent configuration."""

    defaults: AgentDefaults = Field(default_factory=AgentDefaults)


class ProviderConfig(_StrictModel):
    """LLM provider configuration."""

    api_key: str = ""
    api_base: str | None = None
    extra_headers: dict[str, str] | None = None  # Custom request headers for provider endpoints
    compat_mode: str = ""  # Protocol hint for proxies: "openai" = OpenAI-compatible endpoint
    request_params: dict[str, Any] | None = None  # Optional per-request LiteLLM params


class ProvidersConfig(_StrictModel):
    """Configuration for LLM providers."""

    anyrouter: ProviderConfig = Field(default_factory=ProviderConfig)  # AnyRouter (Anthropic relay)
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    openrouter: ProviderConfig = Field(default_factory=ProviderConfig)
    deepseek: ProviderConfig = Field(default_factory=ProviderConfig)
    groq: ProviderConfig = Field(default_factory=ProviderConfig)
    zhipu: ProviderConfig = Field(default_factory=ProviderConfig)
    vllm: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    moonshot: ProviderConfig = Field(default_factory=ProviderConfig)
    siliconflow: ProviderConfig = Field(default_factory=ProviderConfig)  # SiliconFlow (硅基流动)


class GatewayConfig(_StrictModel):
    """Gateway/server configuration."""

    host: str = "0.0.0.0"
    port: int = 18790


class WebSearchConfig(_StrictModel):
    """Web search tool configuration."""

    api_key: str = ""  # Tavily Search API key
    max_results: int = Field(default=5, ge=1, le=10)
    timeout_s: float = Field(default=10.0, gt=0)  # HTTP timeout for search API calls


class WebFetchConfig(_StrictModel):
    """Web fetch tool configuration."""

    default_max_chars: int = Field(default=50000, ge=100)  # Max chars extracted from fetched pages
    timeout_s: float = Field(default=30.0, gt=0)  # HTTP timeout for page fetches
    max_redirects: int = Field(default=5, ge=1)  # Max HTTP redirects (DoS prevention)


class WebToolsConfig(_StrictModel):
    """Web tools configuration."""

    search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    fetch: WebFetchConfig = Field(default_factory=WebFetchConfig)


class ExecToolConfig(_StrictModel):
    """Shell exec tool configuration."""

    timeout: int = Field(default=60, gt=0)  # Command execution timeout (seconds)
    kill_wait_s: int = Field(default=5, gt=0)  # Grace period after timeout before force-kill


class ToolsConfig(_StrictModel):
    """Tools configuration."""

    web: WebToolsConfig = Field(default_factory=WebToolsConfig)
    exec: ExecToolConfig = Field(default_factory=ExecToolConfig)
    restrict_to_workspace: bool = False  # If true, restrict all tool access to workspace directory


class MemorySearchConfig(_StrictModel):
    """Semantic memory search configuration."""

    enabled: bool = False
    embedding_model: str = "openai/text-embedding-3-small"
    embedding_provider: str = ""  # Provider name for embedding API (e.g. "siliconflow")
    milvus_uri: str = "~/.hal/data/milvus/hal_memory.db"
    collection_name: str = "hal_memory"
    embedding_dim: int = 1536
    auto_inject_top_k: int = 3
    recall_min_score: float = 0.0
    max_chunk_size: int = 1000
    chunk_overlap_lines: int = 2
    chunk_heading_max_level: int = 2
    exclude_channels: list[str] = Field(default_factory=list)  # Channels excluded from export/index
    embed_retry_attempts: int = Field(default=3, ge=1)  # Embedding API retry count
    embed_retry_base_delay_s: float = Field(default=0.5, gt=0)  # Base delay for exponential backoff
    embed_timeout_s: float = Field(default=60.0, gt=0)  # HTTP timeout for embedding API calls


class EngineConfig(_StrictModel):
    """Agent engine runtime configuration."""

    inbound_poll_timeout_s: float = Field(default=1.0, gt=0)  # Bus consume poll interval
    summary_barrier_timeout_s: float = Field(default=10.0, gt=0)  # Max wait for pending summary
    llm_retry_attempts: int = Field(default=3, ge=1)  # Retry count for retryable LLM API errors
    llm_retry_base_delay_s: float = Field(
        default=0.8, gt=0
    )  # Base delay (seconds) for LLM retry backoff
    llm_retry_max_delay_s: float = Field(
        default=8.0, gt=0
    )  # Upper bound (seconds) for LLM retry delay


class Config(BaseSettings):
    """Root configuration for HaL."""

    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    channels: ChannelsConfig = Field(default_factory=ChannelsConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    memory_search: MemorySearchConfig = Field(default_factory=MemorySearchConfig)
    engine: EngineConfig = Field(default_factory=EngineConfig)

    @property
    def workspace_path(self) -> Path:
        """Get expanded workspace path."""
        return Path(self.agents.defaults.workspace).expanduser()

    def get_provider(self, model: str | None = None) -> ProviderConfig | None:
        """Get matched provider config (api_key, api_base, extra_headers). Falls back to first available."""
        from hal.infra.providers.registry import PROVIDERS

        model_lower = (model or self.agents.defaults.model).lower()

        # Match by keyword (order follows PROVIDERS registry)
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and any(kw in model_lower for kw in spec.keywords) and p.api_key:
                return p

        # Fallback: gateways first, then others (follows registry order)
        for spec in PROVIDERS:
            p = getattr(self.providers, spec.name, None)
            if p and p.api_key:
                return p
        return None

    def get_api_key(self, model: str | None = None) -> str | None:
        """Get API key for the given model. Falls back to first available key."""
        p = self.get_provider(model)
        return p.api_key if p else None

    def get_api_base(self, model: str | None = None) -> str | None:
        """Get API base URL for the given model. Applies default URLs for known gateways."""
        from hal.infra.providers.registry import PROVIDERS

        p = self.get_provider(model)
        if p and p.api_base:
            return p.api_base
        # Only gateways get a default URL here. Standard providers (like Moonshot)
        # handle their base URL via env vars in _setup_env, NOT via api_base —
        # otherwise find_gateway() would misdetect them as local/vLLM.
        for spec in PROVIDERS:
            if (
                spec.is_gateway
                and spec.default_api_base
                and p == getattr(self.providers, spec.name, None)
            ):
                return spec.default_api_base
        return None

    model_config = SettingsConfigDict(env_prefix="HAL_", env_nested_delimiter="__", extra="forbid")
