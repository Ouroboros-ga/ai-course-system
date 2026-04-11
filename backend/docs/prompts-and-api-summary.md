# 后端提示词与 API 实现总结

本文档汇总了所有已完成的提示词模块和 API 接口实现。

---

## 一、提示词模块 (Prompts)

### 1. 知识库问答提示词 (QA)

**文件路径**: `app/common/prompts/qa.py`

**功能**: 实现严格的知识库问答助手，确保回答忠于原文并标注引用。

**核心组件**:
- `QA_SYSTEM_PROMPT`: 系统提示词，定义回答规则
  - 绝对忠于原文，禁止幻觉
  - 必须标注引用 `(引用：知识点X)`
  - 找不到信息时回复：`抱歉，当前课程资料中未包含该信息。`
- `build_qa_prompt()`: 构建用户提示词

**使用场景**: 学生提问时，基于知识库内容生成带引用的准确回答。

---

### 2. 文档分析提示词 (Document Analysis)

**文件路径**: `app/common/prompts/document_analysis.py`

**功能**: 从文档内容中提取核心知识点，组织为结构化 Markdown。

**核心组件**:
- `KNOWLEDGE_EXTRACTION_PROMPT`: 系统提示词，定义提取规则
  - 全面准确提取关键信息
  - 按逻辑层次划分（总分、递进、并列）
  - 使用多级 Markdown 标题展现层级
  - 简洁精炼，格式规范
- `build_knowledge_extraction_prompt()`: 构建用户提示词

**输出格式**:
```markdown
# [文档主题概括]

## [一级知识点分类 1]
### [二级知识点 1.1]
- **核心概念**：[概念解释]
- **要点说明**：[详细说明]
```

**使用场景**: 文档上传后，自动提取结构化知识点。

---

### 3. 知识点转智课脚本提示词 (Knowledge to Script)

**文件路径**: `app/common/prompts/knowledge_to_script.py`

**功能**: 将提取的知识点转换为结构化智课脚本。

**核心组件**:
- `KNOWLEDGE_TO_SCRIPT_PROMPT`: 系统提示词，定义脚本结构
- `build_knowledge_to_script_prompt()`: 构建用户提示词

**脚本结构**:
1. **开场白** (opening): 30-60秒
   - 问候语、主题引入、学习目标、互动提问
2. **知识点讲解** (knowledge_point): 60-180秒
   - 概念定义、原理讲解、实例说明、过渡语
3. **互动提问** (question): 30-60秒
   - 思考问题、引导方向、提示要点
4. **总结语** (summary): 45-90秒
   - 要点回顾、框架梳理、下节预告

**输出格式**: JSON，包含 title, summary, keywords, total_duration, sections

**使用场景**: 知识点提取后，生成可语音合成的教学脚本。

---

### 4. 进度续接提示词 (Progress)

**文件路径**: `app/common/prompts/progress.py`

**功能**: 根据历史答疑记录分析学习进度，生成续接建议。

**核心组件**:
- `PROGRESS_CONTINUATION_PROMPT`: 系统提示词，定义分析维度
- `build_progress_continuation_prompt()`: 构建用户提示词

**输出结构**:
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
        "strength_areas": ["已掌握的知识点1"],
        "weak_areas": ["薄弱知识点1"],
        "analysis_summary": "分析总结..."
    },
    "learning_recommendations": {
        "next_action": "continue",
        "recommended_nodes": [3, 4, 5],
        "review_suggestions": ["建议复习..."],
        "pace_adjustment": "建议放慢节奏"
    },
    "continuation_script": {
        "welcome_back": "欢迎回来！...",
        "progress_review": "你已完成...",
        "next_step_intro": "接下来我们将学习...",
        "encouragement": "继续保持..."
    }
}
```

**使用场景**: 学生重新进入课程时，提供个性化的续接引导。

---

## 二、服务层实现 (Services)

### 1. 问答服务 (QA Service)

**文件路径**: `app/services/qa_service.py`

**核心类**:
- `QAPromptBuilder`: Prompt构建器
  - `build_knowledge_base_qa_prompt()`: 构建严格知识库问答Prompt
  - `build_context_aware_prompt()`: 构建上下文感知Prompt
  - `build_understanding_analysis_prompt()`: 构建理解程度分析Prompt
- `QAService`: 问答服务主类
  - `ask_question_with_rag()`: 基于RAG的问答
  - `ask_question_with_knowledge_base()`: 基于知识库的严格问答
  - `retrieve_rag_context()`: RAG检索上下文

**集成提示词**: `app/common/prompts/qa.py`

---

### 2. 文档服务 (Document Service)

**文件路径**: `app/services/document_service.py`

**核心类**:
- `DocumentParser`: 文档解析器
  - 支持 PDF、Word、PPT、文本等多种格式
  - 使用 Docling 或备用方法解析
- `KnowledgeExtractor`: 知识点提取器
  - `extract_knowledge_points()`: 提取知识点 Markdown
  - `parse_knowledge_markdown()`: 解析知识点列表
  - `generate_script_from_knowledge()`: 从知识点生成脚本
- `ScriptGenerator`: 智课脚本生成器
  - `generate_script()`: 生成智课脚本
- `DocumentService`: 文档服务主类
  - `extract_knowledge_only()`: 仅提取知识点
  - `generate_script_from_knowledge_only()`: 仅从知识点生成脚本
  - `extract_and_generate_script()`: 完整流程（提取+生成脚本）
  - `process_document()`: 完整文档处理流程

**集成提示词**:
- `app/common/prompts/document_analysis.py`
- `app/common/prompts/knowledge_to_script.py`

---

### 3. 进度服务 (Progress Service)

**文件路径**: `app/services/progress_service.py`

**核心类**:
- `UnderstandingAnalyzer`: 理解度分析器
  - `analyze_question()`: 分析学生提问，判断理解程度
- `NodeLocator`: 学习节点定位器
  - `locate_relevant_nodes()`: 定位与提问最相关的节点
- `PaceAdjuster`: 讲授节奏调节器
  - `calculate_pace_adjustment()`: 计算节奏调整建议
- `ProgressService`: 进度服务主类
  - `handle_student_question()`: 处理学生提问
  - `get_progress_visualization()`: 获取进度可视化数据

---

## 三、API 接口 (Endpoints)

### 1. 问答 API

**文件路径**: `app/api/v1/endpoints/chat.py`

**主要接口**:
- `POST /chat/ask`: 学生提问接口
- `POST /chat/stream`: 流式问答接口
- `GET /chat/history/{chat_id}`: 获取对话历史

**使用提示词**: `app/common/prompts/qa.py`

---

### 2. 文档 API

**文件路径**: `app/api/v1/endpoints/document.py`

**主要接口**:
- `POST /document/upload`: 上传文档
- `POST /document/parse`: 解析文档
- `POST /document/extract-knowledge`: 提取知识点
- `POST /document/generate-script`: 生成智课脚本
- `GET /document/{doc_id}/status`: 获取处理状态

**使用提示词**:
- `app/common/prompts/document_analysis.py`
- `app/common/prompts/knowledge_to_script.py`

---

### 3. 进度续接 API

**文件路径**: `app/api/v1/endpoints/progress.py`

**主要接口**:
- `POST /progress/analyze`: 分析学生理解度
- `POST /progress/continuation`: **进度续接分析** ⭐
  - 获取历史答疑记录
  - 调用 LLM 分析学习进度
  - 生成结构化续接脚本
- `POST /progress/sync`: 同步学习进度
- `GET /progress/resume/{course_id}`: 获取断点续接信息
- `GET /progress/visualization/{course_id}`: 获取进度可视化数据

**使用提示词**: `app/common/prompts/progress.py`

---

## 四、完整工作流程

### 文档处理流程

```
1. 文档上传
   ↓
