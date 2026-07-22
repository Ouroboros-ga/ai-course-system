# B-G0b 真实课件来源与 OCR 预检

- 检查日期：2026-07-16
- 来源状态：`AUTHORIZATION_PRIVACY_ATTESTED_PENDING_VALIDITY_AND_HUMAN_SELECTION`
- 候选数据状态：未创建
- 人工标签：未创建
- 算法比较资格：`false`
- B-R1/B-R2/B-R3：仍未放行

## 1. 来源隔离

原始课件位于 `research/product1_graph_retrieval/human_gold/human_gold_source_v0_1/`。根 `.gitignore` 已增加 `/research/product1_graph_retrieval/human_gold/`，并通过 `git check-ignore -v` 验证。原件不移动、不改写；任何脱敏、解析和研究 sidecar 必须输出到独立候选目录。

用户已确认授权/隐私审签完成，使用范围仅限“智能课程系统”项目内部离线评测且不得对外分发。工具仍不能替代责任人身份、证据引用、授权有效期、逐课文件确认和原页隐私复核记录；这些字段必须进入受控 manifest 后才能通过来源门禁。

## 2. 文件闭合与哈希

4 门课均为 PPTX 与其另存 PDF 的双格式，共 8 个文件、253 页；每对页数完全一致。

| research course | PPTX 页 | PDF 页 | PPTX SHA-256 | PDF SHA-256 |
|---|---:|---:|---|---|
| `course_fuel_supply` | 42 | 42 | `cb412fb6d0558cc506aa364e56b80d1d51a46da98f4bf59ec0d52bf70adf0a7b` | `00c5801f2ec48869665e4e56049d1e53df868e14c46ee08aa1672002c61aaae6` |
| `course_circuit_basics` | 52 | 52 | `c7d138b926f8518f896f67d6a96c95a5556d34bbf883906d2259881d22b4a0f5` | `5c6efff64d0a52f7076893298e00bf7136c055d65c93048789632fb41995f836` |
| `course_ac_motor` | 62 | 62 | `38bf5211d938d215a69feeb6e72c0e756321835446cd47bd4b56c8aeb00b0cc1` | `118c78f7683a16ddbb957e7e108ffb5fb0927dff4c020c7467d0eed20593295d` |
| `course_control_ch2` | 97 | 97 | `5034e0a76e6105bfb2f898e680c230aa9d8776134dccd187ede613377dce7da5` | `13c5311e95e762c2bb5681fd86ad351b923cfb10ca53880fab7eb71f6a1e6d99` |

哈希只冻结当前原件；任何文件变化都必须重新审核和重新计算。

## 3. 原生文本与隐私风险

原生 PPTX 文本总计约 16,848 字符，PDF 文本层约 20,073 字符。两者均有价值，但都不是完整真值：存在图片主导页、PPTX 无文本但 PDF 有文本的页、PDF 无文本但 PPTX 有文本的页，以及阅读顺序和字符内容不一致的页。

预检发现：

- 4 个 PPTX 均含作者/最后修改者等文档元数据；候选导出必须剥离这些字段。
- 至少一页可见内容含邮箱模式；不得进入 public/index inputs 或盲标包。
- 自动正则未发现不等于隐私审核通过。姓名、单位页脚、图片内标识、备注和嵌入对象仍需人工逐课复核。
- 用户已提供授权/隐私用途声明；尚无 `authorized_source_manifest.json` 中的有效期、责任人/证据引用、逐课文件与隐私复核闭合记录，因此不得开始候选数据转换。

## 4. 现有生产解析链路审计

当前 production Document Intelligence 没有可用的真实 OCR：

- `native_pptx.py` 只解析 PPTX 原生文本、备注和 shape 元数据，明确不做 OCR、公式或图片分析。
- `ocr_fake.py` 的 `OcrFakeProvider` 只返回确定性假文本；不能用于真实课件或质量评测。
- 同文件的 `OcrProvider` 只是能力契约，`HAS_PADDLE_OCR` 被固定为 `False`，真实 `parse()` 总是抛出 `ParseUnavailableError`。
- planner 只会选择 `ocr-fake` / `docling-fake` 作为测试路径，未发现真实 PaddleOCR 注册与接线。

