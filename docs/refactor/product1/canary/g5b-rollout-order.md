# G5B-0 放行顺序（G5B Rollout Order）

> 状态：**准备（G5B-0）**。
> 约束：不安装到生产、不接生产主链、不调用真实付费服务（CLAUDE.md 仍生效）。
> **后续只按 Docling -> PaddleOCR -> Embedding -> Reranker -> LLM 顺序逐项申请放行。**

## 1. 放行顺序（固定）

```
G5B-0（准备，已完成）
  -> G5B-1 Docling（人工放行）-> 验证通过
  -> G5B-2 PaddleOCR（人工放行）-> 验证通过
  -> G5B-3 Embedding（人工放行）-> 验证通过
  -> G5B-4 Reranker（人工放行）-> 验证通过
  -> G5B-5 LLM（人工放行）-> 验证通过
  -> G5B 完成 -> G6（Preferred，需 G5B 完成）
```

**不得跳序、不得并行**。每项须前一项验证通过 + 人工"放行"才启动。

## 2. 每项放行的进入门禁

- 前一项 G5B-N 已退出通过（G5B-1 无前置，仅 G5B-0 准备完成）。
- 该 provider 的金标子集就绪（gold-standard-dataset-spec.md）。
- 该 provider 的指标阈值已校准（metric-thresholds.md）。
- 隔离环境方案已就绪（isolation-environment-plan.md）。
- 人工"放行"。

## 3. 每项放行的退出门禁

- 该 provider 真实实现满足 G2 Protocol，产出符合冻结契约。
- 该 provider 在金标子集全部 model_quality 指标 >= 阈值。
- execution_safety + contract_integrity 无 FAIL（G5A.1 三维度判定）。
- `real_services_called` 由 ProviderCallLog 推导为 True，且**仅该 provider** 被真实调用（未越序调用下游）。
- 隔离环境验证：生产 venv 无新依赖、生产主链未改、生产 DB 未触。
- P1-10 独立验证 + 人工确认。

## 4. 顺序理由（详见 provider-compatibility-matrix.md §5）

- Docling（解析源头）-> PaddleOCR（图像文字补充）-> Embedding（向量检索）-> Reranker（重排）-> LLM（答案生成，风险最高最后）。

## 5. 失败处理

- 某 provider 未达阈值 -> 不放行下一项；记录失败指标，调整实现或阈值（阈值调整走 P1-00 审批）后重试该项。
- 隔离环境泄漏到生产 -> 立即回滚（拆 venv/容器、关 flag），P1-10 审计。

## 6. G5B-0 边界

- ✅ 本放行顺序、门禁定义。
- ❌ 不启动任何 G5B-N（N>=1）。
- ❌ 不安装依赖、不接真实服务。
