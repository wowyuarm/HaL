"""Tool registry for dynamic tool management."""

from typing import Any

from hal.capabilities.tools.base import Tool

_HINT_RETRY = "Check the parameters and try again."
_HINT_AVAILABLE = "Available tools: {tools}"


def _with_hint(error: str, hint: str) -> str:
    """Append a hint line to an error message."""
    return f"{error}\nHint: {hint}"


class ToolRegistry:
    """
    Registry for agent tools.

    Allows dynamic registration and execution of tools.
    """

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def get_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in OpenAI format."""
        return [tool.to_schema() for tool in self._tools.values()]

    async def execute(self, name: str, params: dict[str, Any]) -> str:
        """
        Execute a tool by name with given parameters.

        Args:
            name: Tool name.
            params: Tool parameters.

        Returns:
            Tool execution result as string.

        Raises:
            KeyError: If tool not found.
        """
        tool = self._tools.get(name)
        if not tool:
            return _with_hint(
                f"Error: Tool '{name}' not found",
                _HINT_AVAILABLE.format(tools=", ".join(self.tool_names)),
            )

        try:
            errors = tool.validate_params(params)
            if errors:
                return _with_hint(
                    f"Error: Invalid parameters for tool '{name}': " + "; ".join(errors),
                    _HINT_RETRY,
                )
            return await tool.execute(**params)
        except Exception as e:
            return _with_hint(f"Error executing {name}: {str(e)}", _HINT_RETRY)

    @property
    def tool_names(self) -> list[str]:
        """Get list of registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
