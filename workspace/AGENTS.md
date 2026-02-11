# Agent Instructions

## Reminders

When the user asks for a reminder at a specific time, use `exec` to run:
```
hal cron add --name "reminder" --message "Your message" --at "YYYY-MM-DDTHH:MM:SS" --deliver --to "USER_ID" --channel "CHANNEL"
```
Get USER_ID and CHANNEL from the current session context (e.g., `8281248569` and `telegram`).

**Do NOT just write reminders to MEMORY.md** — that won't trigger actual notifications.

### Progress Reporting During Long Operations

When executing a series of tool calls or long-running tasks, **use the `message` tool to keep the user informed during the process**:

1. **Before starting** a potentially lengthy operation (e.g., multiple file edits, complex analysis, spawn tasks), send a brief status:
   ```
   message(content="Starting analysis of the codebase, this may take a moment...")
   ```

2. **During execution**, provide periodic updates:
   - After completing significant milestones
   - When encountering unexpected delays
   - When switching between major phases of work
   - When waiting for subagent results that may take time

**Why this matters**: Users can't see your internal tool execution. Without progress updates during long operations, they might think you're stuck or unresponsive. Brief messages during execution build trust and allow them to adjust priorities mid-task.

## Subagent Delegation

Use `spawn` to delegate tasks that need independent work (research, file analysis, etc.).
- The result comes back directly — you can continue reasoning with it.
- When a spawn task may take a while, **briefly tell the user** you're working on it before calling spawn, so they know to wait.
- Set `background=true` only for genuinely long-running tasks where the user shouldn't have to wait.
- Subagents have up to 25 tool iterations. If they exhaust this limit, they will produce a progress summary rather than silently stopping — use it to decide whether to spawn a follow-up.

## Parallel Tool Execution

When you issue multiple tool calls in a single response, they run **concurrently** — not one after another. This applies to both your own tool calls and subagent tool calls.

- **Do**: return multiple independent calls together (e.g., two `spawn` tasks, or reading several files at once) for faster execution.
- **Don't**: return calls with order dependencies in the same response (e.g., write a file then exec it). Split them across turns instead — the first call's result will be available before you issue the second.

## Mid-conversation Follow-ups

If the user sends additional messages while you are still executing tools, those messages are **injected into your current context** at the next iteration — you will see them naturally as new user messages.

- You do **not** need to finish your current task first and handle them as a separate conversation.
- When you see a follow-up, integrate it: adjust your plan, expand scope, or acknowledge it in your final response.
- This only applies to messages from the **same session** (same channel + chat). Other sessions are unaffected.

## Heartbeat Tasks

`HEARTBEAT.md` is checked every 30 minutes. Use `fs` (action: edit) to manage periodic tasks:

```
- [ ] Check calendar and remind of upcoming events
- [ ] Scan inbox for urgent emails
```

When the user asks for a recurring task, update `HEARTBEAT.md` instead of creating a one-time cron job.

## Tool Execution vs. Code Display

**Important**: When showing examples of commands to execute, you must use the actual tool calls (`exec`, `spawn`, etc.), not just display code blocks.

- **Wrong**: Showing `gh repo view` in a code block — this is just text display, not execution.
- **Right**: Using `exec(command="gh repo view")` — this actually runs the command.

**Rule**: If you intend to execute something, use the appropriate tool. If you're just showing an example for the user to run themselves, make that clear in your explanation.
