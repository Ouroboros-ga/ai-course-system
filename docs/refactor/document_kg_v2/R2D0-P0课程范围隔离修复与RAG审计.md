# R2D0-P0 课程范围隔离修复与 RAG 现状审计

更新时间：2026-07-13
分支：`feature/document-kg-v2`
状态标注口径：已实现 / 部分实现 / 未实现 / 仅文档规划 / 占位代码 / 待验证

---

## 1. 本轮执行范围

本轮只完成一个 P0 修复：**为内存树式 RAG 增加课程范围隔离，消除问答链路的跨课程上下文污染**，并补齐 RAG 检索路径的测试基线。

本轮**未做**（明确划界）：

- 未引入 FAISS / Chroma / Embedding / BM25 / Cross-Encoder / RRF；
- 未新建 `platform/retrieval/` 抽象层（避免占位模块，符合 `AGENTS.md`）；
- 未改 API 路径、请求/响应结构、数据库表结构；
- 未改启动方式、数字人/PPT/TTS 适配层；
- 未 commit / push；
- 未触碰 `document_upload.py`（未在 `main.py` 注册、未接入主流程，按“不修改无关代码”原则保留，见 §7）。

---

## 2. 当前实现架构（真实调用链）

证据口径：注册路由 + 实际函数调用 + 数据库模型 + 可运行测试。设计文档不作为完成依据。

### 2.1 问答主链（学生 `/api/v1/chat/ask`）

```
前端 useStudentLearning.js
  -> POST /api/v1/chat/ask  (chat.py:ask_question, courseId/question/currentNodeId/strictMode)
     -> _get_course_context(session, courseId)            [正确：按 courseId 从 DB 取 DoclingDocument/DoclingText/CourseScript]
     -> qa_service.ask_question_with_rag(
          course_context, use_rag=bool(courseId),
          course_id=courseId  ← 本轮新增
        )
        -> QAService.retrieve_rag_context(question, course_id=courseId)  ← 本轮新增 course_id
           -> rag_pipeline.retrieve(question, course_id=courseId)        ← 本轮新增 course_id
              -> TreeRAGRetriever.retrieve (IK 分词倒排 + 结构路径, 内存)
        -> full_context = course_context + rag_context
        -> LLM (llm_client / LLMAdapter) 生成回答
     -> 落库 ChatMessage；可选理解度分析 progress_service
     -> 返回 {chatId, answer, ragSources, understandingAnalysis}
```

### 2.2 文档上传主链（教师 `/api/v1/document/upload`）

```
POST /api/v1/document/upload (document.py:upload_document)
  -> 写源文件 -> 创建 Course -> 可选 PDF 转换 -> 创建 DoclingDocument(PENDING)
  -> document_service.process_document(file_path, filename, enable_rag=True, enable_script=True,
                                        course_id=course.id)   ← 本轮新增 course_id
     -> DocumentParser.parse_file (Docling, 失败格式级 fallback)
     -> StructureParser.parse_markdown_to_structure (标题正则)
     -> ScriptGenerator.generate_script (LLM)
     -> RAGProcessor.process(markdown, name, file_hash, course_id=course.id)  ← 本轮新增 course_id
        -> rag_pipeline.process_document(markdown, doc_name, doc_id=str(course_id))  ← 以 course_id 为范围键
           -> 公式占位 -> 表格展平 -> IK 分词 -> 知识树 -> build_index
           -> 注册 _course_retrievers[str(course_id)]            ← 本轮新增
     -> 落库 DoclingGroup/DoclingText/raw_json/CourseScript/ScriptNode
  -> course.status = PUBLISHED
  -> 后台 TTS (asyncio.create_task)
```

### 2.3 架构分层（当前真实状态）

