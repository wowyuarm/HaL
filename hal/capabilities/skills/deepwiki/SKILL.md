---
name: deepwiki
description: >
  Query DeepWiki documentation for any public GitHub repository directly via HTTP,
  without needing an MCP connection. Use when the agent needs to look up documentation,
  browse wiki structure, or ask questions about a GitHub repository's architecture and code.
  Triggers: "deepwiki", "look up repo docs", "what does this repo do", "ask deepwiki",
  "how does this repo work".
---

# DeepWiki

Query the [DeepWiki](https://deepwiki.com) API via JSON-RPC over HTTP.
No MCP client needed — just `curl` and `python3`.

## Commands

```bash
# List documentation topics for a repo
scripts/deepwiki.sh structure <owner/repo>

# View full documentation
scripts/deepwiki.sh contents <owner/repo>

# Ask a question about a repo
scripts/deepwiki.sh ask <owner/repo> "question"
```

Aliases: `s`, `c`, `a`.

## When to Use

- Understand an unfamiliar repository's architecture before working with it
- Look up how a specific feature or subsystem is implemented
- Get a structured overview (table of contents) of a repo's documentation
- Answer questions about a codebase without cloning or reading source directly

## Notes

- Free, no authentication required. Public GitHub repositories only.
- The `DEEPWIKI_ENDPOINT` env var can override the default API URL.
