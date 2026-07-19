# G5B-0 金标集规范（Gold-Standard Dataset Spec）

> 状态：**准备（G5B-0），未执行**。本文件仅为方案/规范，不含真实金标数据。
> ADR-0006 §8A G5B。约束：不安装到生产、不接生产主链、不调用真实付费服务（CLAUDE.md 仍生效）。
> 后续放行顺序：Docling -> PaddleOCR -> Embedding -> Reranker -> LLM，逐项申请放行。

## 1. 目的

定义 G5B 真实 provider 质量评测所需金标集（gold-standard）的结构、格式、采样规则与存储。金标集用于度量真实 V2 provider 相对 V1 / 相对人标的解析与检索质量。**本文件只定义规范，不收集真实金标数据**（数据收集在 G5B 执行阶段，按逐项放行）。

## 2. 金标集维度（按 provider 切分）

每个 provider 对应一个独立金标子集，按放行顺序准备：

| 顺序 | Provider | 金标子集 | 度量对象 |
| --- | --- | --- | --- |
| 1 | Docling | `docling_gold` | 文档解析结构保真（标题层级、段落、表格、公式占位） |
| 2 | PaddleOCR | `ocr_gold` | OCR 文本召回/字符准确（扫描页/图像文字） |
| 3 | Embedding | `embedding_gold` | 向量检索语义相关性（query->chunk 召回@k） |
| 4 | Reranker | `reranker_gold` | 重排序质量（nDCG@k、MRR） |
| 5 | LLM | `llm_gold` | 答案忠实度/事实性（基于证据的回答正确性） |

## 3. 金标条目结构（通用 schema）

```json
{
  "gold_id": "gold_docling_0001",
  "provider": "docling",
  "source": {
    "doc_ref": "stable DocumentIR document_id 或样本文件名",
    "course_id": "可选，课程隔离参考",
    "page_range": [1, 3]
  },
  "input": {
    "raw_artifact_ref": "样本文件引用（不内联大文件）",
    "question": "仅 retrieval/llm 子集需要",
    "course_scope": "仅 retrieval 子集需要（RISK-03 隔离验证）"
  },
  "expected": {
    "type": "structured | text | ranked_list | answer",
    "value": "金标结构/文本/排序/答案",
    "evidence_refs": ["artifact_id/block_id 引用，仅 llm 子集"]
  },
  "provenance": {
    "annotator": "标注者标识",
    "method": "manual | v1_baseline_plus_human_fix | synthetic_verified",
    "version": "1.0"
  }
}
```

## 4. 采样规则

- 每子集最小样本量（G5B 执行时校准）：docling_gold ≥ 30 文档；ocr_gold ≥ 20 扫描页；embedding_gold ≥ 50 query；reranker_gold ≥ 50 query；llm_gold ≥ 30 query。
- 覆盖性：含中文/公式/表格/扫描混合；含 V1 已知失败 case（证明 V2 价值）。
- 隔离：金标样本可含多课程，但每条带 course_scope；跨课程隔离用 RISK-03 验证。
- 去敏：不内联原始敏感内容；用稳定 ID 引用；遵守 §9 隐私约束。

## 5. 存储与版本

- 存储：`docs/refactor/product1/canary/gold/<provider>_gold.jsonl`（JSONL，一行一条）。**G5B-0 不创建数据，仅定义路径**。
- 版本：每子集 `version` major.minor；金标变更走 P1-00 审批（同 registry 变更规则）。
- 与契约：金标 `expected` 字段类型须对齐已冻结契约（document-ir/1.0、evidence/1.0、citation/1.0、retrieval-provider/1.0、internal-evidence-api/1.0）。

## 6. 度量产出（供 metric-thresholds.md 引用）

每条金标跑 V2 provider -> 产出预测 -> 与 `expected` 比对 -> 单条 pass/fail + 聚合指标。**G5B-0 不跑任何 provider**；仅定义比对将如何进行。

## 7. G5B-0 边界

- ✅ 本规范、目录结构、schema。
- ❌ 不收集真实金标数据（留 G5B 执行）。
- ❌ 不调用任何真实 provider。
- ❌ 不安装依赖。
