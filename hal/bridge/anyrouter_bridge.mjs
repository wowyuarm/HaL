#!/usr/bin/env node

import { randomUUID } from "node:crypto";
import http from "node:http";
import { Readable } from "node:stream";

import {
  applyBridgeDefaults,
  isRetryableUpstreamError,
  normalizeThinkingEffort,
  shouldRetryUpstreamStatus,
} from "./anyrouter_bridge_core.mjs";

const DEFAULT_UPSTREAM = "https://anyrouter.top";
const DEFAULT_HOST = "127.0.0.1";
const DEFAULT_PORT = 3181;
const DEFAULT_USER_AGENT = "claude-cli/2.1.2 (external, cli)";
const DEFAULT_BETA =
  "claude-code-20250219,oauth-2025-04-20,fine-grained-tool-streaming-2025-05-14";
const DEFAULT_THINKING_EFFORT = "high";
const DEFAULT_REQUEST_TIMEOUT_MS = 45_000;
const DEFAULT_MAX_RETRIES = 2;
const DEFAULT_RETRY_BASE_DELAY_MS = 750;
const DEFAULT_STREAM_IDLE_TIMEOUT_MS = 30_000;
const CLIENT_REQUEST_ID_HEADER = "x-client-request-id";

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

function parsePositiveIntEnv(name, fallback) {
  const value = process.env[name];
  if (!value) {
    return fallback;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    return fallback;
  }
  return parsed;
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

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function retryDelayMs(attemptNumber, baseDelayMs) {
  return baseDelayMs * (2 ** Math.max(attemptNumber - 1, 0));
}

function buildBridgeError(message, details = {}) {
  return JSON.stringify({
    error: {
      type: "bridge_error",
      message,
      ...details,
    },
  });
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

async function fetchUpstreamWithRetries({
  reqId,
  method,
  requestPath,
  upstreamUrl,
  headers,
  body,
  timeoutMs,
  maxRetries,
  retryBaseDelayMs,
}) {
  let attempt = 0;
  while (attempt <= maxRetries) {
    attempt += 1;
    const abortController = new AbortController();
    const timeoutHandle = setTimeout(() => abortController.abort(), timeoutMs);

    try {
      const response = await fetch(upstreamUrl, {
        method,
        headers,
        body,
        redirect: "manual",
        signal: abortController.signal,
      });
      clearTimeout(timeoutHandle);

      if (shouldRetryUpstreamStatus(response.status) && attempt <= maxRetries) {
        response.body?.cancel?.();
        const delayMs = retryDelayMs(attempt, retryBaseDelayMs);
        logInfo(
          `#${reqId} ${method} ${requestPath} upstream ${response.status}, retrying in ${delayMs}ms (attempt ${attempt}/${maxRetries + 1})`,
        );
        await sleep(delayMs);
        continue;
      }

      return { response, abortController, attempt };
    } catch (error) {
      clearTimeout(timeoutHandle);
      if (!isRetryableUpstreamError(error) || attempt > maxRetries) {
        throw error;
      }
      const message = error instanceof Error ? error.message : String(error);
      const delayMs = retryDelayMs(attempt, retryBaseDelayMs);
      logInfo(
        `#${reqId} ${method} ${requestPath} transient error "${message}", retrying in ${delayMs}ms (attempt ${attempt}/${maxRetries + 1})`,
      );
      await sleep(delayMs);
    }
  }

  throw new Error("unreachable");
}

async function forwardResponseBody({
  reqId,
  method,
  requestPath,
  upstreamResponse,
  res,
  abortController,
  streamIdleTimeoutMs,
}) {
  if (!upstreamResponse.body) {
    res.end();
    return;
  }

  const upstreamStream = Readable.fromWeb(upstreamResponse.body);
  let idleTimer = null;
  let chunkCount = 0;
  let settled = false;

  const finish = () => {
    if (settled) {
      return false;
    }
    settled = true;
    if (idleTimer) {
      clearTimeout(idleTimer);
      idleTimer = null;
    }
    return true;
  };

  const resetIdleTimer = () => {
    if (idleTimer) {
      clearTimeout(idleTimer);
    }
    idleTimer = setTimeout(() => {
      const message = `upstream stream idle timeout after ${streamIdleTimeoutMs}ms`;
      logInfo(`#${reqId} ${method} ${requestPath} ${message}`);
      abortController.abort();
      upstreamStream.destroy(new Error(message));
      if (chunkCount === 0 && !res.headersSent && !res.writableEnded) {
        res.writeHead(504, { "content-type": "application/json" });
        res.end(buildBridgeError(message, { reason: "upstream_stream_idle_timeout" }));
        finish();
        return;
      }
      if (!res.writableEnded) {
        res.destroy(new Error(message));
      }
      finish();
    }, streamIdleTimeoutMs);
  };

  await new Promise((resolve) => {
    const cleanupAndResolve = () => {
      finish();
      resolve();
    };

    res.on("close", () => {
      abortController.abort();
      upstreamStream.destroy();
      cleanupAndResolve();
    });

    upstreamStream.on("data", (chunk) => {
      chunkCount += 1;
      resetIdleTimer();
      if (!res.write(chunk)) {
        upstreamStream.pause();
        res.once("drain", () => {
          if (!settled) {
            upstreamStream.resume();
          }
        });
      }
    });

    upstreamStream.on("end", () => {
      if (!res.writableEnded) {
        res.end();
      }
      cleanupAndResolve();
    });

    upstreamStream.on("error", (error) => {
      if (!res.headersSent && !res.writableEnded) {
        res.writeHead(502, { "content-type": "application/json" });
        res.end(buildBridgeError(error instanceof Error ? error.message : String(error)));
      } else if (!res.writableEnded) {
        res.destroy(error instanceof Error ? error : new Error(String(error)));
      }
      cleanupAndResolve();
    });

    resetIdleTimer();
  });
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
const defaultThinkingEffort = normalizeThinkingEffort(
  process.env.ANYROUTER_DEFAULT_THINKING_EFFORT,
  DEFAULT_THINKING_EFFORT,
);
const requestTimeoutMs = parsePositiveIntEnv(
  "ANYROUTER_REQUEST_TIMEOUT_MS",
  DEFAULT_REQUEST_TIMEOUT_MS,
);
const maxRetries = parsePositiveIntEnv("ANYROUTER_MAX_RETRIES", DEFAULT_MAX_RETRIES);
const retryBaseDelayMs = parsePositiveIntEnv(
  "ANYROUTER_RETRY_BASE_DELAY_MS",
  DEFAULT_RETRY_BASE_DELAY_MS,
);
const streamIdleTimeoutMs = parsePositiveIntEnv(
  "ANYROUTER_STREAM_IDLE_TIMEOUT_MS",
  DEFAULT_STREAM_IDLE_TIMEOUT_MS,
);
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

      payload = applyBridgeDefaults(payload, {
        forceStream,
        injectClaudeCodeSystem,
        defaultThinking,
        defaultThinkingEffort,
      });
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
    if (!upstreamHeaders.has(CLIENT_REQUEST_ID_HEADER)) {
      upstreamHeaders.set(CLIENT_REQUEST_ID_HEADER, randomUUID());
    }

    const upstreamUrl = `${upstream}${requestUrl}`;
    const { response: upstreamResponse, abortController, attempt } =
      await fetchUpstreamWithRetries({
        reqId,
        method,
        requestPath,
        upstreamUrl,
        headers: upstreamHeaders,
        body: upstreamBody.length > 0 ? upstreamBody : undefined,
        timeoutMs: requestTimeoutMs,
        maxRetries,
        retryBaseDelayMs,
      });

    const elapsed = Date.now() - startedAt;
    logInfo(
      `#${reqId} ${method} ${requestPath} -> ${upstreamResponse.status} (${elapsed}ms, attempt ${attempt})`,
    );
    logDebug(
      `#${reqId} upstream content-type=${upstreamResponse.headers.get("content-type") || "-"} request-id=${upstreamHeaders.get(CLIENT_REQUEST_ID_HEADER) || "-"}`,
    );
    copyResponseHeaders(upstreamResponse.headers, res);
    res.statusCode = upstreamResponse.status;

    await forwardResponseBody({
      reqId,
      method,
      requestPath,
      upstreamResponse,
      res,
      abortController,
      streamIdleTimeoutMs,
    });
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
      res.end(buildBridgeError(message));
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
