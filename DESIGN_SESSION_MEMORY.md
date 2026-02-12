# 会话与记忆系统重构设计

## 当前系统分析

### 现有组件
1. **SessionManager** (`hal/session/manager.py`)
   - 按 `channel:chat_id` 存储对话历史
   - 每个会话一个JSONL文件（如 `telegram_12345.jsonl`）
   - 包含metadata行和消息行
   - 提供 `get_history(max_messages=50)` 方法

2. **EpisodicMemory** (`hal/core/memory/episodic.py`)
   - 存储"有意义"的交互记录
   - 单个 `episodes.jsonl` 文件
   - 包含摘要、工具使用、标签等信息
   - 支持压缩为MemoryTrace

3. **MemoryManager** (`hal/core/memory/manager.py`)
   - 协调EpisodicMemory和LongTermMemory
   - 提供 `get_context()` 方法组装记忆上下文

### 问题
- 数据分散在两个地方：会话历史和交互记录
- 工具消息处理不一致
- 难以统一查询和分析
- 上下文构建逻辑复杂

## 新系统设计

### 核心概念
**统一日志系统**：所有对话记录存储在每日JSONL文件中，按日期组织。

### 数据结构
```json
{
  "timestamp": "2026-02-12T10:30:45.123456",
  "channel": "telegram",
  "chat_id": "12345",
  "role": "user|assistant|tool",
  "content": "消息内容",
  "tool_name": "fs.read",  // 仅当role="tool"时
  "tool_result": "结果内容",  // 仅当role="tool"时
  "session_key": "telegram:12345",  // 可选，用于向后兼容
  "message_id": "msg_abc123",  // 可选，唯一标识符
  "metadata": {}  // 扩展字段
}
```

### 文件组织
```
~/.hal/logs/
├── 2026-02-12.jsonl
├── 2026-02-11.jsonl
├── 2026-02-10.jsonl
└── ...
```

### 新组件

1. **ConversationLogger** (`hal/core/conversation/logger.py`)
   - 统一记录所有对话消息
   - 按日期自动创建/切换日志文件
   - 提供查询接口

2. **ConversationContext** (`hal/core/conversation/context.py`)
   - 从日志文件加载最近50条非工具消息
   - 支持按channel、chat_id过滤
   - 替换SessionManager的 `get_history()` 功能

3. **MigrationScript** (`scripts/migrate_sessions_to_logs.py`)
   - 从现有sessions目录迁移数据
   - 从episodes.jsonl迁移数据
   - 保持数据完整性

### 接口变更

1. **AgentEngine** 不再使用 `SessionManager`
   - 改为使用 `ConversationLogger` 记录消息
   - 使用 `ConversationContext` 获取历史

2. **ContextBuilder** 不再依赖 `MemoryManager` 获取对话历史
   - 直接从 `ConversationContext` 获取最近50条非工具消息
   - 保持现有的记忆系统用于长期记忆

3. **Channels** 统一使用新的日志系统

### 向后兼容性

1. **临时适配层**
   - 在过渡期间保持 `SessionManager` 接口
   - 内部实现改为使用新系统

2. **数据迁移**
   - 提供迁移脚本
   - 保留原始数据备份

## 实施步骤

### 阶段1：基础组件
1. 创建 `ConversationLogger` 类
2. 创建 `ConversationContext` 类
3. 更新 `ContextBuilder` 使用新系统

### 阶段2：集成
1. 修改 `AgentEngine` 使用新系统
2. 更新所有Channels使用新系统
3. 移除 `SessionManager` 依赖

### 阶段3：迁移
1. 创建迁移脚本
2. 测试数据迁移
3. 清理旧系统

### 阶段4：测试
1. 单元测试新组件
2. 集成测试
3. 性能测试

## 优点

1. **简化架构**：单一日志系统替代两个独立系统
2. **统一查询**：所有对话数据在一个地方
3. **更好的工具消息处理**：明确标记工具消息
4. **易于分析**：按日期组织的日志文件
5. **向后兼容**：保持现有接口

## 风险与缓解

1. **数据丢失风险**
   - 实施前备份现有数据
   - 迁移脚本包含验证步骤

2. **性能影响**
   - 每日文件限制大小
   - 实现高效查询算法

3. **兼容性问题**
   - 保持临时适配层
   - 逐步迁移而非一次性替换