# R2D0-P1A：统一 Retriever 接口与知识作用域建模

更新时间：2026-07-13
分支：`feature/document-kg-v2`
状态标注口径：已实现 / 部分实现 / 未实现 / 仅文档规划 / 占位代码 / 待验证

---

## 1. 本轮范围

### 做了什么

1. 定义显式知识检索作用域 `RetrievalScope`（`course:<id>` / `knowledge_base:<id>` 互不冲突）。
2. 定义统一检索结果 `RetrievedChunk`（含稳定 `chunk_id`，不伪造页码/章节 ID）。
3. 定义 `Retriever` / `ScopedRetriever` Protocol。
4. 将现有 `TreeRAGRetriever` 包装为第一个真实 Provider `TreeRetrieverProvider`。
5. 建立 `RetrieverRegistry`（作用域->检索器，原子替换）与 `RetrievalGateway`（统一入口+兜底）。
6. 将 `QAService` 从直接依赖全局 `rag_pipeline` 迁移为依赖 `RetrievalGateway` + 显式课程 scope。
7. `rag_pipeline` 降为兼容层，内部委托 Gateway/Registry，旧签名全保留。
8. 修复 `course_id` 与 `knowledge_base_id` 同值时的裸字符串注册表冲突（`knowledge_service` 改用 `knowledge_base` scope）。
9. `delete_course` 清理该课程的进程内 RAG 作用域（best-effort 小范围安全修复）。
10. 新增 29 个检索契约测试；P0 的 15 个课程隔离测试经 fixture 更新后全绿。

### 未做（明确划界）

- 未引入 FAISS / Chroma / Embedding / Sentence-Transformers / BGE / BM25 / RRF / Cross-Encoder / GraphRAG / 知识图谱 / 多智能体 / 长期记忆。
- 未新增数据库表、未做迁移、未改 API 路径/请求/响应契约、未改前端、未改数字人/PPT/TTS/LLM 适配层。
- 未实现索引持久化（仍为进程内内存）。
- 未实现 Evidence Package 对外契约（`RetrievedChunk` 仅内部使用，`ragSources` 外部结构未变）。
- 未实现权限过滤、检索 trace、检索评测。
- 未 commit / push。

---

## 2. 修改前真实架构

证据来自 P0 审计（`R2D0-P0课程范围隔离修复与RAG审计.md`）+ 本轮代码核验，与当前代码一致。

```
QAService.retrieve_rag_context(question, course_id)
  -> rag_pipeline.retrieve(question, course_id=course_id)   [直接依赖全局单例]
     -> rag_pipeline._course_retrievers[str(course_id)]     [裸字符串注册表]
        -> TreeRAGRetriever.retrieve
  -> rag_pipeline.get_context_for_result(result)            [访问 _retriever]
```

问题：

- `QAService` 直接依赖全局 `rag_pipeline`，访问其 `_retriever` / `_course_retrievers`。
- 无统一 Retriever Protocol，无显式作用域类型。
- `_course_retrievers` 以裸 `str(course_id)` 为键；`knowledge_service.py:646` 用 `doc_id=str(kb_id)` 写入**同一注册表**，`course_id=5` 与 `kb_id=5` 冲突。
- `rag_pipeline.retrieve(query)` 无 `course_id` 时回退「最后一次构建的全局树」——生产主链在 P0 后已不再走该路径，但遗留路径仍存在且会污染。
- 检索结果仅 `path/score/match_type`，无统一 `RetrievedChunk`，无稳定 `chunk_id`。

---

## 3. 修改后架构

```
QAService.retrieve_rag_context(question, course_id)
  -> RetrievalGateway.retrieve(query, scope=RetrievalScope.course(course_id), top_k)
     -> TreeRetrieverProvider.retrieve(query, scope, top_k)   [Retriever 协议]
        -> RetrieverRegistry.get(scope) -> TreeRAGRetriever
        -> RetrievalResult 映射为 RetrievedChunk
  -> RetrievedChunk 列表 -> 旧 ragSources 结构（外部兼容）
```

旧 `rag_pipeline` 兼容层（保留，内部委托）：

```
rag_pipeline.process_document(..., scope=RetrievalScope.course(id))
  -> 构建知识树 -> RetrievalGateway.index(scope, tree_result)
     -> TreeRetrieverProvider.index -> TreeRAGRetriever.build_index -> Registry.register（原子替换）
  -> 同时更新 self._retriever（保留无 scope 旧路径兼容）

rag_pipeline.retrieve(query, course_id=id)
  -> RetrievalScope.course(id) -> RetrievalGateway.get_raw_retriever -> 底层 TreeRAGRetriever.retrieve
     （返回旧 RetrievalResult 类型，保持调用方契约）

rag_pipeline.retrieve(query)  [无 course_id，已弃用]
  -> DeprecationWarning（每进程一次） -> self._retriever（最后一次构建的全局树）
```

