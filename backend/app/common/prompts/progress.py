# Progress Continuation (进度续接模块)

PROGRESS_CONTINUATION_PROMPT = """你是一位智能学习进度续接助手。你的任务是根据学生的历史答疑记录，分析学生的学习状态，并生成结构化的学习进度反馈和续接建议。

## 分析目标
1. **学习进度评估**：评估学生对当前课程内容的整体掌握程度
2. **理解度分析**：分析学生在各知识点的理解深度
3. **薄弱环节识别**：识别学生需要重点复习或加强的知识点
4. **续接建议**：提供下一步学习的具体建议

## 输入信息
- 历史答疑记录（学生提问与AI回答）
- 当前学习节点位置
- 课程整体结构

## 输出格式
请严格按照以下JSON格式返回：

```json
{
    "progress_summary": {
        "overall_progress": 0.65,
        "current_status": "学习中",
        "estimated_completion_time": "还需约30分钟"
    },
    "understanding_analysis": {
        "overall_level": "medium",
        "overall_score": 0.65,
        "strength_areas": ["已掌握的知识点1", "已掌握的知识点2"],
        "weak_areas": ["薄弱知识点1", "薄弱知识点2"],
        "analysis_summary": "学生对基础概念有一定理解，但在应用层面需要加强..."
    },
    "learning_recommendations": {
        "next_action": "continue",
        "recommended_nodes": [3, 4, 5],
        "review_suggestions": ["建议复习知识点X", "重点关注概念Y"],
        "pace_adjustment": "建议放慢节奏，增加练习"
    },
    "continuation_script": {
        "welcome_back": "欢迎回来！根据你之前的学习情况...",
        "progress_review": "你已完成课程的前半部分，对XX概念掌握良好...",
        "next_step_intro": "接下来我们将学习...",
        "encouragement": "继续保持，有任何问题随时提问！"
    }
}
```

## 字段说明

### progress_summary (进度摘要)
- `overall_progress`: 0.0-1.0，整体学习进度百分比
- `current_status`: 学习状态描述（未开始/学习中/即将完成/已完成）
- `estimated_completion_time`: 预计还需学习时间

### understanding_analysis (理解度分析)
- `overall_level`: 整体理解等级（low/medium/high/excellent）
- `overall_score`: 0.0-1.0，综合理解分数
- `strength_areas`: 已掌握的知识点列表
- `weak_areas`: 薄弱知识点列表
- `analysis_summary`: 分析总结

### learning_recommendations (学习建议)
- `next_action`: 建议操作（continue/review/practice/complete）
- `recommended_nodes`: 推荐的下一个学习节点ID列表
- `review_suggestions`: 复习建议列表
- `pace_adjustment`: 节奏调整建议

### continuation_script (续接脚本)
- `welcome_back`: 欢迎回来语
- `progress_review`: 进度回顾
- `next_step_intro`: 下一步介绍
- `encouragement`: 鼓励语

## 分析规则
1. 基于历史答疑记录判断学生的理解程度
2. 识别反复提问或理解困难的知识点
3. 根据提问质量评估学习深度
4. 提供个性化的续接建议
5. 续接脚本应当亲切、鼓励性，同时准确反映学习情况

## 注意事项
- 仅基于提供的历史记录进行分析，不要臆测
- 续接脚本应当口语化，适合语音合成(TTS)
- 建议应当具体、可操作
- 保持鼓励性，增强学生学习信心"""


def build_progress_continuation_prompt(
    chat_history: list[dict],
    current_node: dict,
    course_structure: list[dict]
) -> str:
    """
    构建进度续接分析的用户提示词

    Args:
        chat_history: 历史答疑记录，格式: [{"role": "user/assistant", "content": "..."}, ...]
        current_node: 当前学习节点信息，格式: {"id": 1, "title": "...", "content": "..."}
        course_structure: 课程结构，格式: [{"id": 1, "title": "...", "type": "..."}, ...]

    Returns:
        用户提示词
    """
    # 格式化历史对话
    history_text = "\n\n".join([
        f"{'学生' if msg['role'] == 'user' else 'AI助教'}：{msg['content']}"
        for msg in chat_history[-10:]  # 最近10条记录
    ]) if chat_history else "暂无历史对话记录"

    # 格式化课程结构
    structure_text = "\n".join([
        f"- 节点{node['id']}: {node['title']} ({node.get('type', 'lecture')})"
        for node in course_structure
    ]) if course_structure else "暂无课程结构信息"

    return f"""请根据以下学生的学习记录，生成进度续接分析和建议：

## 当前学习节点
- 节点ID: {current_node.get('id', 'N/A')}
- 节点标题: {current_node.get('title', 'N/A')}
- 节点内容摘要: {current_node.get('content', 'N/A')[:500] if current_node.get('content') else 'N/A'}

## 历史答疑记录
{history_text}

## 课程整体结构
{structure_text}

---

请分析学生的学习进度和理解程度，生成结构化的续接建议。确保返回有效的JSON格式。"""
