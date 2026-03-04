"""Base class for agent tools."""

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ContextAwareTool(Protocol):
    """Optional protocol for tools that need per-session context."""

    def set_context(self, channel: str, chat_id: str) -> None:
        """Update channel/chat context before a new engine turn."""
        ...


class Tool(ABC):
    """
    Abstract base class for agent tools.

    Tools are capabilities that the agent can use to interact with
    the environment, such as reading files, executing commands, etc.
    """

    _TYPE_MAP = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name used in function calls."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Description of what the tool does."""
        pass

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema for tool parameters."""
        pass

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """
        Execute the tool with given parameters.

        Args:
            **kwargs: Tool-specific parameters.

        Returns:
            String result of the tool execution.
        """
        pass

    def get_side_effects(self, params: dict[str, Any]) -> dict[str, Any] | None:
        """Return side-effect metadata for tracking, or None if the call is read-only.

        Override in tools that modify state. The returned dict is merged into
        LoopMetadata by the engine. Recognized keys:
        - ``files_modified``: list[str]
        - ``commands_run``: list[str]
        """
        return None

    def validate_params(self, params: dict[str, Any]) -> list[str]:
        """Validate tool parameters against JSON schema. Returns error list (empty if valid)."""
        schema = self.parameters or {}
        if schema.get("type", "object") != "object":
            raise ValueError(f"Schema must be object type, got {schema.get('type')!r}")
        return self._validate(params, {**schema, "type": "object"}, "")

    def _validate(self, val: Any, schema: dict[str, Any], path: str) -> list[str]:
        t, label = schema.get("type"), path or "parameter"
        if t in self._TYPE_MAP and not isinstance(val, self._TYPE_MAP[t]):
            return [f"{label} should be {t}"]

        errors: list[str] = []
        errors.extend(self._validate_enum(val=val, schema=schema, label=label))
        if t in ("integer", "number"):
            errors.extend(self._validate_numeric_bounds(val=val, schema=schema, label=label))
            return errors
        if t == "string":
            errors.extend(self._validate_string_lengths(val=val, schema=schema, label=label))
            return errors
        if t == "object":
            errors.extend(self._validate_object_fields(val=val, schema=schema, path=path))
            return errors
        if t == "array":
            errors.extend(self._validate_array_items(val=val, schema=schema, path=path))
        return errors

    @staticmethod
    def _validate_enum(*, val: Any, schema: dict[str, Any], label: str) -> list[str]:
        if "enum" not in schema or val in schema["enum"]:
            return []
        return [f"{label} must be one of {schema['enum']}"]

    @staticmethod
    def _validate_numeric_bounds(*, val: Any, schema: dict[str, Any], label: str) -> list[str]:
        errors: list[str] = []
        if "minimum" in schema and val < schema["minimum"]:
            errors.append(f"{label} must be >= {schema['minimum']}")
        if "maximum" in schema and val > schema["maximum"]:
            errors.append(f"{label} must be <= {schema['maximum']}")
        return errors

    @staticmethod
    def _validate_string_lengths(*, val: Any, schema: dict[str, Any], label: str) -> list[str]:
        errors: list[str] = []
        if "minLength" in schema and len(val) < schema["minLength"]:
            errors.append(f"{label} must be at least {schema['minLength']} chars")
        if "maxLength" in schema and len(val) > schema["maxLength"]:
            errors.append(f"{label} must be at most {schema['maxLength']} chars")
        return errors

    def _validate_object_fields(self, *, val: Any, schema: dict[str, Any], path: str) -> list[str]:
        errors: list[str] = []
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in val:
                errors.append(f"missing required {path + '.' + key if path else key}")
        for key, item in val.items():
            if key in props:
                nested_path = f"{path}.{key}" if path else key
                errors.extend(self._validate(item, props[key], nested_path))
        return errors

    def _validate_array_items(self, *, val: Any, schema: dict[str, Any], path: str) -> list[str]:
        if "items" not in schema:
            return []
        errors: list[str] = []
        for index, item in enumerate(val):
            nested_path = f"{path}[{index}]" if path else f"[{index}]"
            errors.extend(self._validate(item, schema["items"], nested_path))
        return errors

    def to_schema(self) -> dict[str, Any]:
        """Convert tool to OpenAI function schema format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
