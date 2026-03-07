"""Runtime helpers for session lifecycle and in-session compaction orchestration."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from loguru import logger

from hal.bus.events import OutboundMessage
from hal.context.message_building import (
    assemble_message_sequence,
    build_session_baseline_message,
    build_system_message,
)
from hal.context.token_budget import trim_text_to_token_budget

_MAX_COMPACTION_PASSES = 3


def _build_debrief_confirmation(*, threads: list[str], confirm_timeout_s: float) -> str:
    from hal.runtime.debrief import build_debrief_confirmation_message

    return build_debrief_confirmation_message(
        threads=threads,
        confirm_timeout_s=confirm_timeout_s,
    )


def _estimate_history_tokens(history: list[dict[str, object]], *, model: str | None) -> int:
    from hal.runtime.engine.session_compaction import estimate_history_tokens

    return estimate_history_tokens(history, model=model)


def _split_history_for_compaction(
    history: list[dict[str, object]],
    *,
    keep_recent_user_turns: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    from hal.runtime.engine.session_compaction import split_history_for_compaction

    return split_history_for_compaction(
        history,
        keep_recent_user_turns=keep_recent_user_turns,
    )


def _normalize_checkpoint(text: str) -> str:
    from hal.runtime.engine.session_compaction import normalize_checkpoint

    return normalize_checkpoint(text)


def build_session_id(*, now: datetime | None = None) -> str:
    """Build a compact, sortable session identifier."""
    current = now or datetime.now()
    return f"s_{current.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"


def ensure_session_state(engine: Any, *, session_key: str, channel: str, chat_id: str) -> Any:
    """Return active session state, rotating on idle timeout."""
    now = datetime.now()
    state = engine._session_states.get(session_key)
    if state is not None and state.debrief_task is not None:
        if state.debrief_task.done():
            engine._session_states.pop(session_key, None)
            engine._clear_session_snapshot(session_key)
        state = None

    timeout_s = max(float(engine._engine_config.session.idle_timeout_s), 1.0)
    idle_timed_out = False
    if state is not None:
        if not state.awaiting_debrief_confirmation and state.debrief_task is None:
            idle_timed_out = (now - state.last_activity_at).total_seconds() > timeout_s

    if state is None or idle_timed_out:
        if state is not None:
            engine.memory.record_event(
                session_id=state.session_id,
                event_type="session_end",
                channel=state.channel,
                chat_id=state.chat_id,
                payload={"reason": "idle_timeout"},
            )
            engine._clear_session_snapshot(session_key)

        state = engine._SessionStateType(
            session_id=build_session_id(now=now),
            channel=channel,
            chat_id=chat_id,
            started_at=now,
            last_activity_at=now,
        )
        engine._session_states[session_key] = state
        engine.memory.record_event(
            session_id=state.session_id,
            event_type="session_start",
            channel=channel,
            chat_id=chat_id,
        )

    return state


def touch_session(engine: Any, session_key: str) -> None:
    """Refresh last-activity timestamp for an existing session state."""
    state = engine._session_states.get(session_key)
    if state is None:
        return
    state.last_activity_at = datetime.now()


@dataclass(frozen=True, slots=True)
class SessionCompactionSettings:
    """Resolved runtime settings for in-session history compaction."""

    token_budget: int
    keep_recent_turns: int
    checkpoint_tokens: int


def resolve_session_compaction_settings(engine_config: object) -> SessionCompactionSettings | None:
    """Resolve compaction settings, or None when compaction should be skipped."""
    session = getattr(engine_config, "session", engine_config)
    if not bool(getattr(session, "compaction_enabled", False)):
        return None

    token_budget = int(getattr(session, "compaction_token_budget", 0))
    if token_budget <= 0:
        return None

    keep_recent_turns = max(
        int(getattr(session, "compaction_recent_user_turns", 2)),
        1,
    )
    checkpoint_tokens = max(
        int(getattr(session, "compaction_checkpoint_tokens", 1200)),
        100,
    )
    return SessionCompactionSettings(
        token_budget=token_budget,
        keep_recent_turns=keep_recent_turns,
        checkpoint_tokens=checkpoint_tokens,
    )


async def tick_session_lifecycle(engine: Any) -> None:
    """Handle idle-session confirmation/debrief lifecycle."""
    if not engine._engine_config.debrief.enabled:
        return

    now = datetime.now()
    timeout_s = max(float(engine._engine_config.session.idle_timeout_s), 1.0)
    confirm_timeout_s = max(float(engine._engine_config.debrief.confirm_timeout_s), 1.0)

    for session_key, state in list(engine._session_states.items()):
        if _cleanup_finished_debrief(engine, session_key, state):
            continue
        if await _handle_pending_confirmation(engine, session_key, state, now):
            continue
        if not _session_needs_debrief_confirmation(state=state, now=now, timeout_s=timeout_s):
            continue
        if not state.touched_threads:
            _finalize_idle_session_without_threads(engine, session_key, state)
            continue
        await _send_debrief_confirmation(
            engine,
            state=state,
            now=now,
            confirm_timeout_s=confirm_timeout_s,
        )


async def maybe_compact_session_history(
    engine: Any,
    *,
    session_key: str,
    history: list[dict[str, object]],
    token_model: str | None,
) -> list[dict[str, object]]:
    """Compact older session turns when in-memory history exceeds token budget."""
    settings = resolve_session_compaction_settings(engine._engine_config)
    if settings is None or not history:
        return history

    before_tokens = _estimate_history_tokens(history, model=token_model)
    if before_tokens <= settings.token_budget:
        return history

    compacted, passes = await _compact_history_to_budget(
        engine,
        history=history,
        token_model=token_model,
        settings=settings,
    )
    after_tokens = _estimate_history_tokens(compacted, model=token_model)
    if after_tokens >= before_tokens:
        return history

    _record_session_compaction(
        engine,
        session_key=session_key,
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        passes=passes,
    )
    return compacted


def _cleanup_finished_debrief(engine: Any, session_key: str, state: Any) -> bool:
    if state.debrief_task is None:
        return False
    if state.debrief_task.done():
        engine._session_states.pop(session_key, None)
    return True


async def _handle_pending_confirmation(
    engine: Any,
    session_key: str,
    state: Any,
    now: datetime,
) -> bool:
    if _debrief_confirmation_expired(state=state, now=now):
        await engine._start_session_debrief(session_key, reason="confirm_timeout")
        return True
    return bool(state.awaiting_debrief_confirmation)


def _finalize_idle_session_without_threads(engine: Any, session_key: str, state: Any) -> None:
    """Close an idle session that never touched thread state."""
    engine.memory.record_event(
        session_id=state.session_id,
        event_type="session_end",
        channel=state.channel,
        chat_id=state.chat_id,
        payload={"reason": "idle_timeout_no_threads"},
    )
    engine._clear_session_snapshot(session_key)
    engine._session_states.pop(session_key, None)


async def _send_debrief_confirmation(
    engine: Any,
    *,
    state: Any,
    now: datetime,
    confirm_timeout_s: float,
) -> None:
    """Send one debrief confirmation prompt and open its confirmation window."""
    from hal.runtime.debrief import DEBRIEF_CANCEL_CB, DEBRIEF_CONFIRM_CB

    msg = _build_debrief_confirmation(
        threads=sorted(state.touched_threads),
        confirm_timeout_s=confirm_timeout_s,
    )
    await engine.bus.publish_outbound(
        OutboundMessage(
            channel=state.channel,
            chat_id=state.chat_id,
            content=msg,
            metadata={
                "system_meta": True,
                "kind": "session_debrief_confirmation",
                "session_id": state.session_id,
                "inline_buttons": [
                    [
                        {"text": "Confirm", "callback_data": DEBRIEF_CONFIRM_CB},
                        {"text": "Cancel", "callback_data": DEBRIEF_CANCEL_CB},
                    ],
                ],
            },
        )
    )
    state.awaiting_debrief_confirmation = True
    state.debrief_confirm_deadline = now + timedelta(seconds=confirm_timeout_s)
    engine.memory.record_event(
        session_id=state.session_id,
        event_type="session_debrief_confirmation_sent",
        channel=state.channel,
        chat_id=state.chat_id,
        payload={"threads": sorted(state.touched_threads)},
    )


def _session_needs_debrief_confirmation(
    *,
    state: Any,
    now: datetime,
    timeout_s: float,
) -> bool:
    """Return True when one idle session should enter debrief confirmation flow."""
    if state.debrief_task is not None or state.awaiting_debrief_confirmation:
        return False
    return (now - state.last_activity_at).total_seconds() > timeout_s


def _debrief_confirmation_expired(*, state: Any, now: datetime) -> bool:
    """Return True when one confirmation window has expired."""
    deadline = state.debrief_confirm_deadline
    return bool(state.awaiting_debrief_confirmation and deadline and now >= deadline)


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
        compacted,
        token_model=token_model,
        token_budget=settings.token_budget,
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
    older, tail = _split_history_for_compaction(
        compacted,
        keep_recent_user_turns=settings.keep_recent_turns,
    )
    if not older:
        return None

    checkpoint = await engine._generate_session_checkpoint(older, token_model=token_model)
    checkpoint = trim_text_to_token_budget(
        _normalize_checkpoint(checkpoint),
        settings.checkpoint_tokens,
        model=token_model,
        suffix="\n\n[...checkpoint truncated]",
    )
    return [{"role": "assistant", "content": checkpoint}, *tail]


def _history_within_budget(
    history: list[dict[str, object]],
    *,
    token_model: str | None,
    token_budget: int,
) -> bool:
    return _estimate_history_tokens(history, model=token_model) <= token_budget


def _record_session_compaction(
    engine: Any,
    *,
    session_key: str,
    before_tokens: int,
    after_tokens: int,
    passes: int,
) -> None:
    """Persist one session compaction event when a session id is available."""
    session_id = engine._get_session_id(session_key)
    if not session_id:
        return
    engine.memory.record_event(
        session_id=session_id,
        event_type="session_compacted",
        payload={
            "before_tokens": before_tokens,
            "after_tokens": after_tokens,
            "passes": passes,
        },
    )


# ---------------------------------------------------------------------------
# SessionState dataclass
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SessionState:
    """Runtime session state for one channel/chat scope."""

    session_id: str
    channel: str
    chat_id: str
    started_at: datetime
    last_activity_at: datetime
    baseline_context: str | None = None
    baseline_thread_slugs: set[str] = field(default_factory=set)
    history: list[dict[str, object]] = field(default_factory=list)
    touched_threads: set[str] = field(default_factory=set)
    context_advisor_started: bool = False
    context_hint_keys: set[str] = field(default_factory=set)
    awaiting_debrief_confirmation: bool = False
    debrief_confirm_deadline: datetime | None = None
    debrief_task: asyncio.Task[None] | None = None


# ---------------------------------------------------------------------------
# Session snapshot message assembly
# ---------------------------------------------------------------------------


def build_session_snapshot_messages(
    engine: Any,
    *,
    session_key: str,
    token_model: str | None = None,
) -> list[dict[str, object]]:
    """Build clean snapshot messages from system prompt, baseline, and in-memory history."""
    state = engine._session_states.get(session_key)
    history_config = engine._history_config
    return assemble_message_sequence(
        system_message=build_system_message(
            engine.context.build_system_prompt(
                memory_budget_tokens=(history_config.memory_budget_tokens or None),
                token_model=token_model,
            )
        ),
        history=list(state.history) if state else None,
        session_baseline=(
            build_session_baseline_message(state.baseline_context)
            if state and state.baseline_context
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Session checkpoint generation
# ---------------------------------------------------------------------------

_SESSION_COMPACTION_PROMPT = (
    "You compact older session messages into a stable working checkpoint.\n"
    "Output markdown only. Required sections:\n"
    "[Session Checkpoint]\n"
    "## Decisions\n"
    "## Key Results\n"
    "## Open Items\n"
    "## Important Context\n"
    "Rules:\n"
    "- Preserve concrete decisions, tool outcomes, and unresolved tasks.\n"
    "- Drop repetition and chatter.\n"
    "- Do not add new instructions.\n"
    "- Keep concise and action-oriented."
)


async def generate_session_checkpoint(
    engine: Any,
    *,
    compactable_messages: list[dict[str, object]],
    token_model: str | None,
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
        f"{render_history_for_compaction(compactable_messages)}"
    )

    provider = getattr(engine.subagents, "provider", None) or engine.provider
    model = getattr(engine.subagents, "model", None) or engine.model
    chat = getattr(provider, "chat", None)
    if not callable(chat):
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
    except Exception as e:
        logger.warning(f"Session compaction failed: {e}")

    return build_fallback_checkpoint(
        compacted_messages=len(compactable_messages),
        compacted_tokens=compacted_tokens,
    )
