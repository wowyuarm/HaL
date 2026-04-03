"""Runtime helpers for session lifecycle and in-session compaction orchestration."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any

from loguru import logger

from hal.context.message_building import (
    assemble_message_sequence,
    build_system_message,
    copy_replay_history,
)
from hal.context.token_budget import trim_text_to_token_budget

# Re-export domain types for backward compatibility
from hal.domain.session import SessionRuntimeState, build_session_id  # noqa: F401

_MAX_COMPACTION_PASSES = 3
_MANUAL_COMPACTION_PASSES = 1
_TOOL_RESULT_SUMMARY_SUFFIX = "\n...[tool result truncated for replay]"
_HISTORY_IMAGE_SUMMARY = "[prior image omitted from session replay]"
_HISTORY_IMAGE_DROPPED = "[prior image dropped from session replay]"


def build_persisted_session_history(
    *,
    working_set_messages: list[dict[str, object]],
    final_content: str,
    include_final_assistant: bool,
) -> list[dict[str, object]]:
    """Build next in-memory session history from working-set messages and final output."""
    history = copy_replay_history(working_set_messages)
    if include_final_assistant:
        history.append({"role": "assistant", "content": final_content})
    return history


def _estimate_history_tokens(history: list[dict[str, object]], *, model: str | None) -> int:
    from hal.runtime.engine.session_compaction import estimate_history_tokens

    return estimate_history_tokens(history, model=model)


def _normalize_checkpoint(text: str) -> str:
    from hal.runtime.engine.session_compaction import normalize_checkpoint

    return normalize_checkpoint(text)


def _request_tool_definitions(engine: Any) -> list[dict[str, Any]] | None:
    try:
        tools = getattr(engine, "tools", None)
        if tools is None or not hasattr(tools, "get_definitions"):
            return None
        definitions = tools.get_definitions()
        return definitions or None
    except Exception:
        return None


def _estimate_request_bytes_for_replay(
    engine: Any,
    messages: list[dict[str, object]],
    *,
    model: str | None,
) -> int:
    return estimate_messages_request_bytes(
        messages,
        model=model or "",
        tools=_request_tool_definitions(engine),
    )


@dataclass(frozen=True, slots=True)
class SessionCompactionSettings:
    """Resolved runtime settings for in-session history compaction."""

    token_budget: int
    request_bytes_threshold: int
    checkpoint_tokens: int
    history_image_replay: str
    tool_result_replay_max_bytes: int


@dataclass(frozen=True, slots=True)
class ManualSessionCompactionResult:
    """Outcome payload for explicit full-history compaction commands."""

    history: list[dict[str, object]]
    before_tokens: int
    after_tokens: int
    before_request_bytes: int
    after_request_bytes: int
    passes: int


def resolve_session_compaction_settings(engine_config: object) -> SessionCompactionSettings | None:
    """Resolve compaction settings, or None when compaction should be skipped."""
    session = getattr(engine_config, "session", engine_config)
    if not bool(getattr(session, "auto_compaction_enabled", False)):
        return None

    token_budget = int(getattr(session, "compaction_token_budget", 0))
    request_bytes_threshold = int(getattr(session, "compaction_request_bytes_threshold", 0))
    if token_budget <= 0 and request_bytes_threshold <= 0:
        return None

    checkpoint_tokens = max(
        int(getattr(session, "compaction_checkpoint_tokens", 1200)),
        100,
    )
    return SessionCompactionSettings(
        token_budget=token_budget,
        request_bytes_threshold=max(request_bytes_threshold, 0),
        checkpoint_tokens=checkpoint_tokens,
        history_image_replay=str(getattr(session, "history_image_replay", "summary") or "summary"),
        tool_result_replay_max_bytes=max(
            int(getattr(session, "tool_result_replay_max_bytes", 0)),
            0,
        ),
    )


async def tick_session_lifecycle(engine: Any) -> None:
    """Clean up finished brief tasks after explicit session closure."""
    for session_id, state in list(engine._sessions.items()):
        if state.brief_task is not None:
            if state.brief_task.done():
                engine._sessions.pop(session_id, None)
                await state.event_publisher.close()


async def maybe_compact_session_history(
    engine: Any,
    *,
    session_id: str,
    history: list[dict[str, object]],
    token_model: str | None,
) -> list[dict[str, object]]:
    """Compact older session turns when in-memory history exceeds token budget."""
    settings = resolve_session_compaction_settings(engine._engine_config)
    if settings is None or not history:
        return history

    before_tokens = _estimate_history_tokens(history, model=token_model)
    replay_history, _ = slim_messages_for_replay(
        history,
        image_replay_mode=settings.history_image_replay,
        tool_result_max_bytes=settings.tool_result_replay_max_bytes,
    )
    before_request_bytes = _estimate_request_bytes_for_replay(
        engine,
        replay_history,
        model=token_model,
    )
    if _history_within_budget(
        engine,
        history,
        replay_history=replay_history,
        token_model=token_model,
        settings=settings,
    ):
        return history

    compacted, passes = await _compact_history_to_budget(
        engine,
        history=history,
        token_model=token_model,
        settings=settings,
    )
    after_tokens = _estimate_history_tokens(compacted, model=token_model)
    compacted_replay, _ = slim_messages_for_replay(
        compacted,
        image_replay_mode=settings.history_image_replay,
        tool_result_max_bytes=settings.tool_result_replay_max_bytes,
    )
    after_request_bytes = _estimate_request_bytes_for_replay(
        engine,
        compacted_replay,
        model=token_model,
    )
    if after_tokens >= before_tokens:
        if before_request_bytes <= 0 or after_request_bytes >= before_request_bytes:
            return history

    logger.debug(
        "compaction: {} → {} tokens, {} → {} bytes ({} passes)",
        before_tokens,
        after_tokens,
        before_request_bytes,
        after_request_bytes,
        passes,
    )

    await _record_session_compaction(
        engine,
        session_id=session_id,
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        before_request_bytes=before_request_bytes,
        after_request_bytes=after_request_bytes,
        passes=passes,
    )
    return compacted


async def compact_full_session_history(
    engine: Any,
    *,
    session_id: str,
    history: list[dict[str, object]],
    token_model: str | None,
) -> ManualSessionCompactionResult:
    """Compact full in-memory history into one checkpoint for explicit /compact commands."""
    session_cfg = getattr(engine._engine_config, "session", None)
    history_image_replay = str(getattr(session_cfg, "history_image_replay", "summary") or "summary")
    tool_result_replay_max_bytes = max(
        int(getattr(session_cfg, "tool_result_replay_max_bytes", 0)),
        0,
    )
    checkpoint_tokens = max(int(getattr(session_cfg, "compaction_checkpoint_tokens", 1200)), 100)

    before_tokens = _estimate_history_tokens(history, model=token_model)
    replay_history, _ = slim_messages_for_replay(
        history,
        image_replay_mode=history_image_replay,
        tool_result_max_bytes=tool_result_replay_max_bytes,
    )
    before_request_bytes = _estimate_request_bytes_for_replay(
        engine,
        replay_history,
        model=token_model,
    )

    checkpoint = await engine._generate_session_checkpoint(
        list(history),
        token_model=token_model,
        fallback_on_error=False,
    )
    checkpoint = trim_text_to_token_budget(
        _normalize_checkpoint(checkpoint),
        checkpoint_tokens,
        model=token_model,
        suffix="\n\n[...checkpoint truncated]",
    )
    compacted = [{"role": "assistant", "content": checkpoint}]
    compacted_replay, _ = slim_messages_for_replay(
        compacted,
        image_replay_mode=history_image_replay,
        tool_result_max_bytes=tool_result_replay_max_bytes,
    )
    after_tokens = _estimate_history_tokens(compacted, model=token_model)
    after_request_bytes = _estimate_request_bytes_for_replay(
        engine,
        compacted_replay,
        model=token_model,
    )

    await _record_session_compaction(
        engine,
        session_id=session_id,
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        before_request_bytes=before_request_bytes,
        after_request_bytes=after_request_bytes,
        passes=_MANUAL_COMPACTION_PASSES,
    )
    return ManualSessionCompactionResult(
        history=compacted,
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        before_request_bytes=before_request_bytes,
        after_request_bytes=after_request_bytes,
        passes=_MANUAL_COMPACTION_PASSES,
    )


async def _compact_history_to_budget(
    engine: Any,
    *,
    history: list[dict[str, object]],
    token_model: str | None,
    settings: SessionCompactionSettings,
) -> tuple[list[dict[str, object]], int]:
    """Run bounded checkpointing passes until history fits within the token budget."""
    return await _compact_history_recursively(
        engine,
        compacted=list(history),
        token_model=token_model,
        settings=settings,
        remaining_passes=_MAX_COMPACTION_PASSES,
        completed_passes=0,
    )


async def _compact_history_recursively(
    engine: Any,
    *,
    compacted: list[dict[str, object]],
    token_model: str | None,
    settings: SessionCompactionSettings,
    remaining_passes: int,
    completed_passes: int,
) -> tuple[list[dict[str, object]], int]:
    if remaining_passes <= 0 or _history_within_budget(
        engine,
        compacted,
        replay_history=None,
        token_model=token_model,
        settings=settings,
    ):
        return compacted, completed_passes

    next_compacted = await _compact_history_pass(
        engine,
        compacted=compacted,
        token_model=token_model,
        settings=settings,
    )
    if next_compacted is None:
        return compacted, completed_passes
    return await _compact_history_recursively(
        engine,
        compacted=next_compacted,
        token_model=token_model,
        settings=settings,
        remaining_passes=remaining_passes - 1,
        completed_passes=completed_passes + 1,
    )


async def _compact_history_pass(
    engine: Any,
    *,
    compacted: list[dict[str, object]],
    token_model: str | None,
    settings: SessionCompactionSettings,
) -> list[dict[str, object]] | None:
    if not compacted:
        return None

    checkpoint = await engine._generate_session_checkpoint(
        compacted,
        token_model=token_model,
        fallback_on_error=True,
    )
    checkpoint = trim_text_to_token_budget(
        _normalize_checkpoint(checkpoint),
        settings.checkpoint_tokens,
        model=token_model,
        suffix="\n\n[...checkpoint truncated]",
    )
    return [{"role": "assistant", "content": checkpoint}]


def _history_within_budget(
    engine: Any,
    history: list[dict[str, object]],
    *,
    replay_history: list[dict[str, object]] | None,
    token_model: str | None,
    settings: SessionCompactionSettings,
) -> bool:
    within_tokens = True
    if settings.token_budget > 0:
        within_tokens = (
            _estimate_history_tokens(history, model=token_model) <= settings.token_budget
        )

    within_bytes = True
    if settings.request_bytes_threshold > 0:
        replay = replay_history
        if replay is None:
            replay, _ = slim_messages_for_replay(
                history,
                image_replay_mode=settings.history_image_replay,
                tool_result_max_bytes=settings.tool_result_replay_max_bytes,
            )
        within_bytes = (
            _estimate_request_bytes_for_replay(engine, replay, model=token_model)
            <= settings.request_bytes_threshold
        )

    return within_tokens and within_bytes


async def _record_session_compaction(
    engine: Any,
    *,
    session_id: str,
    before_tokens: int,
    after_tokens: int,
    before_request_bytes: int,
    after_request_bytes: int,
    passes: int,
) -> None:
    """Emit a session.compacted event via the session event publisher."""
    state = engine._sessions.get(session_id)
    if state is None:
        return
    await state.event_publisher.emit(
        "session.compacted",
        actor="engine",
        payload={
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "before_request_bytes": before_request_bytes,
            "after_request_bytes": after_request_bytes,
            "passes": passes,
        },
    )


def estimate_messages_request_bytes(
    messages: list[dict[str, object]],
    *,
    model: str = "",
    tools: list[dict[str, Any]] | None = None,
    max_tokens: int = 4096,
    temperature: float = 0,
) -> int:
    """Estimate serialized request body size for a chat-style messages payload."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    return len(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    )


