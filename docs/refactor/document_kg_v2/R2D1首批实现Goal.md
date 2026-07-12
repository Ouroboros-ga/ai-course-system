# R2D1 首批实现 Goal

## 1. 目标

建立 Document Intelligence V2 的最小可测试底座：稳定 SourceArtifact、DocumentProbe、ParserProvider/ParserRegistry、DocumentIR、FakeParser、JSON artifact persistence、一个现有 parser 到 DocumentIR 的最小 adapter、V1/V2 flags 和微型 benchmark 目录。不得实现完整知识图谱、OCR/VLM 或生产迁移。

## 2. 开始前检查

```powershell
git status --short
git branch --show-current
git log --oneline -5
git stash list
```

要求：在 `feature/document-kg-v2` 或经批准的后续分支；M7 已提交；不恢复 stash；若存在无关未提交生产代码，停止并报告。

## 3. 必须阅读

- `AGENTS.md`
- 本目录全部 R2D0 文档
- `backend/app/services/document_service.py` 中 ParseResult/DocumentParser
- `backend/app/common/ppt_parser.py`
- `backend/app/platform/tasks/` 和 adapters contract
- `backend/tests/conftest.py`、`fakes.py`、M4A/M4B/M7/R2 测试

## 4. 允许范围

优先新增：

```text
backend/app/platform/document_intelligence/
  contracts.py
  source_artifact.py
  probe.py
  registry.py
  document_ir/{models.py,serialization.py}
  providers/{fake.py,v1_document_service.py}
  persistence/json_artifact_store.py
backend/tests/document_intelligence/
backend/tests/benchmarks/document_kg_v2/
docs/refactor/document_kg_v2/R2D1执行报告.md
```

允许对测试配置增加默认 `v1_only` flag。若要修改 `document.py`、数据库模型、migration、requirements 或现有 service，必须停止并先人工 review；R2D1 默认不需要这些修改。

## 5. 详细需求

### 5.1 SourceArtifact

- 由本地 fixture/path 构建：`artifact_id`、sha256、filename、mime、size、created_at、uri。
- `artifact_id/document_id/unit_id/block_id` 是稳定身份；同 bytes、同 schema_version、同规范化规则必须相同，`created_at` 不参与稳定 ID。
- `run_id/parser_run_id` 是执行身份；duration、status、错误与重试不得参与稳定 ID。
- 不读取上传目录以外任意路径；不复制生产源文件。

### 5.2 DocumentProbe

- 只用已有标准库/已安装依赖做轻量探测。
- 输出真实 mime/signature、extension、size、format、page/slide hint、encrypted/corrupt/unsupported、native text/image/table hints。
- 首批至少支持 PPTX、PDF、DOCX 的可识别/不支持分支；不做 OCR。

### 5.3 Parser contract 与 registry

- `ParserProvider.parse(source_artifact: SourceArtifact, parse_plan: ParsePlan) -> ParserOutput`；声明 name/version/capabilities。
- registry 支持显式注册、重复名拒绝、能力过滤、未知 provider 错误。
- 不用动态插件扫描、entry point 或复杂 DI。

### 5.4 DocumentIR

- 实现 `DocumentIR, DocumentUnit, ContentBlock, TableBlock, FormulaBlock, VisualAsset, ParserRun, Provenance, QualityReport, ParseWarning`。
- `DocumentIR.blocks` 必须是以 `kind` 为判别字段的 `ContentBlock | TableBlock | FormulaBlock` discriminated union；`DocumentUnit.block_ids`、`reading_order`、`notes_block_ids` 只引用该顶层集合中的稳定 `block_id`。
- 严格 schema_version、稳定 ID、page/slide、bbox、reading order、provider、confidence、raw ref、warning；JSON round-trip 不得重算稳定 ID。
- JSON round-trip 不丢字段；未知 major 拒绝；optional 字段保持向后兼容。

### 5.5 FakeParser

稳定支持 `success, timeout, service_unavailable, malformed_response, business_failure`，以及 `partial`。business failure 返回结构化 provider 结果但业务 status 失败，不抛网络异常；malformed 与其严格区分。

### 5.6 JSON artifact persistence

- 仅写 pytest 临时目录或明确 V2 shadow 目录。
- 原子临时文件 + rename；checksum；按 run/kind 定位；防目录穿越。
- 不使用 pickle，不写生产数据库，不覆盖同 checksum 以外内容。

