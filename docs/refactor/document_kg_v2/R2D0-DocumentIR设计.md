# R2D0 DocumentIR 设计

## 1. 设计原则

DocumentIR 是解析 provider 与教育业务之间唯一稳定契约：不可变版本、稳定 ID、页级顺序、原文证据、允许部分成功。DocumentIR 不包含 ORM 对象，不把 Markdown 当唯一真相，不丢弃 provider raw result。

### 稳定身份与执行身份

稳定对象身份使用 UUIDv5 或等价的确定性 ID，且只依赖以下输入：

- `artifact_id`：`artifact_sha256 + 源格式规范化规则版本`；同 bytes 和同规则得到相同 ID。
- `document_id`：`artifact_id + schema_version + 文档规范化规则版本`；不依赖解析器选择。
- `unit_id`：`document_id + unit_type + 规范化后的 page_or_slide/index locator`。
- `block_id`：`document_id + unit_id + block kind + provider-neutral locator + normalized content hash`；多解析器融合后保留该 canonical ID。

`run_id` 是一次文档流水线执行的 UUIDv7/ULID；`parser_run_id` 是该执行内一次 ParserProvider 调用的 UUIDv7/ULID。`created_at`、`started_at`、`finished_at`、`duration_ms`、运行状态、错误信息和重试次数都不得参与任何稳定对象 ID。相同 bytes、相同 schema_version、相同规范化规则必须产生相同的 `artifact_id`、`document_id`、`unit_id` 和可重现 `block_id`；不同执行只改变 `run_id/parser_run_id`。

## 2. 顶层对象

### DocumentIR

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | string | 例如 `document-ir/1.0.0` |
| `document_id` | UUID | provider-neutral 稳定 ID |
| `source_artifact` | SourceArtifact | `artifact_id`、sha256、mime、原始名、size 的稳定引用 |
| `parser_runs` | ParserRun[] | 本次执行的 ParserProvider 调用记录；每项同时带 `run_id` 与 `parser_run_id` |
| `units` | DocumentUnit[] | page/slide/sheet/section 单元 |
| `blocks` | `Block[]` | `Block` 是以 `kind` 为判别字段的 `ContentBlock`、`TableBlock`、`FormulaBlock` discriminated union；所有 canonical block 的唯一集合 |
| `assets` | VisualAsset[] | 图片、渲染页、图表等 |
| `quality` | QualityReport | 文档和页级指标 |
| `warnings` | ParseWarning[] | 不阻断但可解释的问题 |
| `created_at` | datetime | 产物创建时间；仅运行元数据，不参与稳定 ID |

### DocumentUnit

字段：`unit_id`、`unit_type(page|slide|section|sheet)`、`index`、`label`、`width/height/unit`、`block_ids`、`reading_order`、`notes_block_ids`、`asset_ids`、`quality`、`provenance`。`block_ids`、`reading_order` 和 `notes_block_ids` 中的每个值都必须引用同一 DocumentIR 顶层 `blocks` 集合中的稳定 `block_id`；不得嵌入第二份 block 对象。

### ContentBlock

`blocks` 使用 `kind` 作为 discriminated union 判别字段：`ContentBlock.kind="content"`、`TableBlock.kind="table"`、`FormulaBlock.kind="formula"`。三者都共享以下字段：`block_id`、`page_or_slide`、`bbox{x0,y0,x1,y1,coordinate_space}`、`reading_order`、`block_type`、`text`、`ocr_text`、`heading_level`、`language`、`style_hints`、`parent_id`、`child_ids`、`confidence`、`provider`、`provenance[]`、`raw_result_ref`、`visual_description`、`warnings[]`。

`block_type` 最低枚举：`title, heading, paragraph, list_item, caption, footnote, header, footer, code, quote, table, formula, image, chart, diagram, unknown`。

### TableBlock

`kind="table"`，并增加：`rows`、`columns`、`cells[{row,col,row_span,col_span,text,bbox,header,confidence}]`、`html`、`markdown`、`caption_block_id`、`continued_from/to`。不能只保存展平字符串。

### FormulaBlock

`kind="formula"`，并增加：`latex`、`normalized_latex`、`display_mode`、`source_text`、`symbol_mentions`、`recognition_confidence`、`image_asset_id`。

### VisualAsset

字段：`asset_id`、`kind(image|chart|diagram|page_render|slide_render)`、`page_or_slide`、`bbox`、`uri`、`sha256`、`mime`、`width/height`、`alt_text`、`visual_description`、`ocr_text`、`linked_block_ids`、`provider`、`confidence`、`provenance`。