def slim_messages_for_replay(
    messages: list[dict[str, object]],
    *,
    image_replay_mode: str,
    tool_result_max_bytes: int,
    preserve_latest_user: bool = True,
) -> tuple[list[dict[str, object]], bool]:
    """Rewrite replayed history to reduce request bytes before aggressive truncation is needed."""
    if not messages:
        return messages, False

    latest_user_index = None
    if preserve_latest_user:
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].get("role") == "user":
                latest_user_index = index
                break

    slimmed = copy.deepcopy(messages)
    changed = False
    for index, message in enumerate(slimmed):
        preserve_user = latest_user_index is not None and index == latest_user_index
        changed_this_message = _slim_message_for_replay(
            message,
            image_replay_mode=image_replay_mode,
            tool_result_max_bytes=tool_result_max_bytes,
            preserve_user_content=preserve_user,
        )
        changed = changed or changed_this_message
    return slimmed, changed


def _slim_message_for_replay(
    message: dict[str, object],
    *,
    image_replay_mode: str,
    tool_result_max_bytes: int,
    preserve_user_content: bool,
) -> bool:
    changed = False

    if "reasoning_content" in message:
        message.pop("reasoning_content", None)
        changed = True

    content = message.get("content")
    if isinstance(content, list) and not preserve_user_content:
        rewritten = _rewrite_multimodal_history_content(content, mode=image_replay_mode)
        if rewritten != content:
            message["content"] = rewritten
            content = rewritten
            changed = True

    if (
        message.get("role") == "tool"
        and isinstance(message.get("content"), str)
        and tool_result_max_bytes > 0
    ):
        trimmed = _trim_text_to_byte_budget(
            str(message.get("content") or ""),
            tool_result_max_bytes,
            suffix=_TOOL_RESULT_SUMMARY_SUFFIX,
        )
        if trimmed != message.get("content"):
            message["content"] = trimmed
            changed = True

    return changed


