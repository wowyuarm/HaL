"""Validation and event-safe shaping for web-submitted attachments."""

from __future__ import annotations

import base64
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote_to_bytes

from hal.utils.helpers import safe_filename
from hal.workspace.layout import WorkspaceLayout

_ALLOWED_ATTACHMENT_TYPES = {"image", "document", "file"}
_ALLOWED_PART_TYPES = {"text", "image", "file"}


def parse_web_attachments(value: Any) -> list[dict[str, Any]]:
    """Validate user-submitted attachments from the web client."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("attachments must be a list")

    attachments: list[dict[str, Any]] = []
    for index, raw_attachment in enumerate(value):
        if not isinstance(raw_attachment, dict):
            raise ValueError(f"attachments[{index}] must be an object")

        attachment_type = str(raw_attachment.get("type", "file")).strip() or "file"
        if attachment_type not in _ALLOWED_ATTACHMENT_TYPES:
            raise ValueError(f"attachments[{index}].type must be image, document, or file")

        name = str(raw_attachment.get("name", "")).strip()
        if not name:
            raise ValueError(f"attachments[{index}].name is required")

        raw_content = raw_attachment.get("content")
        if not isinstance(raw_content, list) or not raw_content:
            raise ValueError(f"attachments[{index}].content must be a non-empty list")

        parts: list[dict[str, Any]] = []
        for part_index, raw_part in enumerate(raw_content):
            if not isinstance(raw_part, dict):
                raise ValueError(f"attachments[{index}].content[{part_index}] must be an object")

            part_type = str(raw_part.get("type", "")).strip()
            if part_type not in _ALLOWED_PART_TYPES:
                raise ValueError(
                    f"attachments[{index}].content[{part_index}].type must be text, image, or file"
                )

            if part_type == "text":
                text = str(raw_part.get("text", ""))
                if not text.strip():
                    raise ValueError(f"attachments[{index}].content[{part_index}].text is required")
                parts.append({"type": "text", "text": text})
                continue

            if part_type == "image":
                image = str(raw_part.get("image", "")).strip()
                if not image:
                    raise ValueError(
                        f"attachments[{index}].content[{part_index}].image is required"
                    )
                part: dict[str, Any] = {"type": "image", "image": image}
                filename = str(raw_part.get("filename", "")).strip()
                if filename:
                    part["filename"] = filename
                parts.append(part)
                continue

            mime_type = str(raw_part.get("mimeType", "")).strip()
            data = str(raw_part.get("data", ""))
            if not mime_type:
                raise ValueError(f"attachments[{index}].content[{part_index}].mimeType is required")
            if not data:
                raise ValueError(f"attachments[{index}].content[{part_index}].data is required")
            part = {"type": "file", "mimeType": mime_type, "data": data}
            filename = str(raw_part.get("filename", "")).strip()
            if filename:
                part["filename"] = filename
            parts.append(part)

        normalized: dict[str, Any] = {
            "type": attachment_type,
            "name": name,
            "content": parts,
        }
        content_type = str(raw_attachment.get("contentType", "")).strip()
        if content_type:
            normalized["contentType"] = content_type
        attachments.append(normalized)

    return attachments


def materialize_web_attachments(
    layout: WorkspaceLayout,
    session_id: str,
    attachments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Persist uploaded web attachments into the local workspace and attach relative paths."""
    if not attachments:
        return []

    target_dir = layout.web_session_media_dir(session_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    materialized: list[dict[str, Any]] = []
    for index, attachment in enumerate(attachments, start=1):
        stored_path = _write_attachment_file(target_dir=target_dir, attachment=attachment, index=index)
        next_attachment = dict(attachment)
        next_attachment["path"] = str(stored_path.relative_to(layout.root))
        materialized.append(next_attachment)
    return materialized


def sanitize_event_attachments(attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trim attachment payloads for durable event storage while keeping UI previews."""
    sanitized: list[dict[str, Any]] = []
    for attachment in attachments:
        name = str(attachment.get("name", "")).strip()
        if not name:
            continue

        attachment_type = str(attachment.get("type", "file")).strip() or "file"
        content_type = str(attachment.get("contentType", "")).strip()
        stored_path = str(attachment.get("path", "")).strip()
        parts = attachment.get("content")
        if not isinstance(parts, list):
            continue

        image_parts = [
            {
                "type": "image",
                "image": str(part.get("image", "")),
                **(
                    {"filename": str(part.get("filename", "")).strip()}
                    if str(part.get("filename", "")).strip()
                    else {}
                ),
            }
            for part in parts
            if isinstance(part, dict)
            and str(part.get("type", "")) == "image"
            and str(part.get("image", "")).strip()
        ]

        if image_parts:
            sanitized_content = image_parts
        else:
            file_part = next(
                (
                    part
                    for part in parts
                    if isinstance(part, dict) and str(part.get("type", "")) == "file"
                ),
                None,
            )
            mime_type = (
                (str(file_part.get("mimeType", "")).strip() if isinstance(file_part, dict) else "")
                or content_type
                or ("text/plain" if attachment_type == "document" else "application/octet-stream")
            )
            sanitized_content = [
                {
                    "type": "file",
                    "filename": name,
                    "mimeType": mime_type,
                    "data": "",
                }
            ]

        item: dict[str, Any] = {
            "type": attachment_type if attachment_type in _ALLOWED_ATTACHMENT_TYPES else "file",
            "name": name,
            "content": sanitized_content,
        }
        if content_type:
            item["contentType"] = content_type
        if stored_path:
            item["path"] = stored_path
        sanitized.append(item)

    return sanitized


def _write_attachment_file(
    *,
    target_dir: Path,
    attachment: dict[str, Any],
    index: int,
) -> Path:
    name = str(attachment.get("name", "")).strip() or f"attachment-{index}"
    content_type = str(attachment.get("contentType", "")).strip()
    parts = attachment.get("content")
    if not isinstance(parts, list):
        raise ValueError("attachment content must be a list")

    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    stem = Path(safe_filename(name)).stem or f"attachment-{index}"

    for part in parts:
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type", "")).strip()
        if part_type == "image":
            image = str(part.get("image", "")).strip()
            if not image:
                continue
            mime_type, data = _decode_data_url(image)
            file_name = _build_file_name(
                stem=stem,
                original_name=name,
                mime_type=mime_type or content_type,
                timestamp=timestamp,
                index=index,
            )
            path = target_dir / file_name
            path.write_bytes(data)
            return path
        if part_type == "text":
            text = str(part.get("text", ""))
            if not text:
                continue
            file_name = _build_file_name(
                stem=stem,
                original_name=name,
                mime_type=content_type or "text/plain",
                timestamp=timestamp,
                index=index,
            )
            path = target_dir / file_name
            path.write_text(text, encoding="utf-8")
            return path
        if part_type == "file":
            data_url = str(part.get("data", ""))
            mime_type = str(part.get("mimeType", "")).strip() or content_type
            if not data_url:
                continue
            _, data = _decode_data_url(data_url)
            file_name = _build_file_name(
                stem=stem,
                original_name=str(part.get("filename", "")).strip() or name,
                mime_type=mime_type,
                timestamp=timestamp,
                index=index,
            )
            path = target_dir / file_name
            path.write_bytes(data)
            return path

    raise ValueError(f"Unable to materialize attachment: {name}")


def _build_file_name(
    *,
    stem: str,
    original_name: str,
    mime_type: str,
    timestamp: str,
    index: int,
) -> str:
    suffix = Path(original_name).suffix
    if not suffix and mime_type:
        suffix = mimetypes.guess_extension(mime_type, strict=False) or ""
    return safe_filename(f"{timestamp}-{index:02d}-{stem}{suffix}")


def _decode_data_url(data_url: str) -> tuple[str, bytes]:
    if not data_url.startswith("data:"):
        return "", data_url.encode("utf-8")

    header, _, payload = data_url.partition(",")
    mime_type = header[5:].split(";", 1)[0].strip()
    if ";base64" in header:
        return mime_type, base64.b64decode(payload)
    return mime_type, unquote_to_bytes(payload)
