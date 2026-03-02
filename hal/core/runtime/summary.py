"""Post-loop summary generation service."""

from __future__ import annotations

from loguru import logger

from hal.core.memory.manager import MemoryManager
from hal.core.runtime.loop import LoopMetadata
from hal.infra.providers.base import LLMProvider

_SUMMARY_SYSTEM_PROMPT = (
    "You summarize an AI agent's tool-calling session into "
    "a concise structured record. This summary will replace "
    "the agent's verbose response in conversation history so "
    "future LLM calls have compact context.\n\n"
    "Output format (use exactly these headers):\n"
    "**Outcome**: 1-2 sentences on what was accomplished.\n"
    "**Files modified**: comma-separated list, or 'none'.\n"
    "**Commands run**: key commands, or 'none'.\n"
    "**Open issues**: unresolved items, or 'none'.\n"
    "**Failed actions**: any actions that failed and why, or 'none'.\n\n"
    "Rules:\n"
    "- NEVER attribute the agent's actions to the user.\n"
    "- Keep failure details when present, including error reasons.\n"
    "- Output ONLY the structured summary, no preamble."
)

_MSG_CHAR_LIMIT = 5000
_TOTAL_CHAR_LIMIT = 60000


async def generate_summary(
    *,
    meta: LoopMetadata,
    final_content: str,
    channel: str,
    chat_id: str,
    provider: LLMProvider,
    model: str,
    memory: MemoryManager,
) -> None:
    """Generate a concise summary of a tool-heavy loop and persist it."""
    try:
        prompt = _build_summary_prompt(meta, final_content)

        response = await provider.chat(
            messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            tools=[],
            model=model,
        )

        if response.content:
            memory.record_conversation(
                channel=channel,
                chat_id=chat_id,
                role="user",
                content=f"[System Summary]\n{response.content}",
                entry_type="summary",
            )
            logger.info(f"[summary] recorded for {channel}:{chat_id}")
    except Exception as e:
        logger.warning(f"Failed to generate loop summary: {e}")


def _build_summary_prompt(meta: LoopMetadata, final_content: str) -> str:
    """Build the user prompt for summary generation from full loop messages."""
    parts: list[str] = [
        "<metadata>",
        f"iterations: {meta.iterations}",
        f"tools_used: {', '.join(meta.tools_used) or 'none'}",
        f"files_modified: {', '.join(meta.files_modified) or 'none'}",
        f"commands_run: {', '.join(meta.commands_run[-5:]) or 'none'}",
        f"has_side_effects: {meta.has_side_effects}",
        "</metadata>",
        "",
        "<session>",
    ]

    total = 0
    for msg in meta.loop_messages:
        role = msg.get("role", "")
        lines: list[str] = []

        tool_calls = msg.get("tool_calls")
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", "")
                if len(args) > _MSG_CHAR_LIMIT:
                    args = args[:_MSG_CHAR_LIMIT] + "…"
                lines.append(f"  tool_call: {name}({args})")

        content = str(msg.get("content", "") or "")
        if len(content) > _MSG_CHAR_LIMIT:
            content = content[:_MSG_CHAR_LIMIT] + "…"
        if content:
            lines.append(f"  {content}")

        entry = f"[{role}]\n" + "\n".join(lines) if lines else f"[{role}]"
        total += len(entry)
        if total > _TOTAL_CHAR_LIMIT:
            parts.append("[...earlier messages truncated...]")
            break
        parts.append(entry)

    parts.append("</session>")
    parts.append("")
    parts.append("<final_response>")
    parts.append(final_content[:_MSG_CHAR_LIMIT] if final_content else "")
    parts.append("</final_response>")
    return "\n".join(parts)
