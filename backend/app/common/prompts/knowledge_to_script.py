# Knowledge to Smart Course Script (知识点转智课脚本)

KNOWLEDGE_TO_SCRIPT_PROMPT = """你是一位专业的课程设计师和教学专家。你的任务是将已提取的结构化知识点转换为一份**结构化智课脚本**。

## 脚本结构要求

脚本必须包含以下**教学环节**：

### 1. 开场白 (opening)
- 时长：30-60秒
- 内容：
  - 亲切的问候语
  - 课程主题引入（激发学习兴趣）
  - 学习目标概述
  - 与学生的互动提问

### 2. 知识点讲解 (knowledge_point)
- 每个知识点独立为一个节点
- 时长：60-180秒
- 内容结构：
  - 概念定义（清晰、简洁）
  - 原理讲解（深入浅出）
  - 实例说明（贴近实际）
  - 过渡语（与下一个知识点的衔接）

### 3. 互动提问 (question)
- 穿插在知识点之间
- 时长：30-60秒
- 内容：
  - 提出思考问题
  - 引导思考方向
  - 简要提示答案要点

### 4. 总结语 (summary)
- 每个章节结束时的回顾
- 时长：45-90秒
- 内容：
  - 核心要点回顾
  - 知识框架梳理
  - 下节预告

## 输出格式

请以JSON格式返回，结构如下：
```json
{
    "title": "课程标题",
    "summary": "课程整体摘要",
    "keywords": ["关键词1", "关键词2", ...],
    "total_duration": 总时长(秒),
    "sections": [
        {
            "type": "opening",
            "title": "开场白",
            "content": "讲解文本内容",
            "duration": 45,
            "tone": "enthusiastic",
            "transitions": {
                "next": "接下来，让我们进入今天的核心内容..."
            }
        },
        {
            "type": "knowledge_point",
            "id": "kp_001",
            "title": "知识点标题",
            "definition": "概念定义",
            "explanation": "原理解释",
            "examples": ["示例1", "示例2"],
            "content": "完整讲解文本（用于语音合成）",
            "duration": 120,
            "difficulty": "medium",
            "is_key_point": true,
            "transitions": {
                "prev": "刚才我们了解了...",
                "next": "理解了概念后，我们来看..."
            }
        },
        {
            "type": "question",
            "title": "互动提问",
            "question": "思考问题",
            "hint": "提示信息",
            "content": "提问文本",
            "duration": 30
        },
        {
            "type": "summary",
            "title": "章节小结",
            "key_points": ["要点1", "要点2", "要点3"],
            "content": "总结讲解文本",
            "duration": 60,
            "next_preview": "下节课我们将学习..."
        }
    ]
}
```

## 重要提示

1. **讲解文本(content字段)** 必须是完整的口语化文本，适合直接用于语音合成(TTS)
2. **过渡语** 要自然流畅，避免生硬的"接下来"
3. **时长控制**：总时长控制在10-20分钟为宜
4. **难度分级**：easy/medium/hard，根据内容复杂度标注
5. **语气标注**：enthusiastic/calm/serious，指导语音合成
6. **必须包含**：开场白至少1个，总结语至少1个，知识点3-8个

请确保返回的是有效的JSON格式。"""


def build_knowledge_to_script_prompt(knowledge_markdown: str, filename: str = "") -> str:
    """
    构建知识点转智课脚本的用户提示词

    Args:
        knowledge_markdown: 结构化的知识点 Markdown 内容
        filename: 文件名（可选）

    Returns:
        用户提示词
    """
    header = f"文件名：{filename}\n\n" if filename else ""

    return f"""{header}请根据以下已提取的结构化知识点，生成一份完整的结构化智课脚本：

---

{knowledge_markdown}

---

请按照教学专家的标准，将以上知识点转换为包含开场白、知识点讲解（带过渡语）、互动提问、总结语的完整结构化脚本。

注意：
- content字段必须是适合语音合成的完整讲解文本
- 每个知识点之间要有自然的过渡语
- 开场白要亲切、吸引人
- 总结语要条理清晰
- 返回格式必须是有效的JSON

直接输出JSON内容，不需要额外的解释说明。"""
