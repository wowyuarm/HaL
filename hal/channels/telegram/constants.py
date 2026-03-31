"""Telegram channel constants."""

from telegram import BotCommand

# /context output constants
CTX_SYSTEM_PREVIEW_CHARS = 2400
CTX_MESSAGE_PREVIEW_CHARS = 900
CTX_OUTPUT_MAX_CHARS = 12000

MSG_SPLIT_MAX_LENGTH = 4000
TYPING_INDICATOR_INTERVAL_S = 4
PROGRESS_APPEND_MODE_CONCAT = "concat"
PROGRESS_APPEND_DEFAULT_SEPARATOR = "\n"
BOT_KEEPALIVE_SLEEP_S = 1
GIT_LOG_TIMEOUT_S = 5

# Commands registered with Telegram's command menu
BOT_COMMANDS = [
    BotCommand("start", "Start the bot"),
    BotCommand("brief", "Update thread briefs for this session"),
    BotCommand("compact", "Compact session history into one checkpoint"),
    BotCommand("drop", "End session without briefing"),
    BotCommand("context", "Show current LLM context"),
    BotCommand("help", "Show available commands"),
]

BOT_BOOTSTRAP_RETRIES = -1
