from __future__ import annotations

from hal.domain.message_payloads import estimate_content_chars


def test_estimate_content_chars_handles_text_payload() -> None:
    assert estimate_content_chars("hello") == 5


def test_estimate_content_chars_handles_multimodal_payload() -> None:
    payload = [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        {"type": "text", "text": "caption"},
    ]

    assert estimate_content_chars(payload) >= len("caption")


def test_estimate_content_chars_handles_nested_dict_payload() -> None:
    payload = {"text": "hello", "meta": {"reason": "world"}}

    assert estimate_content_chars(payload) == len("hello")
