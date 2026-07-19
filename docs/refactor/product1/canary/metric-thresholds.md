# G5B-0 指标阈值规范（Metric Thresholds）

> 状态：**准备（G5B-0）**。阈值为提议值，待 G5B 执行阶段用金标集校准。
> 约束：不安装到生产、不接生产主链、不调用真实付费服务（CLAUDE.md 仍生效）。
> 放行顺序：Docling -> PaddleOCR -> Embedding -> Reranker -> LLM，逐项申请放行。

## 1. 目的

为每个真实 V2 provider 定义质量指标 + 验收阈值。G5B 执行时：V2 provider 在金标集上跑 -> 计算指标 -> 与阈值比对 -> 通过则该 provider 可进入下一阶段（仍需人工放行）。

## 2. 维度区分（与 G5A.1 对齐）

- **execution_safety**：V1 隔离保证（不写 V1 表、不阻断 V1、不二次调 LLM）-- 由 G5A 已覆盖，G5B 复用。
- **contract_integrity**：契约/引用不变式（accepted->evidence、scope 隔离、citation 完整性）-- 由 G5A 已覆盖，G5B 复用。
- **model_quality**：真实模型质量 -- **G5B 新增**（G5A 中强制 NOT_EVALUATED）。

本文件仅定义 model_quality 指标与阈值。

## 3. Per-provider 指标与阈值（提议）

### Docling（文档解析）
| 指标 | 定义 | 阈值（提议） | 维度 |
| --- | --- | --- | --- |
| `structural_fidelity` | 标题层级/段落/表格结构匹配金标的比例 | ≥ 0.85 | model_quality |
| `block_id_stability` | 同文档多次解析 block_id 一致率 | ≥ 0.95 | contract_integrity |
| `formula_placeholder_preserved` | 公式占位保留率（不丢 TextTransformMap 映射） | ≥ 0.90 | contract_integrity |

### PaddleOCR（OCR）
| 指标 | 定义 | 阈值（提议） | 维度 |
| --- | --- | --- | --- |
| `char_accuracy` | 字符级准确率（vs 金标文本） | ≥ 0.92 | model_quality |
| `page_recall` | 含文字页召回率（不漏页） | ≥ 0.95 | model_quality |
| `noise_rate` | 幻觉字符率（越低越好） | ≤ 0.03 | model_quality |

### Embedding（向量检索）
| 指标 | 定义 | 阈值（提议） | 维度 |
| --- | --- | --- | --- |
| `recall_at_k` | 金标 chunk 在 top-k 命中率（k=5） | ≥ 0.70 | model_quality |
| `scope_isolation` | 跨课程泄漏率（越低越好，RISK-03） | ≤ 0.00 | execution_safety |
| `mrr` | 金标 chunk 平均倒数排名 | ≥ 0.55 | model_quality |

### Reranker（重排序）
| 指标 | 定义 | 阈值（提议） | 维度 |
| --- | --- | --- | --- |
| `ndcg_at_k` | nDCG@k（k=5，vs 金标排序） | ≥ 0.75 | model_quality |
| `mrr` | 金标首位平均倒数排名 | ≥ 0.65 | model_quality |
| `latency_p95_ms` | 重排序 p95 延迟 | ≤ 800 | execution_safety |

### LLM（答案生成）
| 指标 | 定义 | 阈值（提议） | 维度 |
| --- | --- | --- | --- |
| `faithfulness` | 答案可由 evidence 支撑的比例（无幻觉） | ≥ 0.85 | model_quality |
| `citation_completeness` | 引用可解析且证据存活率 | ≥ 0.90 | contract_integrity |
| `abstain_when_no_evidence` | 无证据时正确 abstain 率 | ≥ 0.95 | contract_integrity |
| `v1_answer_unchanged_in_shadow` | shadow 模式下 V1 答案不变率 | = 1.00 | execution_safety |

## 4. 阈值校准

- 上述阈值为**初始提议**，非冻结。G5B 执行时用金标集 + V1 baseline 跑一次，记录 V1 baseline 指标，阈值须 **>= V1 baseline + 合理 delta**（否则无升级价值）。
- 阈值冻结：经 P1-00 + P1-10 审批后冻结为 `canary-thresholds/1.0`。

## 5. 单 provider 通过门禁

某 provider 可进入下一阶段，当：
1. 其金标子集全部跑完（样本量达标）。
2. 该 provider 全部 model_quality 指标 >= 阈值。
3. execution_safety + contract_integrity 指标无 FAIL（复用 G5A.1 三维度判定）。
4. real_services_called 由 Provider 调用记录推导为 True（且仅该 provider 被真实调用）。
5. 人工"放行"。

## 6. G5B-0 边界

- ✅ 本规范、指标定义、提议阈值、校准流程。
- ❌ 不跑任何 provider（阈值未校准）。
- ❌ 不安装依赖、不接真实服务。
