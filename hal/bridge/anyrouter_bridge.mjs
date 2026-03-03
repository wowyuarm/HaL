#!/usr/bin/env node

import http from "node:http";
import { Readable } from "node:stream";

const DEFAULT_UPSTREAM = "https://anyrouter.top";
const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 3181;
const DEFAULT_USER_AGENT = "claude-cli/2.1.2 (external, cli)";
const DEFAULT_BETA =
  "claude-code-20250219,oauth-2025-04-20,fine-grained-tool-streaming-2025-05-14";
const DEFAULT_SYSTEM = "You are Claude Code, Anthropic's official CLI for Claude.";
const THINKING_ADAPTIVE_TYPE = "adaptive";
const DEFAULT_THINKING_EFFORT = "high";
const VALID_THINKING_EFFORTS = new Set(["low", "medium", "high", "max"]);

const HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
]);

const REQUEST_SKIP_HEADERS = new Set([
  ...HOP_HEADERS,
  "host",
  "content-length",
  "x-api-key",
  "user-agent",
  "x-app",
  "anthropic-beta",
  "anthropic-dangerous-direct-browser-access",
]);

const RESPONSE_SKIP_HEADERS = new Set([...HOP_HEADERS, "content-length"]);

function envBool(name, fallback) {
  const value = process.env[name];
  if (value === undefined) {
    return fallback;
  }
  return !["0", "false", "no", "off"].includes(value.toLowerCase());
}

function getFirstHeaderValue(value) {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  return value;
}

function normalizeUpstreamUrl(url) {
  return (url || DEFAULT_UPSTREAM).replace(/\/+$/, "");
}

function toSystemBlocks(systemField) {
  if (!systemField) {
    return [];
  }
  if (typeof systemField === "string") {
    return [{ type: "text", text: systemField }];
  }
  if (Array.isArray(systemField)) {
    return systemField.map((item) => {
      if (typeof item === "string") {
        return { type: "text", text: item };
      }
      if (item && typeof item === "object") {
        return { ...item };
      }
      return { type: "text", text: String(item) };
    });
  }
  return [{ type: "text", text: String(systemField) }];
}

function hasClaudeCodeSystem(systemBlocks) {
  const lowered = DEFAULT_SYSTEM.toLowerCase();
  return systemBlocks.some((block) => {
    if (!block || typeof block !== "object") {
      return false;
    }
    const text = typeof block.text === "string" ? block.text : "";
    return text.toLowerCase().includes(lowered);
  });
}

function ensureClaudeCodeSystem(body) {
  const blocks = toSystemBlocks(body.system);
  if (hasClaudeCodeSystem(blocks)) {
    body.system = blocks;
    return;
  }

  body.system = [
    {
      type: "text",
      text: DEFAULT_SYSTEM,
      cache_control: { type: "ephemeral" },
    },
    ...blocks,
  ];
}

function normalizeThinkingEffort(value) {
  if (typeof value !== "string") {
    return DEFAULT_THINKING_EFFORT;
  }
  const normalized = value.trim().toLowerCase();
  if (!VALID_THINKING_EFFORTS.has(normalized)) {
    return DEFAULT_THINKING_EFFORT;
  }
  return normalized;
}

function resolveThinkingType(thinking) {
  if (!thinking) {
    return "";
  }
  if (typeof thinking === "string") {
    return thinking.trim().toLowerCase();
  }
  if (typeof thinking === "object") {
    if (Array.isArray(thinking)) {
      return "";
    }
    const value = thinking.type;
    if (typeof value === "string") {
      return value.trim().toLowerCase();
    }
  }
  return "";
}

function ensureDefaultThinking(body) {
  if (body.thinking !== undefined && body.thinking !== null) {
    return;
  }
  body.thinking = { type: THINKING_ADAPTIVE_TYPE };
}

