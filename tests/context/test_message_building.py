from __future__ import annotations

from hal.context.message_building import build_user_message_content


def test_build_user_message_content_includes_web_attachments_before_text() -> None:
    content = build_user_message_content(
        "Please review these inputs.",
        media=None,
        dynamic_context="<context>Now</context>",
        attachments=[
            {
                "type": "image",
                "name": "diagram.png",
                "content": [{"type": "image", "image": "data:image/png;base64,abc"}],
            },
            {
                "type": "document",
                "name": "notes.md",
                "content": [
                    {"type": "text", "text": "<attachment name=notes.md>\nhello\n</attachment>"}
                ],
            },
            {
                "type": "file",
                "name": "report.pdf",
                "content": [
                    {
                        "type": "file",
                        "filename": "report.pdf",
                        "mimeType": "application/pdf",
                        "data": "data:application/pdf;base64,xyz",
                    }
                ],
            },
        ],
    )

    assert isinstance(content, list)
    assert content[0]["type"] == "image_url"
    assert content[-1]["type"] == "text"
    assert "<context>Now</context>" in content[-1]["text"]
    assert "<attachment name=notes.md>" in content[-1]["text"]
    assert "[Attached file: report.pdf (application/pdf)]" in content[-1]["text"]


def test_build_user_message_content_returns_images_for_attachment_only_turn() -> None:
    content = build_user_message_content(
        "",
        media=None,
        attachments=[
            {
                "type": "image",
                "name": "diagram.png",
                "content": [{"type": "image", "image": "data:image/png;base64,abc"}],
            }
        ],
    )

    assert content == [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}}]