---

## 4. 核心类型

| 类型 | 文件 | 职责 |
|---|---|---|
| `RetrievalScope` | `platform/retrieval/schemas.py` | frozen dataclass，`scope_type` ∈ {course, knowledge_base} + `scope_id`；`key` = `"{type}:{id}"`；可哈希；工厂 `course()` / `knowledge_base()` |
| `RetrievedChunk` | `platform/retrieval/schemas.py` | 统一结果块：`chunk_id`/`content`/`scope` + 可选 `source_id`/`chapter_id`/`page_number`/`retrieval_score`/`match_type`/`path`/`metadata`；当前不具备的字段置 `None` |
| `stable_chunk_id` | `platform/retrieval/schemas.py` | SHA-256(scope.key + 节点路径 + 内容前缀)[:16]，跨进程稳定；**过渡树节点级标识，非未来 DocumentIR 持久主键** |
| `Retriever` / `ScopedRetriever` | `platform/retrieval/base.py` | `Protocol`：`retrieve(query, *, scope, top_k)`；`ScopedRetriever` 增 `index`/`has_scope`/`clear_scope` |
| `RetrieverRegistry` | `platform/retrieval/registry.py` | `scope.key -> TreeRAGRetriever`；`register`（原子替换）/`get`/`has`/`clear`/`clear_all` |
| `TreeRetrieverProvider` | `platform/retrieval/providers/tree.py` | 包装 `TreeRAGRetriever`，返回 `RetrievedChunk`；复用 IK 分词与树检索，不重复实现 |
| `RetrievalGateway` | `platform/retrieval/gateway.py` | 统一入口：空查询/`top_k` 边界/异常兜底；`index`/`retrieve`/`has_scope`/`clear_scope`/`clear_all`；单例 `retrieval_gateway` |

### 分层选择说明

`platform/` 命名空间文档串为 "Platform-level infrastructure helpers"（`platform/tasks` 长任务运行时亦为本地基础设施，证明 `platform/` 非仅外部适配层）。检索 Gateway/Registry 是本地基础设施 seam，依赖方向 `services -> platform/retrieval -> common/RAG`，与现有 `services -> platform/adapters` 一致。故采用 `platform/retrieval/`，未强行放入 `common/` 或 `services/`。

### 循环导入处理

`providers/tree.py` 依赖 `app.common.RAG.tree_rag`，而 `rag_utils.py` 依赖 `app.platform.retrieval`，形成导入期循环。解法：`providers/tree.py` 对 `tree_rag` 用 `TYPE_CHECKING` 守卫类型注解 + 方法内运行时导入，使本包在导入期不触碰 `app.common.RAG`，打破循环。已验证 `import app.main` 通过。

---

## 5. 兼容策略

| 旧接口 | 兼容方式 |
|---|---|
| `rag_pipeline.retrieve(query, course_id=...)` | 保留，`course_id` 转 `RetrievalScope.course`，经 Gateway 取底层检索器，返回旧 `RetrievalResult` 类型 |
| `rag_pipeline.process_document(..., doc_id=...)` | 保留，`doc_id`-only 视为 `course:<doc_id>`（P0 行为），产生一次性 `DeprecationWarning` |
| `rag_pipeline.process_document(..., scope=...)` | 新增推荐入口 |
| `rag_pipeline.get_context_for_result` | 保留，仅依赖 `result.node`，与检索器实例无关 |
| `rag_pipeline.has_course_index` / `clear_course_index` | 保留，委托 Gateway 的 `has_scope`/`clear_scope`（course scope） |
| `rag_pipeline.generate_answer` | 保留（遗留，非生产路径） |
| `rag_pipeline.retrieve(query)` 无 scope | 保留兼容行为（全局树），一次性 `DeprecationWarning`；生产主链不再走 |
| `ragSources` 外部响应 | 结构不变（`path/score/match_type/content_preview`），内部由 `RetrievedChunk` 转换 |
| QA `ask_question_with_rag` 签名 | 不变（`course_id` 参数 P0 已加） |
| API 请求/响应、DB、前端、启动方式 | 均未变 |

生产问答主链（`chat.py /chat/ask` -> `qa_service.ask_question_with_rag(course_id=courseId)` -> `retrieve_rag_context`）已改为经 Gateway + 显式 course scope，不再依赖无作用域检索。`retrieve_rag_context` 的无 `course_id` 路径仅遗留兼容（委托 `rag_pipeline` 全局树 + 警告），生产不触发。

---

## 6. 多文档语义结论

经代码核验：

