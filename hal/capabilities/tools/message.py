"""Message tool for sending messages to users."""

from typing import Any, Awaitable, Callable

from hal.bus.events import OutboundMessage
from hal.capabilities.tools.base import Tool


class MessageTool(Tool):
    """Tool to send messages to users on chat channels."""

    def __init__(
        self,
        send_callback: Callable[[OutboundMessage], Awaitable[None]] | None = None,
        default_channel: str = "",
        default_chat_id: str = "",
    ):
        self._send_callback = send_callback
        self._default_channel = default_channel
        self._default_chat_id = default_chat_id
        self._sent_in_turn = False

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current message context and reset per-turn state."""
        self._default_channel = channel
        self._default_chat_id = chat_id
        self._sent_in_turn = False

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[None]]) -> None:
        """Set the callback for sending messages."""
        self._send_callback = callback

    @property
    def sent_in_turn(self) -> bool:
        """Whether a message was successfully sent during the current turn."""
        return self._sent_in_turn

    @property
    def name(self) -> str:
        return "message"

    @property
    def description(self) -> str:
        return "Send a message to the user on a chat channel."

    @property
    def prompt(self) -> str:
        return (
            "Send a message to the user on a chat channel (Telegram etc.).\n"
            "This tool is NOT available in web sessions — web sessions deliver responses "
            "directly via WebSocket. Only use this in channel-based sessions.\n"
            "Use ONLY for cross-channel delivery (e.g., sending to a different chat). "
            "Do NOT use this to reply within the current conversation — that happens automatically.\n"
            "Omit chat_id and channel in normal use; they are auto-filled from the current turn context. "
            "Override chat_id only for cross-chat delivery (different group/DM).\n"
            "Supports media attachments via file path list."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The message content to send"},
                "channel": {
                    "type": "string",
                    "description": "Optional: target channel (telegram, discord, etc.)",
                },
                "chat_id": {"type": "string", "description": "Optional: target chat/user ID"},
                "media": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: list of file paths to attach (images, audio, documents)",
                },
            },
            "required": ["content"],
        }

    async def execute(
        self,
        content: str,
        channel: str | None = None,
        chat_id: str | None = None,
        media: list[str] | None = None,
        **kwargs: Any,
    ) -> str:
        channel = channel or self._default_channel
        chat_id = chat_id or self._default_chat_id

        if not channel or not chat_id:
            return "Error: No target channel/chat specified"

        if not self._send_callback:
            return "Error: Message sending not configured"

        msg = OutboundMessage(channel=channel, chat_id=chat_id, content=content, media=media or [])

        try:
            await self._send_callback(msg)
            self._sent_in_turn = True
            media_info = f" with {len(media)} attachments" if media else ""
            return f"Message sent to {channel}:{chat_id}{media_info}"
        except Exception as e:
            return f"Error sending message: {str(e)}"
