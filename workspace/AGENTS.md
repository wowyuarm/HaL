# Agent Instructions

## Reminders

When the user asks for a reminder at a specific time, use `exec` to run:
```
hal cron add --name "reminder" --message "Your message" --at "YYYY-MM-DDTHH:MM:SS" --deliver --to "USER_ID" --channel "CHANNEL"
```
Get USER_ID and CHANNEL from the current session context (e.g., `8281248569` and `telegram`).

**Do NOT just write reminders to MEMORY.md** — that won't trigger actual notifications.

## Subagent Delegation

Use `spawn` to delegate tasks that need independent work (research, file analysis, etc.).
- The result comes back directly — you can continue reasoning with it.
- When a spawn task may take a while, **briefly tell the user** you're working on it before calling spawn, so they know to wait.
- Set `background=true` only for genuinely long-running tasks where the user shouldn't have to wait.

## Heartbeat Tasks

`HEARTBEAT.md` is checked every 30 minutes. Use `fs` (action: edit) to manage periodic tasks:

```
- [ ] Check calendar and remind of upcoming events
- [ ] Scan inbox for urgent emails
```

When the user asks for a recurring task, update `HEARTBEAT.md` instead of creating a one-time cron job.