### ParserRun

字段：`run_id`（一次文档流水线执行）、`parser_run_id`（一次 ParserProvider 调用）、`provider`、`provider_version`、`model_versions`、`config_hash`、`started_at/finished_at/duration_ms`、`status(succeeded|partial|failed|timeout)`、`input_artifact_id`、`raw_output_uri/checksum`、`error_code/message`、`warnings`、`metrics`、`parent_parser_run_id`。二者均为执行身份，不能作为稳定对象 ID 的组成部分。

### Provenance

字段：`artifact_id`、`run_id`、`parser_run_id`、`provider`、`raw_locator`、`page_or_slide`、`bbox`、`char_span`、`source_block_id`、`transform`、`confidence`。任何融合块可有多个 provenance。

### QualityReport

字段：`overall_score`、`text_coverage`、`reading_order_confidence`、`heading_confidence`、`ocr_ratio`、`formula_coverage`、`table_coverage`、`visual_coverage`、`duplicate_ratio`、`empty_unit_ratio`、`hard_failures[]`、`per_unit[]`、`scorer_version`。

### ParseWarning

字段：`code`、`severity(info|warning|error)`、`message`、`run_id`、`parser_run_id`、`unit_id`、`block_id`、`recoverable`、`details_safe`。禁止记录 token、密钥和不必要的绝对路径。

## 3. 示例 JSON

```json
{
  "schema_version": "document-ir/1.0.0",
  "document_id": "291eeb79-9530-5fd4-94a7-0f4be20aeb30",
  "source_artifact": {
    "artifact_id": "art_01JZ...",
    "sha256": "92f9...d12a",
    "filename": "二叉树.pptx",
    "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "size_bytes": 2841120
  },
  "parser_runs": [{
    "run_id": "run_01JZ...",
    "parser_run_id": "parser_run_native_01JZ...",
    "provider": "native-pptx",
    "provider_version": "1.0.0",
    "model_versions": {},
    "config_hash": "sha256:91ab...",
    "status": "succeeded",
    "duration_ms": 182,
    "raw_output_uri": "artifact://parser_run_native_01JZ/raw.json",
    "raw_output_checksum": "sha256:8fea..."
  }, {
    "run_id": "run_01JZ...",
    "parser_run_id": "parser_run_ocr_01JZ...",
    "provider": "paddleocr-structure",
    "provider_version": "3.x",
    "model_versions": {"layout": "locked-at-release"},
    "config_hash": "sha256:bcde...",
    "status": "succeeded",
    "duration_ms": 641,
    "raw_output_uri": "artifact://parser_run_ocr_01JZ/raw.json",
    "raw_output_checksum": "sha256:11aa..."
  }],
  "units": [{
    "unit_id": "unit_7ab1...",
    "unit_type": "slide",
    "index": 3,
    "label": "第 3 页",
    "width": 13.333,
    "height": 7.5,
    "coordinate_unit": "inch",
    "reading_order": ["blk_title", "blk_def", "blk_formula"],
    "block_ids": ["blk_title", "blk_def", "blk_formula"],
    "quality": {"overall_score": 0.94},
    "provenance": [{"artifact_id": "art_01JZ...", "run_id": "run_01JZ...", "parser_run_id": "parser_run_native_01JZ...", "raw_locator": "slides/3"}]
  }],
  "blocks": [{
    "block_id": "blk_title",
    "kind": "content",
    "page_or_slide": 3,
    "bbox": {"x0": 0.08, "y0": 0.05, "x1": 0.82, "y1": 0.16, "coordinate_space": "normalized"},
    "reading_order": 1,
    "block_type": "heading",
    "heading_level": 2,
    "text": "二叉树的定义",
    "ocr_text": null,
    "confidence": 0.99,
    "provider": "native-pptx",
    "raw_result_ref": "artifact://parser_run_native_01JZ/raw.json#/slides/2/shapes/1",
    "provenance": [{"artifact_id": "art_01JZ...", "run_id": "run_01JZ...", "parser_run_id": "parser_run_native_01JZ...", "page_or_slide": 3, "raw_locator": "slides/3/shapes/1", "confidence": 0.99}],
    "warnings": []
  }, {
    "block_id": "blk_def",
    "kind": "content",
    "page_or_slide": 3,
    "bbox": {"x0": 0.08, "y0": 0.23, "x1": 0.86, "y1": 0.42, "coordinate_space": "normalized"},
    "reading_order": 2,
    "block_type": "paragraph",
    "text": "每个节点最多有两个子节点。",
    "confidence": 0.99,
    "provider": "native-pptx",
    "raw_result_ref": "artifact://parser_run_native_01JZ/raw.json#/slides/2/shapes/2",
    "provenance": [{"artifact_id": "art_01JZ...", "run_id": "run_01JZ...", "parser_run_id": "parser_run_native_01JZ...", "page_or_slide": 3, "raw_locator": "slides/3/shapes/2", "confidence": 0.99}],
    "warnings": []
  }, {
    "block_id": "blk_formula",
    "kind": "formula",
    "page_or_slide": 3,
    "bbox": {"x0": 0.21, "y0": 0.54, "x1": 0.72, "y1": 0.69, "coordinate_space": "normalized"},
    "reading_order": 3,
    "block_type": "formula",
    "latex": "n_0 = n_2 + 1",
    "normalized_latex": "n_{0}=n_{2}+1",
    "source_text": "n0=n2+1",
    "confidence": 0.87,
    "provider": "paddleocr-structure",
    "raw_result_ref": "artifact://parser_run_ocr_01JZ/raw.json#/pages/3/blocks/8",
    "provenance": [{"artifact_id": "art_01JZ...", "run_id": "run_01JZ...", "parser_run_id": "parser_run_ocr_01JZ...", "page_or_slide": 3, "raw_locator": "pages/3/blocks/8", "confidence": 0.87}]
  }],
  "assets": [{
    "asset_id": "asset_slide3",
    "kind": "slide_render",
    "page_or_slide": 3,
    "uri": "artifact://render/slide-3.png",
    "sha256": "27cc...",
    "visual_description": null,
    "ocr_text": "二叉树的定义 ... n0=n2+1",
    "linked_block_ids": ["blk_title", "blk_formula"]
  }],
  "quality": {
    "overall_score": 0.93,
    "text_coverage": 0.96,
    "reading_order_confidence": 0.95,
    "heading_confidence": 0.98,
    "ocr_ratio": 0.12,
    "formula_coverage": 1.0,
    "table_coverage": 1.0,
    "visual_coverage": 0.8,
    "duplicate_ratio": 0.01,
    "empty_unit_ratio": 0.0,
    "hard_failures": [],
    "scorer_version": "quality/1.0.0"
  },
  "warnings": []
}
```

