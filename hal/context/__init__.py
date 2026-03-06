"""Forward-compatible context package surface.

This module provides a stable import path (`hal.context`) while implementation
continues to live under `hal.core.context` during staged package reorganization.
"""

from __future__ import annotations

from hal.core.context.builder import ContextBuilder
from hal.core.context.compiler import CompiledSessionContext, ContextCompiler, SessionTurnRequest
from hal.core.context.messages import add_assistant_message, add_tool_result
from hal.core.context.metrics import MetricsCollector
from hal.core.context.prompt_layers import build_capabilities_prompt
from hal.core.context.registry import ContextRegistry
from hal.core.context.thread_mentions import detect_thread_mentions
from hal.core.context.units import (
    ContextUnit,
    ContextUnitManifest,
    SkillContextUnit,
    ThreadContextUnit,
)

__all__ = [
    "CompiledSessionContext",
    "ContextBuilder",
    "ContextCompiler",
    "ContextRegistry",
    "ContextUnit",
    "ContextUnitManifest",
    "MetricsCollector",
    "SessionTurnRequest",
    "SkillContextUnit",
    "ThreadContextUnit",
    "add_assistant_message",
    "add_tool_result",
    "build_capabilities_prompt",
    "detect_thread_mentions",
]
