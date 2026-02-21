"""Factory functions for constructing providers and memory search."""

from __future__ import annotations

import importlib.util

import typer
from rich.console import Console

console = Console()


def _resolve_provider_name(config, model_name: str):
    """Resolve the selected provider config field name for a model."""
    from hal.infra.providers.registry import PROVIDERS

    model_lower = model_name.lower()

    for spec in PROVIDERS:
        p = getattr(config.providers, spec.name, None)
        if p and p.api_key and any(kw in model_lower for kw in spec.keywords):
            return spec.name

    for spec in PROVIDERS:
        p = getattr(config.providers, spec.name, None)
        if p and p.api_key:
            return spec.name

    return ""


def make_provider(config):
    """Create LiteLLMProvider from config. Exits if no API key found."""
    from hal.infra.providers.litellm_provider import LiteLLMProvider

    p = config.get_provider()
    model = config.agents.defaults.model
    provider_name = _resolve_provider_name(config, model)
    if not (p and p.api_key) and not model.startswith("bedrock/"):
        console.print("[red]Error: No API key configured.[/red]")
        console.print("Set one in ~/.hal/auth.yaml under providers section")
        raise typer.Exit(1)
    return LiteLLMProvider(
        api_key=p.api_key if p else None,
        api_base=config.get_api_base(),
        default_model=model,
        extra_headers=p.extra_headers if p else None,
        compat_mode=p.compat_mode if p else "",
        provider_name=provider_name,
    )


def make_summary_provider(config):
    """Create a separate LiteLLMProvider for summary model if needed. Returns None if same provider."""
    return _make_alternate_provider(config, config.agents.defaults.summary_model)


def make_subagent_provider(config):
    """Create a separate LiteLLMProvider for subagent model if needed. Returns None if same provider."""
    return _make_alternate_provider(config, config.agents.defaults.subagent_model)


def _make_alternate_provider(config, model_name: str):
    """Create a separate LiteLLMProvider for an alternate model. Returns None if 'default' or same provider."""
    from hal.infra.providers.litellm_provider import LiteLLMProvider

    if model_name == "default":
        return None

    sp = config.get_provider(model_name)
    mp = config.get_provider()
    # If alternate model resolves to the same provider, no need for a separate instance
    if sp and mp and sp.api_key == mp.api_key and sp.api_base == mp.api_base:
        return None
    if not sp or not sp.api_key:
        return None

    provider_name = _resolve_provider_name(config, model_name)

    api_base = sp.api_base
    if not api_base:
        from hal.infra.providers.registry import find_by_model

        spec = find_by_model(model_name)
        if spec and spec.default_api_base:
            api_base = spec.default_api_base

    return LiteLLMProvider(
        api_key=sp.api_key,
        api_base=api_base,
        default_model=model_name,
        extra_headers=sp.extra_headers if sp else None,
        compat_mode=sp.compat_mode if sp else "",
        provider_name=provider_name,
    )


def _resolve_embedding_provider(config, ms_cfg) -> dict:
    """Resolve api_key/api_base for embedding from the named provider."""
    result: dict = {}
    name = ms_cfg.embedding_provider
    if not name:
        # Fallback: try to auto-detect provider from embedding model name
        p = config.get_provider(ms_cfg.embedding_model)
        if p and p.api_key:
            result["api_key"] = p.api_key
            base = config.get_api_base(ms_cfg.embedding_model)
            if base:
                result["api_base"] = base
        return result

    p = getattr(config.providers, name, None)
    if p and p.api_key:
        result["api_key"] = p.api_key
        # Use provider's api_base, falling back to registry default
        if p.api_base:
            result["api_base"] = p.api_base
        else:
            from hal.infra.providers.registry import find_by_name

            spec = find_by_name(name)
            if spec and spec.default_api_base:
                result["api_base"] = spec.default_api_base
    return result


def _module_available(module_name: str) -> bool:
    """Whether a Python module is importable in the current environment."""
    return importlib.util.find_spec(module_name) is not None


def _missing_memory_deps(milvus_uri: str) -> list[str]:
    """Detect missing optional dependencies required by memory search."""
    missing: list[str] = []

    if not _module_available("pymilvus"):
        missing.append("pymilvus")

    # Local file URIs require milvus-lite runtime.
    is_remote_uri = "://" in milvus_uri
    if not is_remote_uri and not _module_available("milvus_lite"):
        missing.append("milvus-lite")

    return missing


def make_memory_search(config):
    """Create MemorySearch instance from config. Returns None if deps missing."""
    missing = _missing_memory_deps(config.memory_search.milvus_uri)
    if missing:
        deps = ", ".join(missing)
        console.print(
            "[yellow]Memory search unavailable "
            f'(missing dependency: {deps}). Install with `pip install -e ".[memory]"`.[/yellow]'
        )
        return None

    try:
        from hal.core.memory.chunker import MarkdownChunker
        from hal.core.memory.exporter import DailyExporter
        from hal.core.memory.search import MemorySearch
        from hal.core.memory.store import VectorStore
    except ImportError as e:
        console.print(f"[yellow]Memory search unavailable (missing dependency: {e})[/yellow]")
        return None

    ms_cfg = config.memory_search

    from hal.core.memory.daily_log import DailyLog

    # Must match MemoryManager's log_dir: (data_dir or workspace) / "logs".
    # MemoryManager defaults data_dir=None → uses workspace, so logs live
    # under workspace/logs, not get_data_dir()/logs.
    log_dir = config.workspace_path / "logs"
    daily_log = DailyLog(log_dir)
    daily_dir = config.workspace_path / "memory" / "daily"

    exporter = DailyExporter(daily_log, daily_dir)
    chunker = MarkdownChunker(
        max_size=ms_cfg.max_chunk_size,
        overlap_lines=ms_cfg.chunk_overlap_lines,
        max_heading_level=ms_cfg.chunk_heading_max_level,
    )
    store = VectorStore(
        uri=ms_cfg.milvus_uri,
        collection_name=ms_cfg.collection_name,
        embedding_dim=ms_cfg.embedding_dim,
    )

    return MemorySearch(
        exporter=exporter,
        chunker=chunker,
        store=store,
        embedding_model=ms_cfg.embedding_model,
        daily_dir=daily_dir,
        embedding_dim=ms_cfg.embedding_dim,
        **_resolve_embedding_provider(config, ms_cfg),
    )
