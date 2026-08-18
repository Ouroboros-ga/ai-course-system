# 推荐系统 LLM 智能升级

**日期**: 2026-08-18  
**状态**: ✅ 已部署到服务器  
**提交**: a270a539

---

## 问题背景

原推荐系统基于简单的**关键词匹配**，存在严重的误匹配问题：

### 问题案例
- 学生提到"控制"两个字 → 匹配课程 5 所有 7 个包含"控制"的知识节点
- 学生说"数学模型是怎么建立的" → 无法推荐跳转到"数学模型建立"节点

### 根本原因
1. **关键词匹配过于宽松**：
   - `workflow.py` 第 500-509 行：`len(requested_lower) >= 2` 就进行子串匹配
   - `learning_adjustment_service.py` 第 780 行：`_shares_keyword` 最初只要求 4 个字符

2. **缺少意图理解**：
   - 无法区分"困惑求助" vs "主动探索"
   - 无法判断学生的真实学习需求
   - 没有结合对话历史和认知状态

3. **没有知识结构判断**：
   - 不理解知识点之间的前置关系
   - 不判断"回顾前置是否真的能解决当前困惑"

---

## 解决方案

### 方案设计原则
- **最小改动**：不重构整个推荐系统，只在关键节点引入 LLM
- **不堆屎山**：LLM 失败时自动降级到原有逻辑，不影响主流程
- **智能推荐**：从"关键词匹配"升级到"理解学生意图"

### 实施内容

#### 1. 修复关键词匹配问题

**文件**: `backend/app/services/learning_adjustment_service.py`

```python
def _shares_keyword(left: str, right: str, min_span: int = 3, min_coverage: float = 0.6) -> bool:
    """要求至少 3 个字符，且覆盖较短标题的 60%"""
```

**文件**: `backend/app/platform/agents/edu/workflow.py` (第 499-522 行)

```python
# 要求至少 3 字符且覆盖率 >= 30%
if len(shorter) >= 3 and shorter in longer:
    if shorter == requested_lower and len(match_name) > len(requested_lower):
        if len(requested_lower) / len(match_name) < 0.3:
            continue  # 拒绝"控制"匹配"控制系统微分方程"
```

#### 2. 引入 LLM 智能推荐

**新增函数**: `_intelligent_recommend` (第 52-151 行)

```python
async def _intelligent_recommend(tools: TeachingTools, state: Mapping[str, Any]) -> str | None:
    """LLM 智能推荐：基于对话上下文、认知状态、知识图谱判断是否推荐复习/跳转。"""
```

**调用时机**: `propose_learning_adjustment` 节点（第 1319 行）

```python
# 2026-08-18: LLM 智能推荐逻辑
llm_recommended_concept_id = await _intelligent_recommend(tools, state)

proposal = await tools.learning_adjustment.propose(
    ...
    requested_concept_id=llm_recommended_concept_id or state.get("requested_concept_id"),
)
```

#### 3. LLM 推荐输入

LLM 综合以下信息做出推荐决策：

| 输入 | 来源 | 作用 |
|---|---|---|
| 学生提问 | `state["user_message"]` | 理解学生意图 |
| 当前知识点 | `state["current_concept_id"]` | 定位学生当前位置 |
| 教学动作 | `state["teaching_action"]` | 区分主动跳转 vs 被动回顾 |
| 学生请求的知识点名称 | `state["requested_concept_name"]` | 学生明确表达的学习目标 |
| 前置知识点列表 | `state["prerequisites"]` | 知识依赖关系 |
| 薄弱知识点列表 | `state["weak_concepts"]` | 学生认知薄弱点 |
| 相关知识点 | `state["graph_context"]["related_concepts"]` | 知识图谱结构 |
| 对话历史（最近3轮）| `state["conversation_turns"][-3:]` | 上下文理解 |

#### 4. LLM 推荐输出

```json
{
  "should_recommend": true/false,
  "recommended_concept_id": "概念ID" 或 null,
  "reason": "推荐理由（1-2句话）"
}
```

#### 5. 推荐原则

```python
# Prompt 中明确的判断原则：
- 如果学生明确表达想学某个知识点，且该知识点在相关概念中，则推荐
- 如果学生困惑，且困惑明显源于某个前置知识薄弱，则推荐该前置知识
- 如果学生只是随口问问，或当前知识点足以解答，则不推荐
- 避免过度推荐：只有在确实有帮助时才推荐
```

---

## 技术细节

### 触发条件
只在以下教学动作时调用 LLM 推荐：
- `requested_jump`：学生主动请求学习某个知识点
- `prerequisite_review`：系统检测到学生可能需要回顾前置知识

### 降级策略
```python
# 如果 LLM 不可用，降级到原有逻辑
if tools.llm is None:
    return None

try:
    # LLM 调用
    ...
except Exception:  # LLM 推荐失败不影响主流程
    return None
```

