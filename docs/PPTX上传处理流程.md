# PPTX 上传处理流程技术文档

## 总览流程图

```
用户上传 PPTX
     │
     ▼
┌─────────────────────────────────────────────────────────┐
│  POST /api/v1/document/upload                           │
│  POST /api/v1/chat/file/upload  (别名路由)               │
│                                                         │
│  ① 文件存储 → ② Docling/PPTX解析 → ③ 结构化解析        │
│       → ④ LLM智课脚本生成 → ⑤ RAG预处理 → ⑥ 思维导图   │
│       → ⑦ 数据库持久化 → ⑧ 返回前端                     │
└─────────────────────────────────────────────────────────┘
```

---

## 步骤详解

### ① 文件存储与记录创建

**入口接口**: `POST /api/v1/document/upload`

**代码位置**: `backend/app/api/v1/endpoints/document.py:56-99`

| 操作 | 写入表 | 说明 |
|------|--------|------|
| 文件保存到临时目录 | — | `UPLOAD_DIR / {uuid}{ext}` |
| 创建课程记录 | `courses` | 状态为 `DRAFT` |
| 创建文档解析记录 | `docling_documents` | 状态为 `PENDING → PROCESSING` |

**技术要点**:
- 使用 UUID 重命名文件，防止路径冲突
- 文件大小限制 50MB
- 需要用户认证（`Depends(get_current_user)`）

---

### ② 文档解析（PPTX → Markdown）

**服务层**: `backend/app/services/document_service.py:96-142` → `DocumentParser.parse_file()`

**解析策略**（双引擎降级）:

```
优先: Docling 解析 (_parse_with_docling)
  │ 失败
  ▼
降级: python-pptx 解析 (_fallback_parse → _parse_pptx)
```

#### Docling 解析

**代码位置**: `backend/app/services/document_service.py:144-181`

- 使用 `DocumentConverter` 支持 PDF/DOCX/PPTX/HTML/图片
- PDF 额外启用 OCR（`do_ocr=True, ocr_lang="zh_cn+en"`）
- 导出为 Markdown 后进行后处理（清理乱码、规范标题层级、去连续空行）

#### python-pptx 备用解析

**代码位置**: `backend/app/services/document_service.py:296-329`

- 逐页提取标题、文本内容
- 短文本自动识别为子标题（`###`），长文本为正文
- 问号结尾的短文本标记为互动提问（`❓`）

#### Docling JSON 附加数据

- 检查同目录下是否存在 `{stem}_docling.json`，若有则加载 `ai_formatted` 结构化数据
- `ai_formatted` 的存在决定了后续脚本生成走哪条路径

**技术要点**:
- Docling 是 IBM 开源的文档结构感知解析器，能保留文档层级结构
- 降级策略确保即使 Docling 不可用也能基本解析
- `ai_formatted` 数据的存在决定了脚本生成走哪条路径

---

### ③ 结构化解析（Markdown → 结构化数据）

**服务层**: `backend/app/services/document_service.py:343-456` → `StructureParser.parse_markdown_to_structure()`

**处理逻辑**:
- 按 `#` 标题层级拆分为 `groups`（chapter/section/subsection/paragraph）
- 非标题文本（>8字符）归入 `texts`，关联到当前 group
- 清理乱码字符（控制字符 + 特殊方块符号）

**输出结构**:

```python
StructureResult:
    groups: List[Dict]   # 标题层级节点
    texts:  List[Dict]   # 正文段落
    tables: List[Dict]   # 表格（此处为空，由Docling JSON补充）
    pictures: List[Dict] # 图片（此处为空）
```

**技术要点**:
- 通过 `level` 字段记录标题深度（1-6），保持原文档层级
- `self_ref` 引用格式（`#/groups/0`、`#/texts/0`）兼容 Docling JSON 规范

---

### ④ LLM 智课脚本生成

**服务层**: `ScriptGenerator`，两条路径：

