import test from "node:test";
import assert from "node:assert/strict";

import {
  applyBridgeDefaults,
  shouldRetryUpstreamStatus,
} from "../../hal/bridge/anyrouter_bridge_core.mjs";

test("applyBridgeDefaults fills missing Claude-like defaults", () => {
  const payload = {
    model: "claude-opus-4-6",
    messages: [{ role: "user", content: "hi" }],
  };

  const updated = applyBridgeDefaults(payload, {
    forceStream: true,
    injectClaudeCodeSystem: true,
    defaultThinking: true,
    defaultThinkingEffort: "high",
  });

  assert.equal(updated.stream, true);
  assert.deepEqual(updated.thinking, { type: "adaptive" });
  assert.equal(updated.output_config.effort, "high");
  assert.equal(updated.temperature, 1);
  assert.ok(Array.isArray(updated.system));
  assert.equal(updated.system[0].type, "text");
});

test("applyBridgeDefaults preserves explicit request fields", () => {
  const payload = {
    model: "claude-opus-4-6",
    messages: [{ role: "user", content: "hi" }],
    stream: false,
    thinking: { type: "enabled", budget_tokens: 1024 },
    output_config: { effort: "low" },
    temperature: 0.2,
    system: [{ type: "text", text: "You are Claude Code, Anthropic's official CLI for Claude." }],
  };

  const updated = applyBridgeDefaults(payload, {
    forceStream: true,
    injectClaudeCodeSystem: true,
    defaultThinking: true,
    defaultThinkingEffort: "high",
  });

  assert.equal(updated.stream, false);
  assert.deepEqual(updated.thinking, { type: "enabled", budget_tokens: 1024 });
  assert.equal(updated.output_config.effort, "low");
  assert.equal(updated.temperature, 0.2);
  assert.equal(updated.system.length, 1);
});

test("shouldRetryUpstreamStatus only retries transient upstream statuses", () => {
  assert.equal(shouldRetryUpstreamStatus(502), true);
  assert.equal(shouldRetryUpstreamStatus(503), true);
  assert.equal(shouldRetryUpstreamStatus(504), true);
  assert.equal(shouldRetryUpstreamStatus(401), false);
  assert.equal(shouldRetryUpstreamStatus(429), false);
});