### 性能优化
- 只在需要时调用 LLM（2 个教学动作）
- 对话历史只取最近 3 轮
- 前置/薄弱知识点只取前 5 个
- 相关概念只取前 10 个
- Temperature = 0.3（较低，保证稳定性）
- Max tokens = 500（足够返回 JSON）

---

## 部署状态

### 提交信息
- **提交哈希**: a270a539
- **提交时间**: 2026-08-18
- **分支**: dev-liu
- **服务器**: root@120.26.104.247

### 部署步骤
1. ✅ 修复关键词匹配逻辑
2. ✅ 添加 LLM 智能推荐函数
3. ✅ 集成到 `propose_learning_adjustment` 节点
4. ✅ 推送到 Gitee 和 GitHub
5. ✅ 部署到服务器 `/opt/smartcarb/current`
6. ✅ 重启后端服务（smartcarb-backend）

### 验证
```bash
# 服务状态
systemctl status smartcarb-backend
# ● smartcarb-backend.service - SmartCarb AI Course System Backend
#      Active: active (running) since Tue 2026-08-18 19:18:43 CST

# Git 日志
cd /opt/smartcarb/current && git log -1 --oneline
# a270a53 feat: 推荐系统升级为 LLM 智能推荐
```

---

## 效果预期

### 修复前
| 场景 | 原行为 | 问题 |
|---|---|---|
| 学生提到"控制" | 匹配所有 7 个包含"控制"的节点 | 过度推荐 |
| 学生说"数学模型是怎么建立的" | 无法匹配 | 推荐缺失 |
| 学生随口问问 | 也会推荐跳转 | 打断学习流程 |

### 修复后
| 场景 | 新行为 | 优势 |
|---|---|---|
| 学生提到"控制" | LLM 判断意图，只在确实需要时推荐 | 避免误匹配 |
| 学生说"数学模型是怎么建立的" | LLM 理解"建立"的语义，推荐正确节点 | 语义理解 |
| 学生随口问问 | LLM 判断不需要推荐，不打断 | 避免过度推荐 |
| 学生困惑且前置薄弱 | LLM 结合认知状态，推荐前置知识 | 精准推荐 |

---

## 后续改进方向

### 短期（已完成）
- ✅ 修复关键词匹配过于宽松的问题
- ✅ 引入 LLM 智能推荐
- ✅ 结合对话历史、认知状态、知识图谱

### 中期（待完成）
- [ ] 收集 LLM 推荐的日志，分析推荐准确率
- [ ] 优化 Prompt，提升推荐质量
- [ ] 引入六维认知状态的细粒度判断
- [ ] 增加"学习渴望度"判断逻辑

### 长期（架构级）
- [ ] 将推荐系统独立为一个专门的 Agent
- [ ] 引入强化学习，根据学生反馈（接受/拒绝推荐）优化策略
- [ ] 建立推荐效果评估体系（A/B 测试）

---

## 相关文件

### 修改文件
1. `backend/app/platform/agents/edu/workflow.py`
   - 第 52-151 行：新增 `_intelligent_recommend` 函数
   - 第 499-522 行：修复 `resolve_concept` 的关键词匹配
   - 第 1319 行：调用 LLM 智能推荐

2. `backend/app/platform/agents/edu/state.py`
   - 第 80-81 行：新增 `intelligent_recommendation` 字段

3. `backend/app/services/learning_adjustment_service.py`
   - 第 38-82 行：改进 `_shares_keyword` 函数（min_span=3, min_coverage=0.6）

4. `frontend/src/app/components/learn/AgentAssistantBubble.vue`
   - 添加 `adjustment?.review_target` 检查，防止空推荐框显示

### 相关文档
- `AGENTS.md`：Agent 工作规则
- `docs/phase1/功能现状审计表.md`：功能现状记录

---

## 注意事项

1. **LLM 调用成本**：只在 2 个特定教学动作时调用，不会显著增加成本
2. **降级保证**：LLM 失败时自动降级到原有逻辑，不影响主流程
3. **数据隐私**：LLM Prompt 不包含敏感信息，只包含结构化的教学数据
4. **性能影响**：LLM 调用是异步的，不阻塞主流程；失败时超时自动返回 None

---

## 总结

这次改动是一个**最小但有效**的升级，让推荐系统从"关键词匹配"升级到"LLM 理解意图"。核心优势：

1. **不堆屎山**：只在关键节点引入 LLM，失败时自动降级
2. **智能推荐**：综合对话历史、认知状态、知识图谱做决策
3. **避免误匹配**：修复关键词匹配过于宽松的问题
4. **最小改动**：不重构整个系统，只在一个函数中实现

**部署状态**: ✅ 已部署到服务器并重启服务，可以开始测试。
