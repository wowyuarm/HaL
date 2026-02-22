# AnyRouter Integration

AnyRouter validates requests as Claude Code traffic. A direct Python request path can fail with:

```json
{"error":{"type":"new_api_error","message":"invalid claude code request"}}
```

The common failure mode is TLS fingerprint mismatch (`JA3/JA4`) from Python HTTP stacks.

## Recommended Architecture

Use a local Node bridge:

`HaL (Python/LiteLLM) -> localhost bridge (Node) -> https://anyrouter.top`

This keeps HaL unchanged while moving the upstream TLS fingerprint to Node.

## Start Bridge

```bash
hal anyrouter bridge --port 3181
```

The command reads `providers.anyrouter.api_key` from `~/.hal/auth.yaml` by default.
If `HTTPS_PROXY` / `HTTP_PROXY` is set, HaL enables Node `--use-env-proxy` automatically.
Bridge runs in verbose mode by default (request metadata, no message content).

Explicitly force verbose mode:

```bash
hal anyrouter bridge --port 3181 --verbose
```

Reduce log noise when needed:

```bash
hal anyrouter bridge --port 3181 --quiet
```

## Configure HaL

Point AnyRouter `api_base` to the local bridge:

```yaml
# ~/.hal/auth.yaml
providers:
  anyrouter:
    api_key: sk-xxx

# ~/.hal/config.yaml
providers:
  anyrouter:
    api_base: http://127.0.0.1:3181
    extra_headers:
      user-agent: "claude-cli/2.1.2 (external, cli)"
      x-app: cli
      anthropic-beta: "claude-code-20250219,oauth-2025-04-20,fine-grained-tool-streaming-2025-05-14,interleaved-thinking-2025-05-14"
```

Then run HaL normally:

```bash
hal agent -m "hello"
```

## Switch Models / Providers

Switch by changing `agents.defaults.model`:

- AnyRouter Claude: `"claude-opus-4-6"` (or `"anthropic/claude-opus-4-6"`)
- DeepSeek: `"deepseek-chat"`
- Moonshot: `"kimi-k2.5"`

HaL resolves provider from model keywords + configured keys.
To force AnyRouter, keep `providers.anyrouter.api_key` enabled and set model to Claude.

## Notes

- The bridge defaults to injecting Claude Code system prefix and forcing `stream=true`.
- **System prefix injection is required.** AnyRouter validates the Claude Code system prompt prefix; requests without it are rejected as `"invalid claude code request"`. Do not disable `--inject-system` in production.
- `--no-inject-system` and `--no-force-stream` are available for debugging only.
- The bridge can inject a default thinking budget (`--default-thinking / ANYROUTER_DEFAULT_THINKING`). Disabled by default; when enabled, uses a 2048-token budget unless the request already specifies thinking.
- Keep the bridge on localhost only.