| 路径 | 条件 | 方法 |
|------|------|------|
| **ai_formatted 路径** | 存在 Docling JSON | `generate_script_from_ai_formatted()` |
| **LLM 路径** | 无 Docling JSON | `generate_script()` |

#### 路径A: ai_formatted 路径

**代码位置**: `backend/app/services/document_service.py:463-583`

- 直接使用 Docling JSON 中的 `content`，**不调用 LLM**
- 合并相邻短章节（标题有内容无配对时合并）
- 自动判断节点类型：`lecture` / `question` / `summary`

#### 路径B: LLM 路径

**代码位置**: `backend/app/services/document_service.py:685-815`

- 调用 LLM（豆包/通义千问/文心/OpenAI）生成结构化脚本
- **Prompt 核心**: 要求每个节点 content 300-800字，包含概念定义+原理解释+实例+应用场景
- 输出 JSON 格式，包含 `nodes` 数组
- LLM 失败时降级为模板填充（`_create_default_script`）

#### LLM 客户端架构

**代码位置**: `backend/app/common/llm_client.py`

```
LLMClient (单例)
  ├── DoubaoClient   → 豆包/火山引擎 (OpenAI兼容格式)
  ├── QwenClient     → 通义千问 (DashScope格式)
  ├── WenxinClient   → 文心一言 (百度格式，需获取access_token)
  └── OpenAIClient   → OpenAI兼容格式
```

**技术要点**:
- 单例模式: `LLMClient` 使用 `__new__` 实现单例，全局共享一个客户端实例
- 降级策略: LLM 调用失败时自动回退到模板生成，保证系统可用性
- 内容截断: 超长文档截断到 20000 字符（LLM路径）/ 8000 字符（SmartCourse路径）
- JSON 解析容错: 用正则 `\{[\s\S]*\}` 提取 JSON，防止 LLM 输出多余文本

---

### ⑤ RAG 预处理

**服务层**: `backend/app/services/document_service.py:1167-1254` → `RAGProcessor.process()`

**RAG 流水线** (`backend/app/common/RAG/rag_utils.py`):

```
Markdown原文
    │
    ▼ Step1: 公式占位替换 (FormulaPlaceholderReplacer)
    │  LaTeX公式 → FORMULA_001 等语义占位符
    ▼ Step2: 表格展平 (TableFlattener)
    │  Markdown表格 → 自然语言描述
    ▼ Step3: IK分词 (IKTokenizer)
    │  教育场景定制分词，识别领域术语
    ▼ Step4: 知识树构建 (DoclingTreeBuilder)
    │  按标题层级构建树状结构
    ▼ Step5: 检索索引 (TreeRAGRetriever)
    │  建立关键词+路径混合检索索引
    ▼
  处理后文本 + 知识树
```

**技术要点**:
- 公式占位替换: 将 LaTeX 公式替换为语义化占位符，避免公式干扰分词和检索
- 表格展平: 将结构化表格转为自然语言，便于语义检索
- IK 分词: 教育领域定制分词器，内置专业词典，识别领域术语
- 树状 RAG: 基于文档层级结构的知识树检索，支持 keyword/path/hybrid 三种策略
- 内存索引: 处理结果缓存在 `_processed_docs` 字典中（按 doc_id 索引）

---

### ⑥ 思维导图生成

**服务层**: `MindMapGenerator`，两条路径：

| 路径 | 条件 | 方法 |
|------|------|------|
| ai_formatted 路径 | 存在 Docling JSON | `generate_from_ai_formatted()` |
| 脚本路径 | 无 Docling JSON | `generate()` |

#### ai_formatted 路径

**代码位置**: `backend/app/services/document_service.py:1014-1066`

- 保留 Docling 原始层级结构
- 使用栈算法构建多级树（`_build_tree`）
- 支持章节编号识别（`1.1`、`1.2.3` 等）
- 自动排序子节点、清理空 children

