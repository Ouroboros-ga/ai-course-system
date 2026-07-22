# B-R1 放行检查报告：Reviewed Silver v0.2

## 结论

`reviewed_silver_v0_2` 已通过个人学习版的 B-G0c 数据闭合检查，可作为下一步离线 BM25 基线实现和探索性评测的冻结输入。

它不是正式 Human Gold：不得将其结果写成双人标注准确率，不授权生产 Provider、GraphRAG、公开 API 或测试环境接入。

## 本次输入与构建

- 审核输入：`RAG素材审核_LLM任务已完成(2).xlsx`，SHA-256 `34d176a8a5f046df154f7808591ef68288ba73ca96375aeb9fbb7e587337b209`。
- 课程源：4 对真实 PPTX/PDF；每对PDF页数与PPTX页数一致。
- 解析：`native_pptx_xml/1`；PPTX原生文本是Evidence原文，PDF只用于来源身份和页数校验。
- OCR：按个人学习决定，不作为质量门禁；本数据包没有伪造OCR文本。
- 空白改写项：14条由 `configs/reviewed_silver_v0_2_reconciliation.json` 的可审计LLM协调记录补全。

## 冻结结果

| 项目 | 数量 |
| --- | ---: |
| 课程 / 页面 | 4 / 253 |
| 章节 / 知识点 / 查询 | 36 / 71 / 96 |
| 源文本块 / active Evidence / corpus chunks | 1083 / 1083 / 1083 |
| retrieval qrels / mapping qrels | 232 / 136 |
| 人工通过 / 人工改写查询 | 66 / 30 |

所有Evidence、Citation key、课程作用域、页码、query/evidence/slide/knowledge-point 引用和 split 均通过 `validate_fixture.py`。同一输入二次重建的 manifest SHA-256 一致：

```text
ea1f660d0c73dff28f1815456a8ab683bde487d85db70f44b6a8c43c41063975
```

## 两层门禁结果

### B-G0c Reviewed Silver

状态：`ready_for_offline_baseline_authorization`

- `offline_baseline_implementation_eligible=true`
- `quality_comparison_eligibility=reviewed_silver_only_not_human_gold`
- `production_integration=not_authorized`

含义：可以开始研究目录内的B-R1 BM25实现，并对本Silver集报告“探索性离线结果”。

### 正式 B-R1 门禁

状态：`blocked`

阻塞原因是正式门禁仍要求Human Gold、独立审批和生产前流程；本个人学习版刻意不伪造这些字段。这些原因不否定Silver数据的可用性，只限制报告口径和生产接入范围。

## 下一步

收到用户对“只在研究目录内开始B-R1”的明确授权后，新增唯一 tokenizer、课程分区BM25、Evidence-preserving hit、abstain和离线运行报告。B-R2必须复用同一BM25/tokenizer，不另建检索实现。