- `document.py:upload_document` 每次上传新建一个 `Course`（`document.py:411`），即一次上传 = 一个课程。
- `chat.py:_get_course_context` 对课程取 `DoclingDocument.where(course_id=...).first()`（`chat.py:334`）；若同课程有多文档，仅取首条用于 DB 上下文。
- `ppt_generation.py:_parse_generated_pptx` 复用已有 `course`，调用 `process_document(course_id=course.id)`，**覆盖**该课程的 RAG 树。
- `RetrieverRegistry.register` 对同 scope 为单次字典绑定替换。

**结论：当前一个 `course` scope 映射到恰好一棵 `TreeRAGRetriever`；对同一 scope 多次 `index`（重传 / PPT 解析覆盖）为「最后写入覆盖」（last-write-overwrite），既不是聚合，也不是增量更新。** 知识库 scope 同理。

本轮不实现多文档聚合。该语义已通过 `TestAtomicReplace::test_rebuild_replaces_old_index_for_same_scope` 测试锁定。多文档聚合列为下一阶段任务。

---

## 7. 多进程与生命周期风险

本轮仅分析与必要的小修复，未实现持久化。

| 风险 | 现状 | 本轮处理 |
|---|---|---|
| 多 worker | Worker A 上传建内存索引，Worker B 接问答看不到 | 未解决（需持久化/共享存储，下一阶段） |
| 进程重启 | 索引丢失；`retrieve` 返回空，问答回退 DB `course_context`（安全降级） | 已在 Gateway/Provider 保证缺失返回空不回退 |
| 水平扩容 | 不同实例索引不一致 | 未解决 |
| 内存增长 | 每课程/KB 一棵树常驻内存；无 LRU 淘汰 | 未解决（demo 规模可接受） |
| 课程删除 | `delete_course` 现清理该 course scope（best-effort） | 本轮已接入 `rag_pipeline.clear_course_index` |
| 并发更新 | Registry 采用「局部完整构建 -> 成功后单次赋值替换」；构建失败保留旧索引 | 已实现 + 测试（`TestAtomicReplace`） |
| course/kb 同 ID 冲突 | 已由 `RetrievalScope` 显式命名空间消除 | 本轮修复 + 测试（`TestScopeIsolation::test_kb_does_not_leak_into_course`） |

并发模型：当前为单事件循环 async，Registry 单次字典绑定在 GIL 下原子；未引入显式锁。多 worker 下需持久化方案，不在本轮。

---

## 8. 测试结果

```bash
# 新增检索契约 + P0 课程隔离
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_retrieval_gateway.py backend/tests/test_rag_course_scope.py -v
-> 44 passed（29 新增 + 15 P0）

# 主流程回归
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_m4b_main_flows.py \
    backend/tests/test_m7_demo_flow.py backend/tests/test_m4b_fakes.py \
    backend/tests/test_m4a_isolation.py backend/tests/test_m4a_route_contract.py -q
-> 26 passed

# 后端导入
PYTHONPATH=backend backend/.venv/Scripts/python.exe -c "import app.main"
-> OK

# 全量
backend/.venv/Scripts/python.exe -m pytest backend/tests/ -q
-> 28 failed, 218 passed, 11 errors
```

历史基线对比：

| 指标 | P0 基线 | P1A 本轮 | 说明 |
|---|---|---|---|
| passed | 189 | 218 | +29 新增测试 |
| failed | 28 | 28 | 全部为历史基线失败 |
| errors | 11 | 11 | 全部为历史基线错误 |

逐项核对：28 failed + 11 errors **全部**落在 `test_f5_mapping_fix` / `test_new_features` / `test_prerequisite_jump` / `test_split_video_player` / `test_video_generation`（与 `docs/phase1/代码风险清单.md` 记录的历史基线一致）。RAG / retrieval / QA / 上传相关测试**零失败**。本轮**未引入新回归**。

测试不依赖真实 LLM / 网络 / Embedding / FAISS（纯检索路径 + conftest `FakeLLMClient`）。

---

## 9. 尚未实现

- 未实现索引持久化（进程内内存，重启/多 worker 不一致）。
- 未实现 Dense Retrieval / Embedding / BM25 / RRF / Cross-Encoder。
- 未实现 Evidence Package 对外契约（`RetrievedChunk` 仅内部，`ragSources` 外部结构未变）。
- 未实现权限过滤（选课/角色未纳入检索过滤）。
- 未实现检索 trace / 阶段耗时 / 检索评测基线。
- 未实现多文档聚合（当前为 last-write-overwrite）。
- 未实现索引版本 / 快照。
- `document_upload.py`（未注册主流程的重复上传端点）未迁移到显式 scope；若启用需补 `scope=RetrievalScope.course(course.id)`。

---

## 9.1 评审复核与补充修复（2026-07-13）