def _rewrite_multimodal_history_content(content: list[object], *, mode: str) -> str | list[object]:
    parts: list[str] = []
    image_items: list[dict[str, object]] = []

    for item in content:
        if not isinstance(item, dict):
            if item:
                parts.append(str(item))
            continue
        item_type = str(item.get("type", ""))
        if item_type == "text":
            text = item.get("text")
            if text:
                parts.append(str(text))
            continue
        if item_type == "image_url":
            image_items.append(copy.deepcopy(item))

    if not image_items:
        return content

    normalized_mode = mode if mode in {"full", "low_detail", "summary", "drop"} else "summary"
    if normalized_mode == "full":
        return content

    if normalized_mode == "low_detail":
        updated_images: list[dict[str, object]] = []
        for item in image_items:
            image_url = item.get("image_url")
            if not isinstance(image_url, dict):
                parts.insert(0, _HISTORY_IMAGE_SUMMARY)
                continue
            url = str(image_url.get("url", ""))
            if url.startswith("data:"):
                parts.insert(0, _HISTORY_IMAGE_SUMMARY)
                continue
            image_url["detail"] = "low"
            updated_images.append(item)
        if updated_images:
            text_block = [{"type": "text", "text": "\n".join(parts)}] if parts else []
            return updated_images + text_block
        return "\n".join([_HISTORY_IMAGE_SUMMARY, *parts]).strip()

    placeholder = _HISTORY_IMAGE_DROPPED if normalized_mode == "drop" else _HISTORY_IMAGE_SUMMARY
    joined = "\n".join([placeholder, *parts]).strip()
    return joined or placeholder


