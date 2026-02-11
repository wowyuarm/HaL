# Tools

## fs — File Operations

Unified file tool with four actions: `read`, `write`, `edit`, `list`.

```
fs(action="read", path="file.txt")
fs(action="write", path="file.txt", content="...")
fs(action="edit", path="file.txt", old_text="...", new_text="...")
fs(action="list", path=".")
```

## exec — Shell Execution

Execute shell commands. Dangerous patterns are blocked. Output truncated at 10K chars.

```
exec(command="ls -la", working_dir="/path")
```

## web_search — Web Search

Search via Tavily API. Requires `tools.web.search.api_key` in config.

```
web_search(query="latest news", count=5)
```

## web_fetch — Fetch Web Page

Extract main content from a URL as markdown or plain text.

```
web_fetch(url="https://example.com", extractMode="markdown")
```

## message — Send Message

Send a message to a specific chat channel. Only use for cross-channel delivery (e.g., cron → Telegram). For normal conversation, reply directly with text.

```
message(content="Hello!", channel="telegram", chat_id="12345")
```

## spawn — Subagent Delegation

Delegate a task to a subagent with its own tools (fs, exec, web). The result
returns directly so you can continue reasoning with it.

```
spawn(task="Research topic X and summarize", label="research")
spawn(task="Long analysis", label="analysis", background=true)
```

- Default (sync): awaits completion, result returned directly
- `background=true`: fire-and-forget, result announced later via system message

## Cron — Scheduled Tasks

Use `exec` to manage scheduled tasks via the `hal cron` CLI:

```bash
# Recurring
hal cron add --name "morning" --message "Good morning!" --cron "0 9 * * *"

# One-time
hal cron add --name "meeting" --message "Meeting now!" --at "2025-01-31T15:00:00"

# With delivery to a channel
hal cron add --name "reminder" --message "Check inbox" --deliver --to "USER_ID" --channel "telegram"

# Manage
hal cron list
hal cron remove <job_id>
```

## Heartbeat

`HEARTBEAT.md` is checked every 30 minutes. Edit it with `fs` to manage periodic tasks:

```
fs(action="edit", path="HEARTBEAT.md", old_text="## Active Tasks\n", new_text="## Active Tasks\n\n- [ ] New task\n")
```