function ensureDefaultAdaptiveEffort(body, preferredEffort) {
  if (resolveThinkingType(body.thinking) !== THINKING_ADAPTIVE_TYPE) {
    return;
  }
  const outputConfig = body.output_config;
  if (!outputConfig || typeof outputConfig !== "object" || Array.isArray(outputConfig)) {
    body.output_config = { effort: preferredEffort };
    return;
  }
  if (outputConfig.effort === undefined || outputConfig.effort === null || outputConfig.effort === "") {
    outputConfig.effort = preferredEffort;
  }
}

function copyResponseHeaders(source, target) {
  for (const [name, value] of source.entries()) {
    const lower = name.toLowerCase();
    if (RESPONSE_SKIP_HEADERS.has(lower)) {
      continue;
    }
    target.setHeader(name, value);
  }
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(chunk);
  }
  return Buffer.concat(chunks);
}

const host = process.env.ANYROUTER_BRIDGE_HOST || DEFAULT_HOST;
const port = Number.parseInt(process.env.ANYROUTER_BRIDGE_PORT || `${DEFAULT_PORT}`, 10);
const upstream = normalizeUpstreamUrl(process.env.ANYROUTER_UPSTREAM);
const apiKey = process.env.ANYROUTER_API_KEY || "";
const userAgent = process.env.ANYROUTER_USER_AGENT || DEFAULT_USER_AGENT;
const xApp = process.env.ANYROUTER_X_APP || "cli";
const betaHeader = process.env.ANYROUTER_ANTHROPIC_BETA || DEFAULT_BETA;
const allowBrowserAccess = envBool("ANYROUTER_DIRECT_BROWSER_ACCESS", true);
const forceStream = envBool("ANYROUTER_FORCE_STREAM", true);
const injectClaudeCodeSystem = envBool("ANYROUTER_INJECT_CLAUDE_CODE_SYSTEM", true);
const defaultThinking = envBool("ANYROUTER_DEFAULT_THINKING", true);
const defaultThinkingEffort = normalizeThinkingEffort(process.env.ANYROUTER_DEFAULT_THINKING_EFFORT);
const verboseLogs = envBool("ANYROUTER_VERBOSE", false);
let requestCounter = 0;

function logInfo(message) {
  console.log(`[anyrouter-bridge] ${message}`);
}

function logDebug(message) {
  if (verboseLogs) {
    logInfo(message);
  }
}

if (!apiKey) {
  console.error("[anyrouter-bridge] Missing ANYROUTER_API_KEY");
  process.exit(1);
}

if (!Number.isInteger(port) || port <= 0 || port > 65535) {
  console.error(`[anyrouter-bridge] Invalid port: ${port}`);
  process.exit(1);
}

