from __future__ import annotations

import hal.context as context


def test_context_package_exports_compiler_registry_and_units() -> None:
    assert context.ContextBuilder.__name__ == "ContextBuilder"
    assert context.ContextCompiler.__name__ == "ContextCompiler"
    assert context.MetricsCollector.__name__ == "MetricsCollector"
    assert context.ContextRegistry.__name__ == "ContextRegistry"
    assert context.ThreadContextUnit.__name__ == "ThreadContextUnit"
    assert callable(context.add_assistant_message)
    assert callable(context.add_tool_result)
    assert callable(context.detect_thread_mentions)
    assert callable(context.build_capabilities_prompt)