2. 文档解析 (DocumentParser)
   ↓
3. 知识点提取 (KnowledgeExtractor)
   - 使用 document_analysis.py 提示词
   ↓
4. 生成智课脚本 (KnowledgeExtractor.generate_script_from_knowledge)
   - 使用 knowledge_to_script.py 提示词
   ↓
5. RAG 预处理 (RAGProcessor)
   ↓
6. 保存课程数据
```

### 问答流程

```
1. 学生提问
   ↓
2. RAG 检索相关上下文
   ↓
3. 构建 QA Prompt
   - 使用 qa.py 提示词
   ↓
4. LLM 生成回答（带引用标注）
   ↓
5. 返回答案给学生
```

### 进度续接流程

```
1. 学生重新进入课程
   ↓
2. 调用 /progress/continuation
   ↓
3. 获取历史答疑记录
   ↓
4. 构建 Progress Prompt
   - 使用 progress.py 提示词
   ↓
5. LLM 生成续接分析
   ↓
6. 返回进度摘要、理解度分析、学习建议、续接脚本
```

---

## 五、文件清单

### 提示词文件
| 文件 | 路径 | 功能 |
|------|------|------|
| qa.py | `app/common/prompts/qa.py` | 知识库问答 |
| document_analysis.py | `app/common/prompts/document_analysis.py` | 知识点提取 |
| knowledge_to_script.py | `app/common/prompts/knowledge_to_script.py` | 知识点转脚本 |
| progress.py | `app/common/prompts/progress.py` | 进度续接分析 |

### 服务文件
| 文件 | 路径 | 功能 |
|------|------|------|
| qa_service.py | `app/services/qa_service.py` | 问答服务 |
| document_service.py | `app/services/document_service.py` | 文档处理服务 |
| progress_service.py | `app/services/progress_service.py` | 进度续接服务 |

### API 路由文件
| 文件 | 路径 | 功能 |
|------|------|------|
| chat.py | `app/api/v1/endpoints/chat.py` | 问答 API |
| document.py | `app/api/v1/endpoints/document.py` | 文档 API |
| progress.py | `app/api/v1/endpoints/progress.py` | 进度续接 API |

---

## 六、使用示例

### 提取知识点并生成脚本

```python
from app.services.document_service import document_service

# 完整流程：提取知识点 + 生成脚本
result = await document_service.extract_and_generate_script(
    markdown_content="# 文档内容...",
    filename="课程文档.md"
)

knowledge_markdown = result["knowledge_markdown"]  # 结构化知识点
knowledge_points = result["knowledge_points"]      # 知识点列表
script = result["script"]                          # 智课脚本 JSON
```

### 知识库问答

```python
from app.services.qa_service import QAService

qa_service = QAService()

# 基于知识库问答
answer = await qa_service.ask_question_with_knowledge_base(
    question="什么是光合作用？",
    context_content="知识库上下文...",
    knowledge_points=[
        {"id": "知识点1", "content": "光合作用是..."},
        {"id": "知识点2", "content": "叶绿体是..."}
    ]
)
# 返回带引用标注的答案
```

### 进度续接

```python
# API 调用
POST /api/v1/progress/continuation
{
    "courseId": 123,
    "chatId": 456
}

# 返回结果
{
    "progress_summary": { ... },
    "understanding_analysis": { ... },
    "learning_recommendations": { ... },
    "continuation_script": {
        "welcome_back": "欢迎回来！...",
        "progress_review": "你已完成课程的前半部分...",
        "next_step_intro": "接下来我们将学习...",
        "encouragement": "继续保持，有任何问题随时提问！"
    }
}
```

---

*文档生成时间: 2026-04-11*