P1A 评审后补充核实与修复：

### 专项回归 41 vs 26 核实

评审指出专项回归从 P0 的 41 passed 变为 26 passed。核实结论：**无测试丢失/跳过/少跑**。差异源于两轮命令构成不同：

- P0「41 passed」= 5 个回归文件(26) + `test_rag_course_scope.py`(15 P0 测试)，P0 将两者放同一条命令跑。
- P1A「26 passed」= 仅 5 个回归文件；P0/新增测试本轮单独跑（`test_retrieval_gateway.py`+`test_rag_course_scope.py` = 45 passed）。

apples-to-apples 复核：与 P0 **完全相同**的命令（5 文件 + `test_rag_course_scope.py`）-> **41 passed**（与 P0 一致）；再加 `test_retrieval_gateway.py` -> **70 passed**（41 + 29）。P0 的 15 个测试无回归。

### 检查点 1：删除事务顺序 + 知识库删除清理

- `delete_course`：顺序正确--先 `session.commit()`（DB 删除成功提交）后 `clear_course_index`（best-effort）。即使清理失败，DB 已删除，索引为进程内残留（重启消失），不会出现「课程存在但索引消失」。
- **补充修复**：`delete_knowledge_base`（软删除）原先未清理 `knowledge_base` scope，已补 `retrieval_gateway.clear_scope(RetrievalScope.knowledge_base(kb_id))`（commit 后 best-effort），避免残留内存索引被未来 KB 检索误读。

### 检查点 2：`stable_chunk_id` 规范化

原实现用原始 `node_path`+`content` 直接拼接，`\r\n` vs `\n`、连续空格、路径分隔符、Unicode 不同表示会导致相同内容生成不同 id。**已修复**：新增 `_normalize_for_id`（Unicode NFC + CRLF/CR→LF + 反斜杠路径→正斜杠 + 连续空白折叠 + 首尾去空白），`stable_chunk_id` 对三段输入均规范化。新增 `test_chunk_id_invariant_to_whitespace_and_newline_forms` 锁定。

### 检查点 3：无作用域兼容入口审计

全仓搜索 `rag_pipeline.retrieve(` 生产代码命中仅 `qa_service.py:253`，为 `retrieve_rag_context` 中 `course_id is None` 的遗留兼容分支（注释已标注「已弃用，生产主链不触发」）。生产主链 `chat.py /chat/ask` 始终传 `courseId` -> 走 Gateway 路径，**不触发**无作用域调用。**已增强**：无 scope `DeprecationWarning` 现携带调用来源（`文件:行号 (函数)`），便于逐步清理。`rag_utils.py:17` 命中为 docstring 示例，非代码。

---

## 10. 下一步建议（按依赖排序，已按评审意见调整顺序）

评审建议：当前 `RetrievedChunk` 仍缺稳定 `source_id`/文档版本/发布状态/页码来源/多文档关系/索引版本，若立即公开 Evidence Package 对外契约，后续补多文档与持久化时字段语义会再次变化。故**先做来源身份与多文档语义，再持久化，再完善内部 Evidence，最后才对外公开**。

1. **（P1B）来源身份建模与多文档检索语义**：引入 `SourceDocument`（`RetrievalScope -> SourceDocument -> RetrievedChunk`），明确一门课程多份文档（原始 PPT/教材 PDF/补充讲义/AI 生成 PPT）的替换 vs 共存、正式资料 vs 草稿、可检索范围、单文档删除、重解析版本识别、`source_id` 指向。替换当前 last-write-overwrite。← 依赖本轮 `RetrievalScope`/`RetrievedChunk`。
2. **（P1C）索引持久化与重启恢复**：scope->树/chunk 持久化，启动按 scope 重建，解决多 worker/重启/扩容。← 依赖本轮 Registry/Gateway seam；与 R2D0 DocumentIR 表设计对齐避免双轨。
3. **（P1D）内部 Evidence Package 完善**：在 `RetrievedChunk` 补稳定的 `source_id`/文档版本/发布状态/页码来源等，**先内部完善再对外**。← 依赖项 1、2。
4. **（P2A）检索可观测与评测基线**：trace_id/阶段耗时/召回日志；人工标注 chunk/page 真值评测集。← 依赖本轮 Gateway + 项 3。
5. **（P2B）BM25 / Dense / RRF / Reranker**：在 `Retriever` 接口下新增 Provider，RRF 融合，再 Cross-Encoder 重排。**无评测不得宣称提升**。← 依赖项 1、2、3、4。

> 依赖：1 -> 本轮；2 -> 本轮；3 -> 1、2；4 -> 本轮、3；5 -> 1、2、3、4。
> Evidence Package 对外公开推迟至 P1D 内部字段稳定之后。
