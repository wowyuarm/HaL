"""Tests for tool registry error hint injection (#17)."""

from __future__ import annotations

from typing import Any

import pytest

from hal.capabilities.tools.base import Tool
from hal.capabilities.tools.registry import ToolRegistry


class _EchoTool(Tool):
    """Minimal tool for testing."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo the input."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }

    async def execute(self, text: str, **kwargs: Any) -> str:
        return text


class _BrokenTool(Tool):
    """Tool that always raises."""

    @property
    def name(self) -> str:
        return "broken"

    @property
    def description(self) -> str:
        return "Always fails."

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs: Any) -> str:
        raise RuntimeError("something broke")


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_EchoTool())
    reg.register(_BrokenTool())
    return reg


@pytest.mark.asyncio
async def test_unknown_tool_lists_available(registry: ToolRegistry) -> None:
    result = await registry.execute("nonexistent", {})
    assert "not found" in result
    assert "echo" in result
    assert "broken" in result
    assert "Hint:" in result
    assert "Available tools:" in result


@pytest.mark.asyncio
async def test_validation_error_has_retry_hint(registry: ToolRegistry) -> None:
    result = await registry.execute("echo", {})  # missing required 'text'
    assert "Invalid parameters" in result
    assert "Hint:" in result
    assert "try again" in result.lower()


@pytest.mark.asyncio
async def test_runtime_error_has_retry_hint(registry: ToolRegistry) -> None:
    result = await registry.execute("broken", {})
    assert "something broke" in result
    assert "Hint:" in result
    assert "try again" in result.lower()


@pytest.mark.asyncio
async def test_successful_execution_unchanged(registry: ToolRegistry) -> None:
    result = await registry.execute("echo", {"text": "hello"})
    assert result == "hello"
    assert "Hint:" not in result
