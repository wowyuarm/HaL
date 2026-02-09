from __future__ import annotations

from hal.core.memory.working import WorkingMemory


class DummySession:
    def __init__(self):
        self.messages: list[dict] = []

    def get_history(self):
        # Return more than default max
        return [{"role": "user", "content": str(i)} for i in range(100)]

    def add_message(self, role: str, content: str) -> None:
        self.messages.append({"role": role, "content": content})


def test_working_memory_get_history_trims_to_max_messages() -> None:
    wm = WorkingMemory(DummySession())
    hist = wm.get_history(max_messages=10)

    assert len(hist) == 10
    assert hist[0]["content"] == "90"
    assert hist[-1]["content"] == "99"


def test_working_memory_add_message_and_message_count() -> None:
    sess = DummySession()
    wm = WorkingMemory(sess)

    assert wm.message_count == 0
    wm.add_message("user", "hi")
    assert wm.message_count == 1
    assert sess.messages[0] == {"role": "user", "content": "hi"}
