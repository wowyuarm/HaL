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

The command reads `providers.anyrouter.apiKey` from `~/.hal/config.json` by default.
If `HTTPS_PROXY` / `HTTP_PROXY` is set, HaL enables Node `--use-env-proxy` automatically.

## Configure HaL

Point AnyRouter `apiBase` to the local bridge:

```json
{
  "providers": {
    "anyrouter": {
      "apiKey": "sk-xxx",
      "apiBase": "http://127.0.0.1:3181",
      "extraHeaders": {
        "user-agent": "claude-cli/2.1.2 (external, cli)",
        "x-app": "cli",
        "anthropic-beta": "claude-code-20250219,oauth-2025-04-20,fine-grained-tool-streaming-2025-05-14,interleaved-thinking-2025-05-14"
      }
    }
  }
}
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
To force AnyRouter, keep `providers.anyrouter.apiKey` enabled and set model to Claude.

## Notes

- The bridge defaults to injecting Claude Code headers and forcing `stream=true`.
- `--no-inject-system` and `--no-force-stream` are available for debugging behavior changes.
- Keep the bridge on localhost only.