| 层 | 状态 | 关键文件 |
|---|---|---|
| API 路由 | 已实现 | `app/api/v1/endpoints/{chat,document,ppt_generation,...}.py`、`app/main.py` |
| Service | 已实现 | `app/services/{qa,document,progress,prerequisite,knowledge,...}_service.py` |
| RAG 检索 | 部分实现（内存树式关键词，本轮加课程隔离） | `app/common/RAG/{rag_utils,tree_rag,ik_tokenizer,...}.py` |
| 外部服务适配层 | 已实现（R1 重构） | `app/platform/adapters/{llm,tts,ppt,digital_human,duix_avatar,...}.py` |
| Agent / 多智能体 | 占位代码 | `app/engine/{agents,graphrag,cognitive}/__init__.py` 仅空 `__init__.py` |
| 向量库 / Embedding / BM25 / 重排 | 未实现（仅 R2D0 设计文档） | 无对应代码 |
| 知识图谱 | 占位代码 | `app/api/v1/endpoints/graphrag.py` 仅注释；`models/knowledge_graph.py` 未接入 |

---

## 3. RAG 与知识库现状表

| 模块 | 当前实现 | 关键文件 | 是否可用 | 主要问题 |
|---|---|---|---|---|
| 文档解析 | Docling + 格式级 fallback | `document_service.py:DocumentParser` | 可用 | Markdown 正则重建结构，丢失 bbox/类型/provenance |
| 文档切块 | 标题层级知识树（非固定 chunk） | `tree_rag.py:DoclingTreeBuilder` | 可用 | 树节点 = 章节，非语义 chunk |
| 元数据保存 | DoclingGroup/DoclingText/raw_json 落库；RAG 树仅内存 | `document.py`、`rag_utils.py` | 部分 | RAG 树进程重启即丢失；chunk 无持久 id |
| Embedding | 未实现 | 无 | 不可用 | 无 embedding 模型（`TreeNode.embedding` 字段恒 None） |
| 向量索引 | 未实现 | 无 | 不可用 | — |
| FAISS | 未实现 | 无 | 不可用 | 仅 `R2D0开源组件调研与选型.md` 提及 |
| Chroma | 未实现 | 无 | 不可用 | 仅设计文档提及 |
| BM25 | 未实现 | 无 | 不可用 | 当前为 IK 分词倒排（非 BM25 打分） |
| 混合召回 | 部分（keyword + path 简单加权） | `tree_rag.py:_merge_results` | 可用 | 非 RRF/加权融合，无 dense 召回 |
| 重排模型 | 未实现 | 无 | 不可用 | — |
| 课程过滤 | **本轮修复为可用** | `rag_utils.py:retrieve(course_id=)` | 可用 | 修复前无 course filter，跨课程污染 |
| 权限过滤 | 未实现 | 无 | 不可用 | 选课/角色未纳入检索过滤 |
| 对话上下文 | 已实现（history_messages 取最近 5/10 条） | `qa_service.py` | 可用 | — |
| 学习进度上下文 | 已实现（current_node 注入 prompt） | `chat.py`、`qa_service.py` | 可用 | 进度未作为检索过滤，仅作为 prompt 提示 |
| 引用与溯源 | 部分（rag_sources 返回 path/score/match_type） | `qa_service.py` | 部分 | 无 chunk_id/source_id/course_id/page 等结构化证据 |
| 无答案拒答 | 部分（strict_mode prompt 要求说明，无 should_abstain） | `qa_service.py` | 部分 | 无结构化置信度/拒答字段 |
| 索引增量更新 | 部分（重传同一 course_id 会覆盖该课程检索器） | `rag_utils.py` | 部分 | 仅进程内，非持久 |
| 索引删除 | **本轮新增 `clear_course_index`** | `rag_utils.py` | 可用 | 仅进程内；未接入课程删除主链 |
| 索引版本 | 未实现 | 无 | 不可用 | 无版本/快照 |
| 检索日志 | 未实现 | 无 | 不可用 | 仅 logger.info，无 trace_id/阶段耗时 |
| 检索评测 | 未实现 | 无 | 不可用 | 无离线评测基线 |

### FAISS 真实定位结论

- **未安装**：`backend/pyproject.toml` 依赖无 `faiss`；`grep faiss` 仅命中设计文档。
- **无真实调用**：全仓库无 `import faiss`。
- **结论**：FAISS 在当前系统中**不存在**，仅为 R2D0 规划内容。不得称为“已有向量检索”。

