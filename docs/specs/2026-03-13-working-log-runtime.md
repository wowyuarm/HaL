# Working Log Runtime

**Date:** 2026-03-13  
**Status:** Active  
**Scope:** Native web runtime baseline

## Core Decision

HaL 的交互主线不再是 “browser 中的聊天应用”，而是：

- `thread` 作为长期协作入口与持久记忆容器
- `session` 作为一次真实协作的运行单元
- `episode/brief` 作为 session 向 thread 的沉淀结果
- `working-log` 作为 session 的完整事件证据层

这意味着 root UI object 不再是 message，而是：

`thread -> sessions -> turn -> events`

## Interaction Model

### Thread

- 左侧列表展示 thread
- 点击 thread 后，主界面首先看到该 thread 关联的 sessions
- 顶部展示该 thread 的 `BRIEF.md`

### Session

- 从 thread 内可直接 `new session`
- 也可显式选择多个 thread 创建 session
- 创建时必须有 `primary_thread`
- 其余被带入 context 的 thread 为 `mounted_threads`

### Working Log

session 主视图是 append-only 的 working log，而不是双向气泡聊天：

- `turn.started`
- `user.message`
- `context.compiled`
- `loop.started`
- `loop.iteration_started`
- `llm.request_started`
- `llm.response_completed`
- `tool.call_started`
- `tool.call_completed`
- `hook.injected`
- `message.injected`
- `assistant.message_completed`
- `turn.completed`

working log 必须足以：

- 重建 session 视图
- 审计某次 turn 当时到底用了什么 context
- 支撑 live tail 与后续更细粒度 streaming

## Lifecycle

- `/brief` 与 `/drop` 仍然是 human-in-the-loop 的 session 生命周期控制
- `brief` 后 session 在 thread 列表中显示为绿点
- `drop` 后 session 在 thread 列表中显示为灰点
- `brief` 产生的 worker 活动也要进入 session 事件流，但可在 UI 中低优先级折叠展示

## Runtime Boundary

Native web client 不是 `BaseChannel`。

划分如下：

- IM channels: adapter
- AgentEngine: session-first runtime
- Web server: native client interface

因此：

- native web 直接桥接 engine session lifecycle
- native web 直接订阅 `SessionEventPublisher`
- `channel:chat_id` 只保留给 adapter 路由，不再定义产品心智模型

## Storage

Canonical layout:

```text
work/
  threads/{slug}/
    BRIEF.md
    THREAD.yaml
    episodes/
    refs/sessions.jsonl
  sessions/{session_id}/
    manifest.json
    working-log.jsonl
```

Rules:

- session durable state lives under `work/sessions/{session_id}/`
- event log is append-only
- thread 与 session 通过 refs/index 关联，而不是物理嵌套复制

## Near-Term Build Order

1. Native web server 最小纵切：thread list, session list, session events, live WS
2. Working log 事件补齐与 UI 重建能力收敛
3. Session live view 前端改造成 turn/event 结构，而不是 message feed
4. 再考虑 token streaming、tool-progress、mid-loop intervention
