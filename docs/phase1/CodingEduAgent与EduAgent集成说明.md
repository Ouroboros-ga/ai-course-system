# CodingEduAgent 与 EduAgent 集成说明

## 当前实现

```text
学生提交代码
  → ExperimentRun（服务端保存、Judge0 执行）
  → CodingEduAgent 规则诊断（POST /experiments/runs/{run_id}/diagnosis）
  → CodingDiagnosisRecord（课程/学生/run_id 隔离）
  → TeachingAgent 请求携带 code_submission_id = run_id
  → CodingDiagnosisPort + StudentHistoryPort
  → EduAgent 只读教学上下文
```

`Judge0SandboxPort` 不把 Judge0 token 暴露给 Agent。它只按 `run_id + course_id`
读取服务端已经保存的 `ExperimentRun` 和受限运行产物；跨课程或不存在的运行返回
`not_found`。`run_id` 是服务端生成的运行身份，不接受前端自行伪造的执行结果。

## CodingDiagnosis 边界

`CodingDiagnosisRecord` 只保存错误类别、摘要、调试步骤、提示、置信度、策略版本
和 `evidence_refs`。不保存源代码、完整 Judge0 token、原始聊天或完整 LLM trace。

它是 CodingEduAgent 的教学诊断上下文，不是正式 `LearningEvent`、
`LearningEvidence`、`MasteryState`，不会修改六维认知或表现分。只有实验最终评分服务
按既有策略写入正式评分型证据。

首版规则诊断是确定性的 `coding-diagnosis/rule-v1`：编译错误、运行错误、错误答案、
超时、内存超限和通过分别映射到有限的错误类别。未来可以增加受限解释模型，但模型
只能补充解释，不能改变 `ExperimentRun` 结果和正式证据。

## 学习历史边界

`StudentHistoryPort` 只读取当前 `(student_id, course_id)` 的最新六维状态、最近有限条
评分型证据和最近有限条代码诊断。它不返回聊天正文、答案全文、源代码或跨课程记录。
无数据返回 `status=unknown`，不得由 EduAgent 将 unknown 当作掌握结论。

前端在同一学生/课程内复用稳定的 `session_id`，服务端会话上下文仅保存有界结构化摘要，
不保存对话全文。代码工作区完成一次服务端运行后，应先创建/确认诊断，再把该 `run_id`
通过 `setCodeSubmissionId(run_id)` 或 `useLearningWorkspace` 的 `getCodeSubmissionId`
回调交给教学对话。

## 调试建议

1. 先查 `ExperimentRun`：确认 `run_id`、课程和学生一致，且 outcome 已不是 pending。
2. 调用 `GET /api/v1/experiments/runs/{run_id}/diagnosis?course_id=...`；为空时调用
   POST 生成规则诊断，再重试 TeachingAgent。
3. 查看 TeachingAgent trace 中的 `load_sandbox_context`、`load_coding_diagnosis`、
   `load_learning_history` 三个节点。诊断不可用只能产生降级警告，不能伪造结果。
4. 如果沙箱不可用，Agent 应显示 `CODE_SANDBOX_UNAVAILABLE`，不把空结果解释成代码通过。
5. 如果课程图谱/R2 不可用，仍走普通课程问答，并显示课程知识图谱待解析提示。

## 当前 Demo 限制

- 当前学习页还没有把完整的代码编辑器/实验提交 UI 嵌入对话面板；实验页与 API 已可
  创建 `ExperimentRun`。接入 UI 时必须使用服务端返回的 `run_id`，不得传 Judge0 token。
- 规则诊断不会自动替代教师审核，也不会直接发布提示或修改学生认知状态。
- 真实 Judge0、真实学生数据和付费模型不进入自动化测试；部署验收需单独做沙箱健康、
  超时/内存限制、恢复和跨课程权限验证。
# 统一学习投影边界（2026-08-07）

当前学习页的曝光/完成事实已由统一 facade 事件链承载；CodingEduAgent 不写入学习投影。
后续 `LearningProjectionPort` 读取 `release_id`、`outline_node_id`、`exposure_status`、
`completion_ratio` 和最近锚点，仍是 `planned/unimplemented`。Judge0 服务端评分才可形成正式
认知证据；代码诊断、观看和访问不能直接抬高 mastery。

CodingEduAgent 与 TeachingAgent 后续只消费统一学习上下文，不修改学习投影表。
planned/unimplemented 的 `LearningProjectionPort` 返回 `release_id`、
`outline_node_id`、`exposure_status`、`completion_ratio`；正式评分结果仍由服务端
写入认知证据。沙箱、认知和推荐不可用时必须返回 `unknown/pending/degraded`，不能
伪造掌握结论。

`LearningEvidenceContextPort`（planned/unimplemented）只接收正式 `evidence_id`，返回
`knowledge_node_key`、`source_release_id`、`outline_node_id`、`event_id` 和 `status`。
当前服务层已有非 Agent 的 `LearningEvidenceContext` upsert 适配器；评分证据落库后运行，
旧答题记录没有 release 身份时保持 unknown，不从 active release 反推。CodingEduAgent
不得把一次代码运行、诊断摘要或观看行为直接写成掌握证据。