**技术要点**:
- 栈式树构建: 使用栈维护当前路径，遇到更深层级时入栈，同层/上层时出栈
- 章节编号解析: 正则 `^\d+\.\d+` 识别编号，自动匹配父子关系

---

### ⑦ 数据库持久化

**代码位置**: `backend/app/api/v1/endpoints/document.py:161-254`

| 步骤 | 写入表 | 内容 |
|------|--------|------|
| 4a | `docling_groups` | 结构化分组 |
| 4b | `docling_texts` | 文本段落 |
| 4c | `docling_documents` | 更新状态为 COMPLETED |
| 5 | `course_scripts` | 智课脚本（含 script_content JSON） |
| 6 | `script_nodes` | 脚本节点（逐条插入） |
| 7 | `chat_histories` | 聊天记录归档 |

**技术要点**:
- 状态机: DoclingDocument 状态流转 `PENDING → PROCESSING → COMPLETED/FAILED`
- 内存缓存: `document_cache` 字典缓存处理结果，支持后续 `/analyze` 接口查询
- 节点类型枚举: `ScriptNodeType(lecture/question/breakpoint/summary/video/interactive)`

---

### ⑧ 返回前端

**代码位置**: `backend/app/api/v1/endpoints/document.py:279-300`

**返回数据结构**:

```json
{
  "code": 200,
  "data": {
    "fullContent": "美化后的Markdown",
    "rawContent": "原始解析Markdown",
    "title": "课程标题",
    "audioUrl": null,
    "mindMapJson": { "text": "根节点", "children": [...] },
    "chatId": 123,
    "courseId": 456,
    "ragInfo": {
      "formulaCount": 5,
      "tableCount": 3,
      "domainTermCount": 12,
      "treeNodeCount": 28,
      "knowledgePointCount": 8
    }
  }
}
```

---

## 相关接口汇总

| 接口 | 方法 | 功能 |
|------|------|------|
| `/api/v1/document/upload` | POST | 上传文档并执行完整处理流程 |
| `/api/v1/chat/file/upload` | POST | 同上（聊天模块别名路由） |
| `/api/v1/document/analyze` | POST | 对已上传文档进行AI分析 |
| `/api/v1/document/courses` | GET | 获取课程列表 |
| `/api/v1/document/{document_id}` | GET | 获取文档信息 |
| `/api/v1/document/course/{course_id}` | GET | 获取课程完整详情 |
| `/api/v1/document/course/{course_id}/save` | POST | 保存教师修改的节点内容 |
| `/api/v1/document/course/{course_id}/publish` | POST | 发布课程 |
| `/api/v1/document/course/{course_id}/unpublish` | POST | 取消发布课程 |
| `/api/v1/document/course/{course_id}` | DELETE | 删除课程及关联数据 |
| `/api/v1/document/course/{course_id}/enroll` | POST | 学生选课 |
| `/api/v1/document/course/{course_id}/students` | GET | 获取课程学生列表 |
| `/api/v1/document/course/{course_id}/stats` | GET | 获取课程统计数据 |
| `/api/v1/document/tts/synthesize` | POST | TTS语音合成 |
| `/api/v1/video/stream/{filename}` | GET | 视频流式播放 |

---

## 核心技术要点总结

### 1. 双引擎解析降级

Docling（结构感知，保留层级）→ python-pptx（基础提取，逐页文本），保证在任何环境下都能完成解析。

### 2. 双路径脚本生成

- **ai_formatted 路径**: 直接映射 Docling JSON 内容，速度快，不消耗 LLM Token
- **LLM 路径**: 调用大模型生成口语化教学脚本，内容更丰富

按数据源自动选择，无需人工干预。

### 3. RAG 五步流水线

公式占位 → 表格展平 → IK分词 → 知识树 → 检索索引，面向教育场景深度优化，确保公式、表格等专业内容能被正确检索。

### 4. LLM 多提供商适配

豆包/千问/文心/OpenAI 统一接口，单例模式管理，通过 `.env` 中 `LLM_PROVIDER` 切换。