def _trim_text_to_byte_budget(text: str, max_bytes: int, *, suffix: str) -> str:
    if max_bytes <= 0 or len(text.encode("utf-8")) <= max_bytes:
        return text

    suffix_bytes = len(suffix.encode("utf-8"))
    if suffix_bytes >= max_bytes:
        return _fit_prefix_to_byte_budget(text, max_bytes)

    prefix = _fit_prefix_to_byte_budget(text, max_bytes - suffix_bytes).rstrip()
    return f"{prefix}{suffix}" if prefix else suffix.lstrip()


def _fit_prefix_to_byte_budget(text: str, max_bytes: int) -> str:
    if max_bytes <= 0 or not text:
        return ""

    low = 0
    high = len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if len(text[:mid].encode("utf-8")) <= max_bytes:
            low = mid
        else:
            high = mid - 1
    return text[:low]


# ---------------------------------------------------------------------------
# Session snapshot message assembly
# ---------------------------------------------------------------------------


def build_session_snapshot_messages(
    engine: Any,
    *,
    session_id: str,
    token_model: str | None = None,
) -> list[dict[str, object]]:
    """Build clean snapshot messages from system prompt and replay history."""
    state = engine._sessions.get(session_id)
    history_config = engine._history_config
    return assemble_message_sequence(
        system_message=build_system_message(
            engine.context.build_system_prompt(
                memory_budget_tokens=(history_config.memory_budget_tokens or None),
                token_model=token_model,
            )
        ),
        history=list(state.replay_history) if state else None,
    )