---

## 4. 智能体-知识依赖矩阵

| 智能体/功能 | 课程知识库 | 课程结构 | 学生数据 | 对话记忆 | 教学规范 | 当前调用方式 |
|---|---|---|---|---|---|---|
| 课程问答 `/chat/ask` | 树式 RAG（本轮按课程隔离）+ DB course_context | DoclingText/CourseScript | current_node prompt 注入 | history_messages | strict_mode prompt | `qa_service.ask_question_with_rag` |
| 错题重讲/前置跳转 `/prerequisite/*` | 不直接用 RAG | ScriptNode | LearningJumpHistory | chat_messages | LLM 判断 | `prerequisite_service`（LLM，非 RAG） |
| 出题测验 `/chat/quiz` | 不用 RAG（用 node_content + course_context） | ScriptNode | 否 | 否 | QUIZ prompt | `qa_service.generate_quiz`（LLM JSON） |
| 学习路径 | 否 | 否 | LearningProgress | 否 | 否 | `progress_service`（LLM 续学建议） |
| 讲稿生成 | 否 | Docling 结构 | 否 | 否 | ScriptGenerator prompt | `script_generator`（LLM） |
| 教学评价 | 否 | 否 | 理解度分析 | 否 | LLM JSON | `progress_service.handle_student_question` |
| 教师辅助 | 否 | DoclingText | 否 | 否 | 否 | `document.py` 上传/脚本/发布 |
| 多学科知识库问答 | KnowledgePoint（SQL contains） | 否 | 否 | history | strict prompt | `qa_service.ask_question_with_multi_kb`（`KnowledgeSearchService`，非 RAG） |

判断要点：

1. 智能体**未直接操作**向量库（不存在向量库）；问答直接访问全局内存 `rag_pipeline`（本轮改为按 course_id 隔离）。
2. **不存在统一 Retriever/RAG 接口**；`rag_pipeline` 是唯一检索入口但无抽象层（见 §6 下一步）。
3. 同一套课程文档**被重复建立多份索引**：上传主链建 RAG 树（内存），`KnowledgeImportService` 又用 `rag_pipeline.process_document(doc_id=str(kb_id))` 为知识库再建一棵（按 kb_id 隔离，本轮后两不相扰）。
4. 学生进度**未作为向量检索**（正确），仅作为 prompt 提示。
5. 正式课程资料（DoclingText）与 AI 草稿（脚本/知识点）**未严格隔离**：RAG 树来自解析后 markdown，含 LLM 生成的脚本前文本混合；但 RAG 树不写回正式知识库表（`KnowledgeImportService` 是显式独立入口，非上传主链）。
6. 不同智能体**无明确知识范围抽象**，各自硬编码检索/不检索。
7. 元数据：有 course/chapter(title)/page(ScriptNode.page_start/page_end)，但 RAG 树节点**无 page/chapter_id/kp_id** 持久元数据。
8. 向量库可替换性：当前无向量库；`rag_pipeline.retrieve` 是唯一 seam，未来可在此抽 Retriever 接口。

---

## 5. 差距分析（对照目标架构）

目标：`Agent -> Unified RAG Gateway -> Scope Filter -> Sparse -> Dense -> Fusion -> Reranker -> Context Builder -> Evidence Package`

| 目标能力 | 当前状态 | 差距等级 |
|---|---|---|
| Unified RAG Gateway | 无抽象，`rag_pipeline` 直连 | P1 |
| Scope Filter（课程/权限） | **课程过滤本轮已修**；权限过滤未实现 | P0 课程已修 / P1 权限 |
| Sparse Retriever | IK 倒排（非 BM25） | P2 |
| Dense Retriever | 未实现 | P1 |
| Fusion | keyword+path 简单加权（非 RRF） | P2 |
| Reranker | 未实现 | P2 |
| Context Builder | `get_context_for_result` 子树展开 | P2（缺结构化） |
| Evidence Package（chunk_id/source_id/course_id/chapter_id/page/score/...） | 仅 path/score/match_type | P1 |