本轮未修改任何 `backend/app/**`、依赖或锁文件。若未来接入生产 OCR，必须走独立 ADR、依赖/硬件审批、契约适配和回归测试。

## 5. PaddleOCR 3 / PP-StructureV3 隔离试跑

试跑环境完全位于 Codex visualization 临时根，不写入仓库依赖；版本为 PaddleOCR 3.7.0、PaddlePaddle CPU 3.2.0、PaddleX 3.7.2。采用 PP-StructureV3，关闭表格、公式、图表等额外模型，只保留版面检测和 PP-OCRv5 文本检测/识别。

每门课选择 1 个原生文本稀少或版式复杂页，共 4 页。该抽样用于可用性预检，不是随机样本，也没有人工转写真值，因此不能报告 CER/WER 或宣称全课准确率。

| sample | PPT 原生字符 | PDF 文本字符 | OCR 字符 | 版面块 | OCR 置信度中位数 | `<0.5` 行 | CPU CLI 耗时 |
|---|---:|---:|---:|---|---:|---:|---:|
| `fuel_p03` | 0 | 42 | 96 | 6 | 0.999 | 1 | 27.8 s |
| `circuit_p05` | 85 | 0 | 130 | 9 | 0.999 | 0 | 34.3 s |
| `motor_p05` | 12 | 0 | 61 | 4 | 0.959 | 2 | 31.8 s |
| `control_p59` | 17 | 17 | 65 | 3 | 0.753 | 4 | 39.6 s |

结果：

- 4 页均成功生成结构化 JSON、Markdown、版面框、阅读顺序和坐标。
- OCR 在原生文本为空或很少时补回了明显更多文本，证明这批课件需要真实 OCR 兜底。
- 图示页出现低置信度单字符/符号噪声，不能把 OCR 结果直接当 Evidence 或 Gold。
- 首页样本识别出邮箱模式，说明 OCR 输出必须再次经过隐私过滤。
- CLI 推理成功并落盘，但默认 `save_all()` 额外导出 Word 时因隔离环境未安装可选 `python-docx` 返回非零；改用 Python API 只保存 JSON/Markdown可完成导出。API 进程在 Windows 上有推理后线程退出延迟，需在正式离线工具中增加超时和子进程隔离。

## 6. B-G0b 推荐解析策略

OCR 不应成为每页无条件必选项，但应成为本批数据的选择性必备能力：

1. 以 PPTX 原生文本和 shape/slide 位置作为稳定结构主干。
2. 以同页 PDF 文本层交叉补全和发现导出差异。
3. 对原生文本过少、图片主导、PPT/PDF 文本明显冲突或含复杂图示的页触发 PP-StructureV3。
4. OCR 结果只写入显式命名的 research sidecar，保留 `bbox`、阅读顺序、模型版本、参数和置信度；不回写冻结生产对象。
5. 页眉页脚、邮箱、文档作者等个人或无关信息必须在候选构建前移除；低置信度块进入人工复核，不自动生成 qrels。
6. 对复杂图表或公式页，先建立人工小样和错误类型，再决定是否评估 PaddleOCR-VL；本轮不调用托管 API、不实现生产 GraphRAG/OCR。

PP-StructureV3 比纯文本 OCR 更符合本任务，因为它原生提供 LLM 可消费的 JSON/Markdown、版面类别、阅读顺序和细粒度坐标。但这些输出只是候选解析 sidecar，不是人工 Gold。

## 7. 当前门禁

用户的授权/隐私审签声明已记录。解除来源阻塞仍需要材料责任人把以下信息写入受控 manifest 并确认：

- `authorized_by` 与授权证据引用；
- 用途 `human_gold_research_evaluation`；
- `valid_from`、`expires_at` 或 `no_expiry=true`；
- 仓库存储授权；
- 隐私复核人和证据引用；
- 批准受控读取原件，声明已知直接标识符是否存在，并提供候选生成前的清洗计划；确认不含学生记录。

完成后，来源 manifest 应只列每门课的 `pptx_source` 与 `pdf_reference` 及 SHA-256。工具预检通过前，不创建 `human_gold_candidate_v0_1`、不生成盲标包、不填写任何人工标签。