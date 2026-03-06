from __future__ import annotations

import hal.runtime as runtime


def test_runtime_package_exports_core_orchestration_symbols() -> None:
    assert callable(runtime.execute_loop)
    assert callable(runtime.run_session_debrief)
    assert callable(runtime.maybe_compact_session_history)
    assert callable(runtime.generate_session_checkpoint)
    assert callable(runtime.trigger_summary_task)
