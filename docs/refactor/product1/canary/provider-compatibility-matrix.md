# G5B-0 Provider 兼容矩阵（Provider Compatibility Matrix）

> 状态：**准备（G5B-0）**。基于公开文档与 G2 契约接口调研，非实测。
> 约束：不安装到生产、不接生产主链、不调用真实付费服务（CLAUDE.md 仍生效）。
> 放行顺序：Docling -> PaddleOCR -> Embedding -> Reranker -> LLM，逐项申请放行。

## 1. 目的

记录每个真实 V2 provider 的版本、资源需求、依赖足迹、隔离环境要求，与 G2 已冻结的 Protocol 接口对齐。G5B 执行时按此矩阵在隔离环境准备（非生产）。

## 2. Provider 兼容矩阵

| Provider | G2 Protocol 接口 | 候选实现 | 资源需求 | 依赖足迹 | 隔离环境 | 放行顺序 |
| --- | --- | --- | --- | --- | --- | --- |
| Docling | `ParserProvider`（P1-02 `document_intelligence/providers/`，现 `docling_fake`） | `docling` (官方) | CPU 可用，GPU 加速；磁盘 ~2GB 模型 | 重（含 torch/transformers 子集） | 独立 venv/容器，离线模型 | 1 |
| PaddleOCR | `ParserProvider`（OCR enrichment） | `paddleocr` | CPU/GPU；磁盘 ~200MB 模型 | 重（paddlepaddle） | 独立 venv/容器 | 2 |
| Embedding | `VectorProvider`（P1-03 `retrieval/providers/contracts.py`，现 `FakeVectorProvider`） | 本地 sentence-transformers / 在线 API | GPU 优选；磁盘 ~500MB-2GB | 中-重（torch） | 独立 venv/容器，离线模型 | 3 |
| Reranker | `RerankerProvider`（P1-03，现 `FakeRerankerProvider`） | 本地 cross-encoder / 在线 API | GPU 优选；磁盘 ~500MB-2GB | 中-重（torch） | 独立 venv/容器 | 4 |
| LLM | `LLM`（`app/common/llm_client.py`，现 doubao/aliyun） | 在线 API（doubao 等） | 网络 + API key | 轻（HTTP 客户端） | 网络 + 密钥隔离 | 5 |

## 3. 与 G2 契约对齐

- Docling/PaddleOCR -> 实现 P1-02 `ParserProvider` Protocol（`document_intelligence/providers/contracts.py`）；产出 `document-ir/1.0`。**不改契约**，仅新增真实实现（fake 保留）。
- Embedding/Reranker -> 实现 P1-03 `VectorProvider`/`RerankerProvider` Protocol（`retrieval/providers/contracts.py`）。**不改契约**，仅新增真实实现。
- LLM -> 复用现有 `llm_client` 抽象；G5B 仅在隔离 canary 中调用，不接生产主链。

## 4. 资源与冲突评估

- **GPU 端口冲突**：M7 基线占 GPU/端口 {7860, 8383}（见 G3B 约束）。真实 provider 隔离环境须避开这些端口。
- **磁盘**：模型文件总量可达 4-6GB；隔离环境独立目录，不污染生产。
- **依赖冲突**：docling/paddleocr/torch 版本可能与生产 venv 冲突 -> 强制独立 venv/容器（见 isolation-environment-plan.md）。

## 5. 放行顺序理由

1. **Docling 先**：文档解析是下游所有（retrieval/citation/graph）的输入源头；结构保真不达标则下游无意义。
2. **PaddleOCR 次**：补充扫描/图像文字，依赖 Docling 已就位的 DocumentIR 结构。
3. **Embedding**：向量检索是 V2 retrieval 核心，依赖已解析的 chunk。
4. **Reranker**：在 Embedding 召回基础上重排，依赖 Embedding。
5. **LLM 最后**：答案生成是最终环节，依赖前面所有证据链；风险最高（付费 + 改答案），最后放行。

## 6. 每项放行的最小验证

每 provider 放行前须独立验证（不依赖未放行的下游）：
- 契约对齐：实现满足 G2 Protocol，产出符合冻结契约。
- 隔离：仅在隔离环境运行，不接生产主链。
- 指标：在自身金标子集达标（见 metric-thresholds.md）。
- 审计：Provider 调用记录入 canary ProviderCallLog（real_services_called 可推导）。

## 7. G5B-0 边界

- ✅ 本矩阵、候选实现调研、资源评估、放行顺序。
- ❌ 不安装任何 provider 依赖。
- ❌ 不接生产主链、不调真实付费服务。
- ❌ 不修改 G2 Protocol 接口或 fake 实现。