### 分级差距

- **P0**（影响问答正确性/稳定性）：✅ 本轮已修复“跨课程上下文污染”。剩余 P0：解析质量无发布门禁、M4B/M7 fake 不证真实解析（属 R2D0 DocumentIR 范畴，不在本轮）。
- **P1**（阻碍统一架构演进）：统一 Retriever 接口、权限过滤、Evidence Package 结构化、Dense Retrieval、持久化索引。
- **P2**（性能/可观测/科研）：BM25、RRF、Cross-Encoder、检索 trace/阶段耗时、检索评测基线。
- **P3**（长期扩展）：索引版本、GraphRAG、多智能体（均占位/规划，禁止本阶段实现）。

---

## 6. 本轮修改内容

### 修复的缺陷（P0）

修复前：`rag_pipeline` 是全局单例，`TreeRAGRetriever.build_index` 每次覆盖唯一全局树；`QAService.retrieve_rag_context -> rag_pipeline.retrieve(question)` **不传 course_id**；`RAGProcessor.process` 传入的 `doc_id = str(hash(file_path))`（文件路径哈希，与课程无关）。后果：上传课程 B 后，学生对课程 A 提问会命中“最后一次构建”的 B 的树，**跨课程内容污染**，且 `use_rag` 恰在传 courseId 时为 True——即污染发生在核心学生问答。

修复后：`RAGPipeline` 维护按 `course_id` 隔离的检索器注册表 `_course_retrievers`；`retrieve(course_id=...)` 只查该课程树，**缺失时返回空（不回退到全局最新树）**，杜绝污染；`course_id=None` 保留旧行为。问答回退路径安全：RAG 空时仅用 DB `course_context`（权威且按课程隔离）。

### 修改文件

| 文件 | 修改目的 |
|---|---|
| `backend/app/common/RAG/rag_utils.py` | `RAGPipeline` 新增 `_course_retrievers`；`process_document` 注册课程检索器；`retrieve(course_id=)` 课程隔离检索，缺失返回空不回退；新增 `get_context_for_result`/`has_course_index`/`clear_course_index`；`generate_answer` 透传 course_id |
| `backend/app/services/document_service.py` | `RAGProcessor.process` 新增 `course_id`，以 `str(course_id)` 为 RAG 范围键；`DocumentService.process_document` 新增 `course_id` 并透传 |
| `backend/app/services/qa_service.py` | `retrieve_rag_context`/`ask_question_with_rag` 新增 `course_id` 并透传；改用公共 `get_context_for_result` 取代 `_retriever` 私有访问 |
| `backend/app/api/v1/endpoints/chat.py` | `/chat/ask` 传 `course_id=courseId` |
| `backend/app/api/v1/endpoints/document.py` | `/document/upload` 传 `course_id=course.id` |
| `backend/app/api/v1/endpoints/ppt_generation.py` | `_parse_generated_pptx` 传 `course_id=course.id` |
| `backend/tests/test_m4b_main_flows.py` | `fake_process_document`/`failing_process_document` 增加 `course_id=None`（与新签名兼容，不弱化断言） |
| `backend/tests/test_m7_demo_flow.py` | `fake_process_document` 增加 `course_id=None` |
| `backend/tests/test_rag_course_scope.py` | **新增**：15 个用例覆盖课程隔离/缺失不回退/旧行为兼容/QA 透传/端到端/索引管理/边界 |

### 兼容性保证

- 所有新增参数均有默认值（`course_id=None`）；旧调用方零改动即可工作。
- `retrieve(query)`（无 course_id）行为与修复前一致（查最新全局树）。
- API 路径、请求/响应字段、DB 表结构、启动方式均未变。
- 旧测试夹具仅需补 `course_id=None` 形参（因真实调用点新增了该 kwarg）。

---

## 7. 尚未实现 / 待验证

