const DEFAULT_SYSTEM = "You are Claude Code, Anthropic's official CLI for Claude.";
const RETRYABLE_UPSTREAM_STATUSES = new Set([502, 503, 504]);
const VALID_THINKING_EFFORTS = new Set(["low", "medium", "high", "max"]);

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

export function normalizeThinkingEffort(value, fallback = "high") {
  if (typeof value !== "string") {
    return fallback;
  }
  const normalized = value.trim().toLowerCase();
  if (!VALID_THINKING_EFFORTS.has(normalized)) {
    return fallback;
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
  if (typeof thinking === "object" && !Array.isArray(thinking)) {
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
  body.thinking = { type: "adaptive" };
}

function ensureDefaultAdaptiveEffort(body, preferredEffort) {
  if (resolveThinkingType(body.thinking) !== "adaptive") {
    return;
  }
  const outputConfig = body.output_config;
  if (!outputConfig || typeof outputConfig !== "object" || Array.isArray(outputConfig)) {
    body.output_config = { effort: preferredEffort };
    return;
  }
  if (
    outputConfig.effort === undefined ||
    outputConfig.effort === null ||
    outputConfig.effort === ""
  ) {
    outputConfig.effort = preferredEffort;
  }
}

export function applyBridgeDefaults(payload, options) {
  const updated = { ...payload };

  if (options.forceStream && updated.stream === undefined) {
    updated.stream = true;
  }
  if (options.injectClaudeCodeSystem) {
    ensureClaudeCodeSystem(updated);
  }
  if (options.defaultThinking) {
    ensureDefaultThinking(updated);
    ensureDefaultAdaptiveEffort(updated, options.defaultThinkingEffort);
  }
  if (updated.temperature === undefined) {
    updated.temperature = 1;
  }

  return updated;
}

export function shouldRetryUpstreamStatus(status) {
  return RETRYABLE_UPSTREAM_STATUSES.has(status);
}

export function isRetryableUpstreamError(error) {
  if (!error) {
    return false;
  }

  const name = typeof error.name === "string" ? error.name.toLowerCase() : "";
  const code = typeof error.code === "string" ? error.code.toUpperCase() : "";
  const message = typeof error.message === "string" ? error.message.toLowerCase() : "";

  if (name === "aborterror") {
    return true;
  }
  if (["ECONNRESET", "EPIPE", "ECONNREFUSED", "ETIMEDOUT", "UND_ERR_CONNECT_TIMEOUT"].includes(code)) {
    return true;
  }
  return (
    message.includes("fetch failed") ||
    message.includes("timeout") ||
    message.includes("timed out") ||
    message.includes("socket hang up") ||
    message.includes("connection reset") ||
    message.includes("connection refused")
  );
}
