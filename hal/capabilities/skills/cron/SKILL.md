---
name: cron
description: Schedule recurring tasks via the cron tool.
---

# Cron — Scheduled Tasks

Use the `cron` tool to schedule tasks that the agent executes autonomously.

## How It Works

The `message` you provide becomes the **agent's prompt in operator mode**.
Each time the job fires, the agent wakes up, receives your message as its
instruction, executes it (with full tool access), and optionally delivers
the result to the user.

**Key rule**: write `message` as an actionable instruction, not static text.

## Examples

Correct — agent checks and reports only when relevant:
```
cron(action="add",
     message="Check if @anthropic-ai/claude-code has a new release. Compare npm show version with the last known version. Only report if there is a newer version.",
     cron_expr="0 9 * * *")
```

Correct — agent performs a recurring task:
```
cron(action="add",
     message="Fetch the top 3 HackerNews stories and summarize them.",
     every_seconds=3600)
```

Wrong — static text, agent has nothing to execute:
```
cron(action="add", message="Time to take a break!", every_seconds=1200)
```

List / remove:
```
cron(action="list")
cron(action="remove", job_id="abc123")
```

## Time Expressions

| User says | Parameters |
|-----------|------------|
| every 20 minutes | every_seconds: 1200 |
| every hour | every_seconds: 3600 |
| every day at 8am | cron_expr: "0 8 * * *" |
| weekdays at 5pm | cron_expr: "0 17 * * 1-5" |
