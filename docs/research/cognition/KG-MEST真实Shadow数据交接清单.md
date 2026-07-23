# KG-MEST 真实 Shadow 数据交接清单

本清单用于准备一次**只读、假名化、经审批**的 KG-MEST Shadow bundle。它不是生产接入说明，不授权读取生产数据库，也不授权将结果写回 Memory、MasteryState、进度或推荐 API。

## 交付物

将下列五个 UTF-8 JSON 文件放在同一受控目录。不得把该目录提交到代码仓库。

```text
manifest.json
graph_nodes.json
graph_relations.json
review_decisions.json
learning_events.json
```

先在受控环境执行：

```powershell
$env:PYTHONPATH = 'research/product1_cognition'
backend/.venv/Scripts/python.exe research/product1_cognition/tools/run_shadow_bundle.py --bundle-dir <受控目录>
```

只有输出 `"status": "ok"` 才代表**一次只读 Shadow 回放完成**；它不代表算法已经批准影响学生。

## `graph_nodes.json`

来源为既有 `education_graph.GraphNode` 的课程隔离导出，并在导出层补齐 `course_id`。只交付本课程、已经接受且有证据的节点。

```json
{
  "node_id": "stable-knowledge-or-task-id",
  "course_id": "course-pseudonym-or-stable-course-key",
  "status": "accepted",
  "evidence_ids": ["evidence-stable-id"]
}
```

禁止：`proposed`/`needs_review` 节点、没有 `evidence_ids` 的节点、跨课程节点。

## `graph_relations.json`

来源为 `education_graph.GraphRelation`，并由导出层补齐 `course_id`。仅两类关系会被 KG-MEST 消费：

```json
{
  "relation_id": "stable-relation-id",
  "source_id": "pre-or-task-node-id",
  "target_id": "target-concept-id",
  "relation_type": "prerequisite_of 或 tests",
  "course_id": "same-course-key",
  "status": "accepted",
  "evidence_ids": ["evidence-stable-id"]
}
```

语义：

- `prerequisite_of`：`source_id` 是 `target_id` 的前置知识点；必须无环。
- `tests`：`source_id` 是可评分任务，`target_id` 是其测量的知识点；这会形成 Q-Matrix。

`CONTAINS`、`RELATED_TO`、R2 检索图结构边和自由文本 `KnowledgePoint.prerequisites` 不能替代这两类关系。

## `review_decisions.json`

每条被交付的 `prerequisite_of` 或 `tests` 关系均需一条已接受审核记录，来源为 `education_graph.ReviewDecision`：

```json
{
  "decision_id": "stable-review-id",
  "target_id": "relation_id",
  "target_type": "relation",
  "decision": "accepted",
  "evidence_bundle_id": "reviewed-evidence-bundle-id"
}
```

没有审核记录、审核不是 `accepted`、或没有 `evidence_bundle_id` 时，整份 bundle 被拒绝。

## `learning_events.json`

来源为 `domain.learning.LearningEvent` 的**单学生、单课程、获批假名化导出**。文件内可保留临时源整数范围以供本地适配器核对，但运行报告不会输出它们，且不得离开受控目录。

可消费的表现事实：

```json
{
  "event_id": "stable-event-id",
  "event_type": "quiz_answered 或 exercise_submitted",
  "student_id": 123,
  "course_id": 456,
  "sequence_number": 17,
  "timestamp": "2026-07-23T10:00:00+00:00",
  "metadata": {
    "quiz_id": "必须匹配 tests.source_id 的任务ID",
    "observed_score": 0.0,
    "attempt_group_key": "optional-stable-attempt-id"
  }
}
```

`observed_score` 范围为 `[0,1]`；若只有 `is_correct`，可由适配器转换为 `0/1`。同一次作答的 `quiz_correct` 与 `quiz_incorrect` 是派生事件，明确不消费，不能再作为独立评分证据。

普通 `question_asked` 不能用于表现轴。若需作为交互候选，必须同时有：

```json
{
  "candidate_source_event_id": "必须等于本 event_id",
  "concept_ids": ["已验收知识点ID"],
  "interaction_labels": {"confusion_risk": true},
  "interaction_label_confidences": {"confusion_risk": 0.91},
  "candidate_evidence_spans": {"confusion_risk": ["我不明白边界条件"]},
  "candidate_model_version": "model-id",
  "candidate_prompt_version": "prompt-id-or-none",
  "candidate_policy_version": "candidate-policy-id"
}
```

候选标签只产生独立交互状态；不会影响 `observed_performance_score`。低于既有阈值的候选不进入状态。

## `manifest.json`

最低字段：

```json
{
  "schema_version": "kg-mest-read-only-shadow-bundle/1.0",
  "data_classification": "protected_pseudonymized",
  "course_key": "course-key",
  "graph_snapshot_id": "accepted-snapshot-id",
  "student_key": "不可逆假名，不能等于原 student_id 字符串",
  "data_version": "protected-export-version",
  "source_scope": {"student_id": 123, "course_id": 456},
  "artifact_sha256": {
    "graph_nodes": "sha256:...",
    "graph_relations": "sha256:...",
    "review_decisions": "sha256:...",
    "learning_events": "sha256:..."
  },
  "shadow_gate": {
    "research_tests_passed": true,
    "contract_ablation_passed": true,
    "graph_snapshot_status": "accepted",
    "graph_course_isolation_verified": true,
    "interaction_gold_status": "approved_protected_gold",
    "privacy_review_status": "approved",
    "provider_contract_tests_passed": true,
    "append_only_audit_verified": true,
    "no_production_write_verified": true
  }
}
```

四个哈希必须对 canonical JSON 内容计算。可用研究区的 `artifact_sha256` 函数生成；任何输入变动后必须重新审核并更新清单，不能只改哈希。

## 人工签核前检查

1. 图谱审核人确认先修方向、无环性与 `tests` 的任务—知识点映射。
2. 数据负责人确认仅含被批准的单学生/单课程假名化记录。
3. 隐私负责人确认受保护数据使用范围和保留期限。
4. 评测负责人确认金标状态为 `approved_protected_gold`，并保留错误案例。
5. 平台负责人确认运行目录只读输入、报告 append-only，且没有任何生产写入路径。

未完成其中任一项时，bundle 应保持 `not_ready`，而不是把相应字段填为 `true`。