const server = http.createServer(async (req, res) => {
  const reqId = ++requestCounter;
  const startedAt = Date.now();
  const method = req.method || "UNKNOWN";
  const requestUrl = req.url || "/";
  const requestPath = requestUrl.split("?")[0];

  try {
    if (requestPath === "/health") {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ ok: true, upstream }));
      return;
    }

    if (method !== "POST" || !requestPath.startsWith("/v1/")) {
      logInfo(`#${reqId} ${method} ${requestPath} -> 404`);
      res.writeHead(404, { "content-type": "application/json" });
      res.end(JSON.stringify({ error: "Not found" }));
      return;
    }

    logInfo(`#${reqId} ${method} ${requestPath} accepted`);
    const rawBody = await readBody(req);
    const contentType = String(req.headers["content-type"] || "").toLowerCase();
    const isJson = contentType.includes("application/json");

    let upstreamBody = rawBody;
    if (isJson && requestPath === "/v1/messages") {
      let payload;
      try {
        payload = JSON.parse(rawBody.toString("utf-8") || "{}");
      } catch {
        res.writeHead(400, { "content-type": "application/json" });
        res.end(JSON.stringify({ error: "Invalid JSON body" }));
        return;
      }

      if (forceStream) {
        payload.stream = true;
      }
      if (injectClaudeCodeSystem) {
        ensureClaudeCodeSystem(payload);
      }
      if (defaultThinking) {
        ensureDefaultThinking(payload);
        ensureDefaultAdaptiveEffort(payload, defaultThinkingEffort);
      }
      payload.temperature = 1;
      upstreamBody = Buffer.from(JSON.stringify(payload));
      logDebug(
        `#${reqId} payload model=${payload.model || "-"} messages=${
          Array.isArray(payload.messages) ? payload.messages.length : 0
        } tools=${Array.isArray(payload.tools) ? payload.tools.length : 0} stream=${Boolean(
          payload.stream,
        )} thinking=${
          payload.thinking && typeof payload.thinking === "object"
            ? JSON.stringify(payload.thinking)
            : "none"
        } effort=${
          payload.output_config &&
          typeof payload.output_config === "object" &&
          !Array.isArray(payload.output_config) &&
          payload.output_config.effort
            ? String(payload.output_config.effort)
            : "none"
        }`,
      );
    }

    const upstreamHeaders = new Headers();
    for (const [name, value] of Object.entries(req.headers)) {
      if (value === undefined) {
        continue;
      }
      const lower = name.toLowerCase();
      if (REQUEST_SKIP_HEADERS.has(lower)) {
        continue;
      }
      upstreamHeaders.set(lower, getFirstHeaderValue(value));
    }

    const incomingApiKey = getFirstHeaderValue(req.headers["x-api-key"]);
    upstreamHeaders.set("x-api-key", incomingApiKey || apiKey);
    upstreamHeaders.set("user-agent", userAgent);
    upstreamHeaders.set("x-app", xApp);
    upstreamHeaders.set("anthropic-beta", betaHeader);
    if (allowBrowserAccess) {
      upstreamHeaders.set("anthropic-dangerous-direct-browser-access", "true");
    }
    if (!upstreamHeaders.has("anthropic-version")) {
      upstreamHeaders.set("anthropic-version", "2023-06-01");
    }
    if (!upstreamHeaders.has("content-type")) {
      upstreamHeaders.set("content-type", "application/json");
    }

    const upstreamUrl = `${upstream}${requestUrl}`;
    const upstreamResponse = await fetch(upstreamUrl, {
      method,
      headers: upstreamHeaders,
      body: upstreamBody.length > 0 ? upstreamBody : undefined,
      redirect: "manual",
    });

    const elapsed = Date.now() - startedAt;
    logInfo(
      `#${reqId} ${method} ${requestPath} -> ${upstreamResponse.status} (${elapsed}ms)`,
    );
    logDebug(
      `#${reqId} upstream content-type=${upstreamResponse.headers.get("content-type") || "-"}`,
    );
    copyResponseHeaders(upstreamResponse.headers, res);
    res.statusCode = upstreamResponse.status;

    if (upstreamResponse.body) {
      Readable.fromWeb(upstreamResponse.body).pipe(res);
    } else {
      res.end();
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const elapsed = Date.now() - startedAt;
    console.error(
      `[anyrouter-bridge] #${reqId} ${method} ${requestPath} error after ${elapsed}ms: ${message}`,
    );
    if (!res.headersSent) {
      res.writeHead(502, { "content-type": "application/json" });
    }
    if (!res.writableEnded) {
      res.end(
        JSON.stringify({
          error: {
            type: "bridge_error",
            message,
          },
        }),
      );
    }
  }
});

server.listen(port, host, () => {
  console.log(`[anyrouter-bridge] listening on http://${host}:${port}`);
  console.log(`[anyrouter-bridge] upstream ${upstream}`);
});

function shutdown(signal) {
  console.log(`[anyrouter-bridge] ${signal}, shutting down`);
  server.close(() => process.exit(0));
}

process.on("SIGINT", () => shutdown("SIGINT"));
process.on("SIGTERM", () => shutdown("SIGTERM"));