- **未实现**：统一 Retriever 接口、Dense Retrieval、Embedding、BM25、RRF、Cross-Encoder、Evidence Package 结构化、权限过滤、检索 trace/评测、索引持久化与版本、GraphRAG、多智能体。
- **待验证**：真实 LLM 答问质量（本阶段禁调真实付费 LLM，只证链路）；真实多课程并发上传下内存检索器增长（demo 规模内可接受，未压测）。
- **未接入主流程（本轮有意不改）**：
  - `backend/app/api/v1/endpoints/document_upload.py`：未在 `main.py` 注册的重复上传端点，同样存在跨课程隐患，若启用需补 `course_id=course.id`。
  - `clear_course_index` 已提供但未接入“课程删除”主链（删除课程时仍残留内存检索器，进程重启后消失）。
- **已知限制**：RAG 树为进程内内存，**进程重启后丢失**；重启后 `retrieve(course_id=X)` 返回空，问答回退到 DB `course_context`（安全降级，非回归）。

---

## 8. 测试结果

命令（仓库根）：

```bash
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_rag_course_scope.py -v
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_m4b_main_flows.py backend/tests/test_m7_demo_flow.py backend/tests/test_m4b_fakes.py backend/tests/test_m4a_isolation.py backend/tests/test_m4a_route_contract.py -q
```

结果：

- **新增 `test_rag_course_scope.py`：15 passed**（课程隔离、缺失不回退、旧行为兼容、QA 透传、端到端 FakeLLM、索引管理、空查询/top_k 边界）。
- **改动范围回归：41 passed**（含 m4b 上传成功/失败、m7 演示流程）。
- **全量后端：189 passed, 28 failed, 11 errors**。28 failed + 11 errors 与 `docs/phase1/关键业务回归矩阵.md` 记录的历史基线（`120 passed, 28 failed, 11 errors`）**完全一致**，均为既有失败（`test_prerequisite_jump` 鉴权 401、`test_video_generation` 旧路由冲突、`test_new_features` 夹具缺失、`test_f5_mapping_fix` 等，见 `docs/phase1/代码风险清单.md`），**本轮未引入新回归**。
- 后端可导入检查：`PYTHONPATH=backend python -c "import app.main"` 通过。

测试不依赖真实 LLM/网络：`retrieve`/`retrieve_rag_context` 为纯检索路径；`ask_question_with_rag` 集成测试使用 `conftest` 自动安装的 `FakeLLMClient`。

---

## 9. 下一阶段建议（按依赖排序）

1. **（P1）抽象统一 Retriever 接口**：在 `platform/retrieval/` 定义 `Retriever` Protocol 与 `RetrievedChunk` schema，将现有 `rag_pipeline` 树式检索包装为首个 provider，`qa_service` 改为依赖 `Retriever` 抽象而非全局单例。依赖：本轮课程隔离已提供干净 seam。风险：需保持旧 `rag_pipeline` 入口兼容。
2. **（P1）Evidence Package 结构化**：`RetrievedChunk` 补 `chunk_id/course_id/chapter_id/page_number/retrieval_score/retrieval_source`；`rag_sources` 升级为结构化证据，前端契约增量兼容。依赖：项 1。风险：不改现有响应字段语义，仅增量。
3. **（P1）持久化索引 + 进程重启可恢复**：将 RAG 树/chunk 持久化（DB 或文件），启动时按 course_id 重建，解决“重启后 RAG 空”降级。依赖：项 1。风险：需与 R2D0 DocumentIR 表设计对齐，避免双轨。
4. **（P2）检索可观测性与评测基线**：检索 trace_id/阶段耗时/召回日志；建立 Dense Retrieval 离线评测集（人工标注 chunk/page 为真值）。依赖：项 1、2。风险：评测需标注数据。
5. **（P2）BM25 + RRF + Dense 召回**：在 Retriever 接口下新增 BM25 与 Embedding provider，RRF 融合，再考虑 Cross-Encoder 重排。依赖：项 1、3（持久化）、项 4（评测才能证提升）。风险：无评测不得宣称准确率提升。

> 依赖关系：1 -> 2,3；4 -> 1,2；5 -> 1,3,4。在 4（评测基线）就绪前，不得引入新召回并宣称提升。
