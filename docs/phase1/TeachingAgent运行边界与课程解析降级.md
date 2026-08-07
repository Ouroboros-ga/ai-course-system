# TeachingAgent 运行边界与课程解析降级

## 生效语义

- Agent 的课程权限仍由 Course Access v1 在请求入口校验。
- R2 课程侧车、Evidence、GraphSnapshot 是**课程/文档版本级**产物；一次解析可供该课程的多个学生使用。
- KG-MEST Shadow 报告是可选的学生级增强输入，不再是 Agent 可用性的前置条件。
- 没有正式认知状态时，Agent 只获得 `unknown` 读模型；不会自行补写认知结论。

## 旧课件与解析失败

未建立或暂时失效的课程侧车不会返回“学生/课程未配置”503。Agent 返回
`fallback_required / COURSE_KNOWLEDGE_GRAPH_PENDING`；前端随后调用既有 V1
`/chat/ask` 并显示：

> 课程知识图谱正在解析或暂不可用，本次已使用普通课程问答。

这不是授权绕过：课程访问校验仍先执行。后续可按课程和文档版本批量生成
Evidence/图谱，但不需要为每名学生重复执行 KG-MEST。

## 最小化记录与连续性

`AgentLearningEvent`、`AgentTraceRecord` 和 `AgentConversationSession` 只保存：

- 学生、课程、会话、trace 标识；
- 教学动作、意图、节点名、错误/告警码、证据 ID；
- 有界结构化会话状态（当前概念、上一意图/动作、告警）。

它们不保存原始提问、完整回答、完整 Prompt、完整模型 trace 或 Evidence 文本。
前端为同一学生/课程复用 session ID；服务器端摘要 30 分钟无活动后失效。

## 认知边界

上述 Agent 审计和会话记录**不是**正式 `LearningEvent` 或评分型
`LearningEvidence`，不会写入 `observed_performance_score`、`MasteryState` 或
任何正式认知结论。只有独立契约下的 Quiz/Judge0 评分等来源才可产生评分证据。

## 迁移与回滚

`agent-log-minimization-v1` 先做 SQLite 预检，再将历史原始日志替换为最小化
红删标记，并记录幂等批次。回滚函数仅删除迁移账本；出于隐私原则，已清除的
原始内容不可恢复。
# 统一学习数据适配契约（2026-08-07）

学生学习页当前已通过 facade 写入 `LearningEvent`，并从 `StudentLearningProjection` 恢复
`release_id + outline_node_id` 的学习状态和最近锚点。TeachingAgent 仍不直接读取这些表；
`StudentStateTool`、`CognitionTool`、`LearningEventTool` 以及 `LearningContextPort` 等适配
接口继续标记为 `planned/unimplemented`。没有正式评分证据时只能返回 `unknown`，没有图谱映射
时返回 `not_available`，学习链路不可因认知/推荐刷新失败而阻断。

TeachingAgent 不直接访问学习表。未来通过 planned/unimplemented 的
`LearningContextPort`、`LearningProjectionPort`、`LearningEvidenceContextPort`
读取当前 `release_id + outline_node_id` 的学习摘要；`StudentStateTool` 只返回
exposure、cognition、recommendation 三段最小字段，`LearningEventTool` 只记录经过
治理的教学动作和幂等键。当前实现仍由学习门面 API 负责接线，不能把这些 Port/Tool
描述为已完成能力。