# ---------------------------------------------------------------------------
# Session checkpoint generation
# ---------------------------------------------------------------------------

_SESSION_COMPACTION_PROMPT = """\
You are compacting a HaL collaboration session into one checkpoint summary.

This is full-history compaction: after compaction, no raw prior turns remain.
Your checkpoint must preserve enough truth for seamless continuation.

Before final output, you may reason in <analysis>...</analysis>.
After </analysis>, output markdown that starts with `[Session Checkpoint]`.

Required sections in your checkpoint:

1. Primary Request and Intent
- Capture the user's explicit goals.
- Include preference changes, corrections, and boundary constraints.

2. Decisions and Constraints
- Record decisions already made and what was explicitly rejected.
- Keep only high-signal conclusions.

3. Concrete Work and Evidence
- Summarize concrete outcomes (files/commands/tool results/errors/fixes).
- Include only critical snippets or identifiers; avoid long dumps.

4. All User Messages (Non-tool)
- Capture key user messages, especially latest ones.
- Include short direct quotes for critical instructions or corrections.

5. Current Work
- Describe exactly what was in progress right before compaction.

6. Pending Tasks
- List explicit unfinished tasks requested by the user.

7. Next Step
- Provide one immediate next step that is directly aligned with the latest
  user request. Do not revive stale directions.

Rules:
- Prioritize factual continuity over style.
- If uncertain, say `unknown` instead of guessing.
- Do not add new plans that were not requested.
"""


async def generate_session_checkpoint(
    engine: Any,
    *,
    compactable_messages: list[dict[str, object]],
    token_model: str | None,
    fallback_on_error: bool = True,
) -> str:
    """Generate one compaction checkpoint for a slice of older messages."""
    from hal.runtime.engine.session_compaction import (
        build_fallback_checkpoint,
        estimate_history_tokens,
        normalize_checkpoint,
        render_history_for_compaction,
    )

    compacted_tokens = estimate_history_tokens(compactable_messages, model=token_model)
    prompt = (
        f"Compacting {len(compactable_messages)} older messages (~{compacted_tokens} tokens).\n\n"
        "Messages to compact:\n"
        f"{render_history_for_compaction(compactable_messages, model=token_model)}"
    )

    provider = getattr(engine.subagents, "provider", None) or engine.provider
    model = getattr(engine.subagents, "model", None) or engine.model
    chat = getattr(provider, "chat", None)
    if not callable(chat):
        if not fallback_on_error:
            raise RuntimeError("session compaction provider chat() is unavailable")
        return build_fallback_checkpoint(
            compacted_messages=len(compactable_messages),
            compacted_tokens=compacted_tokens,
        )

    try:
        response = await chat(
            messages=[
                {"role": "system", "content": _SESSION_COMPACTION_PROMPT},
                {"role": "user", "content": prompt},
            ],
            tools=[],
            model=model,
        )
        content = getattr(response, "content", None)
        if isinstance(content, str) and content.strip():
            return normalize_checkpoint(content)
        if not fallback_on_error:
            raise RuntimeError("session compaction returned empty checkpoint content")
    except Exception as e:
        logger.warning(f"Session compaction failed: {e}")
        if not fallback_on_error:
            raise

    return build_fallback_checkpoint(
        compacted_messages=len(compactable_messages),
        compacted_tokens=compacted_tokens,
    )