### 5.7 最小 adapter

- 只选一个：把现有 `ParseResult/StructureResult` 的已知文本和页信息映射到 DocumentIR。
- 明确 warning：bbox、表格、图片、原始 provenance 缺失。
- 不重写 DocumentParser，不使 adapter 成为生产默认。

### 5.8 Feature flags

解析 `DOCUMENT_PIPELINE_VERSION`、`KNOWLEDGE_GRAPH_PIPELINE_VERSION` 和 runtime mode；pipeline version 是冻结语义版本，runtime mode 是运行选择，默认值必须保持 V1。
- 未知值 fail closed；测试中显式设置。
- R2D1 不把 flags 接到公开 endpoint。

### 5.9 Benchmark skeleton

- `manifest.schema.json`、2-3 个最小自建文本/PPTX-like fixture 或冻结 fake output、gold DocumentIR。
- 不加入比赛材料、旧申报附件、生产文件或受限 OmniDocBench 数据。

## 6. 测试至少覆盖

1. artifact hash/ID 幂等与路径安全。
2. PPTX/PDF/DOCX probe 及 unsupported/corrupt。
3. registry 注册、重复、能力选择、未知 provider。
4. `artifact_id/document_id/unit_id/block_id` 稳定性、执行字段不参与 stable ID、JSON round-trip、schema major 拒绝、bbox/range validation、DocumentUnit 到 DocumentIR.blocks 的引用完整性。
5. FakeParser 六种模式且不联网。
6. business failure 与 malformed/timeout 可区分。
7. JSON store 原子写、checksum、重复写、路径穿越拒绝。
8. 最小 V1 adapter 生成文本/page，并为缺失结构给 warning。
9. 所有 flags 默认 V1、非法值失败。
10. 测试不访问生产库、上传/音频/视频目录、API key 或网络。
11. M7/M4/R1/R2 关键回归通过。

## 7. 禁止

- 不实现知识图谱表、实体/关系抽取、Neo4j/OpenSPG/GraphRAG/LightRAG。
- 不安装新的 Docling/PaddleOCR 版本或任何新依赖。
- 不创建 migration，不改数据库生产结构。
- 不改 endpoint、公开 API、前端、M7、上传发布流程和用户行为。
- 不调用真实 LLM/VLM/OCR/外部服务，不读取生产 key。
- 不恢复 stash，不提交或 push，完成后等待人工 review。
- 不为未来阶段创建未使用的空接口、空 provider 或空目录；只实现本 Goal 实际测试使用的类型。20 层只是职责和契约边界，不要求逐层建模块。

## 8. 停止条件

出现任一项立即停止代码修改并报告：必须改公开 API/数据库/前端；必须大规模重写 `document_service.py`；无法隔离生产路径或网络；关键回归新增失败且不能证明为历史问题；发现无关未提交生产代码冲突；需要引入复杂任务/插件框架。

## 9. 验证命令

先运行新增测试（文件名按实际实现记录）：

```powershell
backend\.venv\Scripts\python.exe -m pytest backend\tests\document_intelligence -q
```

关键回归：

```powershell
backend\.venv\Scripts\python.exe -m pytest `
  backend\tests\test_m7_demo_flow.py `
  backend\tests\test_m4b_main_flows.py `
  backend\tests\test_r1_adapter_migration.py `
  backend\tests\test_r2_task_runtime.py `
  backend\tests\test_r2b_video_task.py `
  backend\tests\test_r2b_ppt_task.py `
  backend\tests\test_r2c_tts_batch_task.py -q
git diff --check
git status --short
git diff --stat
```

前端未修改可不 build，但执行报告必须写明未运行原因。全量后端若有历史失败只分类，不扩大修复范围。

## 10. 完成标准

- 所有最小类型和 contract 有真实测试使用，无未使用占位。
- 同一 fixture 输出稳定 DocumentIR，raw output/DocumentIR 可校验和回放。
- FakeParser 所有模式可控且零网络。
- 默认运行模式仍为 V1，生产文件/DB/API/用户行为未变。
- 新增测试与关键回归通过，或历史失败有可验证对比且未扩大。
- 执行报告记录修改范围、命令、真实结果、限制、回滚。
- git diff 只有经批准的 R2D1 文件；等待人工 review，不自行开始 R2D2。
