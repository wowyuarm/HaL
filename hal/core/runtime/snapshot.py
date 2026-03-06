"""Session snapshot message assembly helpers."""

from __future__ import annotations

from typing import Any

from hal.core.context.message_sequences import assemble_message_sequence, build_system_message
from hal.core.context.session_messages import build_session_baseline_message


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


__all__ = ["build_session_snapshot_messages"]