序列化必须保留顶层 `blocks` 的 discriminated union，使用 `kind` 解析并拒绝未知 kind；写入前必须验证每个 `DocumentUnit.block_ids`、`reading_order`、`notes_block_ids` 都能解析到同一 DocumentIR 的 `blocks[].block_id`。JSON round-trip 不能重算稳定 ID；执行元数据仅随 `ParserRun`、Provenance 和 warning 序列化。示例为可读性省略部分可选字段。

## 4. Provider 映射

| Provider | 单元/坐标 | block/type/order | 特殊对象 | raw 与置信度 |
|---|---|---|---|---|
| Docling | page -> DocumentUnit；`prov.page_no/bbox` 归一化 | Docling item label -> block type；原生遍历/reading order | table/formula/picture 映射专用 block/asset | 保存 Docling JSON；每 item provenance |
| native PPTX | slide -> unit；EMU -> normalized bbox | shape z-order + 几何规则形成初始 order；placeholder/style 判断 heading | table、picture、notes、chart relationship | raw 是提取 JSON，不保存 provider 对象 pickle |
| PaddleOCR | page image -> unit/augmentation | layout label、polygon/bbox、reading order | table HTML/cells、formula LaTeX、chart text | 保存 JSON 与模型/config 版本；OCR confidence |

映射器必须记录无法映射的 ParserProvider 字段到 warning，而不是静默删除。DocumentIR schema_version 变更遵循 semver；新增可选字段为 minor，不兼容字段/语义为 major，并提供 migration reader。

## 5. 与现有模型的兼容投影

- `DocumentUnit` -> `DoclingGroup`（只作兼容，不反向作为 V2 真相）。
- paragraph/heading -> `DoclingText`；TableBlock/Picture 可投影到已有模型，但需单独验证字段语义。
- EducationalUnit/Script projection -> `CourseScript/ScriptNode`，保留 `page_start/page_end`。
- `KnowledgePageMap` 从 graph mention/evidence 的 page/block 生成，而不是再做无证据全文猜测。

V2 shadow 禁止写上述 V1 业务表；只有显式 publish/projection 阶段才可在事务中写兼容输出。