### 5. TTS 多提供商适配

阿里云/腾讯云/火山引擎/Mock 统一 `synthesize()` 接口，通过 `.env` 中 `TTS_PROVIDER` 切换。

### 6. 全链路降级容错

每个环节都有 fallback 策略：
- 解析失败 → 备用解析器
- LLM 失败 → 模板生成
- TTS 失败 → 返回错误信息（无 Mock 降级）

### 7. 状态机管理

文档解析状态 `PENDING → PROCESSING → COMPLETED/FAILED` 全程可追踪，支持异常恢复。

### 8. 安全机制

- JWT 身份认证（`get_current_user`）
- 签名校验中间件（`SignatureMiddleware`）
- 角色权限控制（教师/学生/管理员）
- 文件名路径遍历防护（`os.path.basename`）

---

## 变更日志

### 2026-05-22: 教师历史页面优化 + 学生端问答越界修复

#### 一、教师历史页面优化 (`/teacher/history`)

**新增功能**：

1. **学习进度分布饼状图** — 使用 `chart.js` + `vue-chartjs`，在学生状态面板中展示进度分布的 Pie 图（未开始/初学/进阶/熟练/完成），与条形图并列展示
2. **各知识点完成率环形图** — 使用 Doughnut 图展示每个课程节点的完成率，下方附带节点进度条列表（含节点类型图标、重点标记、完成率百分比）
3. **后端 `/stats` API 增强** — 新增 `node_progress` 字段，返回每个课程节点的完成人数、完成率、平均理解度

**Bug 修复**：

1. **`progressLabels` 遍历错误** — 原代码返回 `[{label, count}]` 数组但模板用 `v-for="(count, label)"` 对象解构遍历，导致 `count` 为对象、`label` 为索引。修复为 `v-for="item in progressLabels"` + `item.label`/`item.count`
2. **CSS 类名冲突** — 页面级统计和面板内统计共用 `.stats-overview`/`.stat-card` 等类名导致样式覆盖。修复为独立命名：`.page-stats-overview`/`.panel-stats-overview`
3. **`totalStudents: -1` 异常值** — API 失败时设置 `totalStudents: -1`，修复为 `0`
4. **`unknown` 理解度等级无样式** — 新增 `.level-unknown` 样式类
5. **条形图 CSS 类名使用中文** — `dist-未开始` 改为 `dist-not_started`，避免编码问题

**新增依赖**：

- `chart.js` (^4.x)
- `vue-chartjs` (^5.x)

**新增 API 字段** (`GET /document/course/{course_id}/stats`)：

```json
{
  "node_progress": [
    {
      "node_id": 1,
      "node_index": 0,
      "title": "频域响应法概述",
      "node_type": "lecture",
      "is_key_point": true,
      "completed_count": 5,
      "total_students": 10,
      "completion_rate": 50.0,
      "avg_understanding": 72.5,
      "accessed_count": 8
    }
  ]
}
```

#### 二、学生端知识点问答越界修复 (`StudentDashboard.vue`)

**问题**：用户在知识点 A 问答进行中快速跳转到知识点 B，A 的 API 响应延迟到达后被推入 B 的聊天窗口。

**修复**：

1. **per-node 聊天历史隔离** — 新增 `nodeChatHistory` 字典，跳转时保存/恢复每个节点的聊天历史
2. **竞态条件防护** — `streamCurrentNode`/`generateQAForNode`/`sendMessage` 中添加节点索引快照，API 响应到达时检查当前节点是否已切换
3. **`currentNodeId` 传参修复** — `generateQAForNode` 中 `currentNodeId: null` 改为 `currentNodeId: node.id`
4. **后端 `current_node` 传参修复** — `/chat/ask` 接口将 `currentNodeId` 对应的节点信息传入 `qa_service.ask_question_with_rag()` 的 `current_node` 参数

**测试**：14 个单元测试全部通过 (`tests/test_teacher_history.py`)
