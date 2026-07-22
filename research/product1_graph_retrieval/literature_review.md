# 教育图谱与可信检索文献及开源项目调研

> 检索与复核日期：2026-07-16。  
> 本文只引用论文原文页、正式论文库、作者/机构项目页或官方代码仓库。论文结论和本项目推断分栏记录；预印本明确标注，不写成行业定论。

## 1. 结论摘要

1. 教育图谱研究普遍同时建模课程结构、知识概念和教学关系；但节点/关系集合高度依赖场景，不能直接复制某篇论文的本体。
2. 讲义/PPT 的版面、标题、章节顺序本身是强信号。第一版知识点—PPT 页映射应先验证结构与词法基线，而不是立即加入 LLM 或 embedding。
3. 概念抽取和先修关系学习是两个不同任务；后者尤其需要 gold、全局一致性约束和人工审核。
4. 实体归一化不能只做字符串 lower-case。候选生成、上下文消歧、课程实例边界和错误合并率必须单独评测。
5. BM25、Dense、Graph 解决的失败模式不同。论文能支持“值得做消融”，不能支持“Graph 一定优于 BM25/Dense”。
6. RRF 是简单、可解释的排序融合基线，但参数并非普适；本项目必须预注册网格并与单路结果公平比较。
7. Citation 需要同时评估“引用存在/完整”和“证据是否真正支撑”。B-R1 没有生成式回答，因此只评 Evidence/Citation 结构完整性与 gold relevance；语义支撑要留给后续人工或独立评测。

## 2. 核心论文与可用结论

| 方向 | 论文与年份 | 论文/项目原始结论 | 对本项目的推断与边界 |
| --- | --- | --- | --- |
| BM25 | Robertson & Zaragoza, [The Probabilistic Relevance Framework: BM25 and Beyond](https://doi.org/10.1561/1500000019), 2009 | 系统梳理概率相关性框架和 BM25 的词频、文档长度归一化等机制。 | 用透明公式建立 R0 下界；`k1/b` 是配置，不是常数真理。中文 tokenization 和课程 chunk 仍需本地实验。 |
| 排名融合 | Cormack, Clarke, Büttcher, [Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods](https://doi.org/10.1145/1571941.1572114), SIGIR 2009 | 提出基于倒数名次累加的简单融合，并在其数据上优于所比较的单系统/Condorcet。 | RRF 适合作为无需跨模型分数校准的首个 Hybrid；不能据此保证课程语料提升。 |
| 融合敏感性 | Bruch, Gai, Ingber, [An Analysis of Fusion Functions for Hybrid Retrieval](https://doi.org/10.1145/3596512), TOIS 2024 | 比较 RRF 与归一化分数凸组合，指出 RRF 对参数可能敏感，凸组合在其设置中有优势。 | 必须比较多个 `k`，并保留未来分数融合对照；不得把当前代码默认 `k=60` 固化为唯一设置。 |
| Dense | Karpukhin et al., [Dense Passage Retrieval for Open-Domain Question Answering](https://aclanthology.org/2020.emnlp-main.550/), EMNLP 2020 | 双编码器 Dense Retriever 在若干开放域 QA 数据上超过其 BM25 对照。 | 说明 Dense 值得做 paraphrase/semantic recall 对照；开放域英文结果不能外推到中文课程、公式和精确术语。 |
| 异构评测 | Thakur et al., [BEIR](https://datasets-benchmarks-proceedings.neurips.cc/paper/2021/hash/65b9eea6e1cc6bb9f0cd2a47751a186f-Abstract-round2.html), NeurIPS Datasets & Benchmarks 2021 | 在多种 IR 任务上统一评测 sparse/dense 等模型，展示跨域效果差异。 | 本项目必须按 query 类型和课程分层报告，不能只报单一平均分；BEIR 数据不替代本项目 gold。 |
| Citation | Gao et al., [Enabling Large Language Models to Generate Text with Citations](https://aclanthology.org/2023.emnlp-main.398/), EMNLP 2023 | ALCE 将正确性、流畅性和 citation quality 分开评估，并区分 citation correctness/completeness。 | 借用“完整性与支撑性分离”的评测思想；B-R1 不运行其 LLM/NLI 流程，不照搬其分数。 |
| RAG 评测 | Es et al., [RAGAs](https://aclanthology.org/2024.eacl-demo.16/), EACL 2024 Demo | 提出 reference-free 的 RAG pipeline 自动评测维度。 | 可作为后续生成链评测候选；当前禁止真实 LLM，B-R0/B-R1 采用人工 gold 的确定性指标。 |
| 教育概念/先修 | Lu et al., [Concept Extraction and Prerequisite Relation Learning from Educational Data](https://ojs.aaai.org/index.php/AAAI/article/view/5033), AAAI 2019 | 先提取高质量短语并做概念识别，再结合材料依赖学习先修关系，在 Textbook/MOOC 数据上评测。 | 概念候选与先修边必须分阶段；requires/prerequisite 边不能由标题相似直接推出。 |
| MOOC 先修 | Pan et al., [Prerequisite Relation Learning for Concepts in MOOCs](https://aclanthology.org/P17-1133/), ACL 2017 | 研究概念表示和多类特征对 MOOC 先修关系预测的作用。 | 先修关系是独立监督任务；只做一跳图扩展前要有人工确认的 accepted 边。 |
| 教育 KG | Dang et al., [Constructing an Educational Knowledge Graph with Concepts Linked to Wikipedia](https://doi.org/10.1007/s11390-020-0328-2), JCST 2021 | 构建多平台 MOOC KG，包含课程资源、概念链接和先修关系；以外部百科链接辅助规范化。 | 证明“课程结构 + 概念 + 外部规范实体”是一种可行设计；本项目首版不引入外部 Wikipedia，避免范围和证据来源扩大。 |
| 讲义概念图 | [A Comprehensive Text Analysis of Lecture Slides to Generate Concept Maps](https://www.sciencedirect.com/science/article/pii/S0360131517301781), Computers & Education 2018 | 从讲义提取概念—关系—概念三元组，并利用结构/图特征和幻灯片自然布局组织层级，在其 CS 课程材料上做人类评价。 | 支持把标题、布局和章节位置作为显式 feature；论文的相关性/教师评分不能成为本项目目标值。 |
| 通用 IE | Lu et al., [Unified Structure Generation for Universal Information Extraction](https://aclanthology.org/2022.acl-long.395/), ACL 2022 | UIE 用 schema prompt 和统一结构生成建模实体、关系、事件等 IE 任务。 | UIE 是后续候选抽取路线，不适合 B-R1/R2：需要模型与额外依赖，且输出仍只能是 candidate。 |
| Canonicalization | Dash et al., [Open Knowledge Graphs Canonicalization Using Variational Autoencoders](https://aclanthology.org/2021.emnlp-main.811/), EMNLP 2021 | 以表示学习和聚类处理开放 KG 中冗余、歧义的名词/关系短语，并提供 canonicalization 数据集。 | 说明归一化需要聚类与上下文，而非纯字符串；首版先做高精度规则候选和 review，不引入 VAE。 |
| 教育 Graph RAG | Chatti et al., [Leveraging Graph Retrieval-Augmented Generation to Support Learners' Understanding of Knowledge Concepts in MOOCs](https://doi.org/10.1007/978-3-032-00056-9_10), 2025 | CourseMapper 将 Slide、Main Concept、Related Concept 等连成 EduKG/PKG，并在 3 门 MOOC、3 位专家上评估图引导问答/问题生成；作者也指出 QA 准确性与可靠性仍需提升。 | 可借鉴“concept—slide—source”映射和图引导检索任务定义；样本小且含 LLM/外部百科，不能证明本项目 Graph 优于 Hybrid。 |
| 通用 GraphRAG | Edge et al., [From Local to Global: A Graph RAG Approach to Query-Focused Summarization](https://arxiv.org/abs/2404.16130), 2024 预印本 | 针对整库 global sensemaking，使用 LLM 抽图、社区摘要和 map-reduce 回答，在其长文本实验中优于 naive RAG。 | 其目标是全局摘要，不是课程内 evidence-preserving passage retrieval；只作为差异参照，明确不实现。 |
| 近期教育图谱 | Liang et al., [K12-KGraph](https://arxiv.org/abs/2605.09635), 2026 预印本 | 提出 curriculum-aligned K12 图谱及 Ground/Prereq/Neighbor/Evidence/Locate 等图导出任务。 | 任务分层对未来 gold taxonomy 有启发；它是近期预印本，不作为本体冻结或效果定论。 |

## 3. 典型教育本体：最小而不是最大

文献中的本体从“课程/概念/先修”到“教师/学生/资源/外部百科”差异很大。本项目应优先复用已冻结 `edu-graph/1.0`，形成三层视图：

### 3.1 结构层

- Course
- Chapter
- Section
- Page/Slide
- SourceBlock

这层来自 DocumentIR/课程结构，应该确定性构造，不交给 LLM 决定。

### 3.2 教学语义层

- KnowledgePoint / Concept
- Definition
- Formula / Theorem
- Method / Skill
- Example / Exercise
- Misconception
- LearningObjective

首版真正需要映射与检索的核心是 KnowledgePoint、Definition、Formula、Example、Exercise、Misconception；其他类型可以保留在契约中，但不要求 fixture 为凑类型而造数据。

### 3.3 Evidence 与治理层

- EvidenceRecord sidecar（嵌入 EvidenceSpan 字段）
- `SUPPORTED_BY`：语义节点 -> SourceBlock
- `APPEARS_ON`：语义节点/SourceBlock -> Page
- ReviewStatus / ReviewDecision
- GraphSnapshot envelope

Graph evidence 不应被建成无法回到源块的“说明字符串”。accepted 节点与边必须能解析到 active EvidenceRecord；自动抽取结果只保持 proposed/candidate。

## 4. 实体与关系抽取路线比较

| 路线 | 优点 | 主要风险 | 本项目位置 |
| --- | --- | --- | --- |
| 规则/词典/标题结构 | 透明、离线、复现容易、可直接保留 block/page | 召回有限、同义表达不足 | B-R2 首选；先建立下界 |
| 统计短语/关键词抽取 | 无需生成式模型，可产生候选 | 仍需过滤通用词和碎片短语 | B-R2 后的候选实验 |
| UIE/监督 IE | schema 明确，可统一实体和关系 | 模型/依赖重，领域迁移与标注成本 | 需单独批准的后续研究 |
| LLM schema 抽取 | 适配新 schema 快，可生成解释 | 非确定、成本、幻觉、证据跨度漂移 | 当前禁止；未来也只能产 candidate |
| 规则 + 模型混合 | 高精度规则兜底，模型补召回 | 决策与冲突治理更复杂 | 只有 gold 与 review 流程成熟后再做 |

关系抽取必须晚于实体候选与 Evidence 绑定。尤其 `PREREQUISITE_OF` 不能由同页出现或高相似度自动接受；这两个信号最多产 relation candidate。

## 5. 实体归一化方案

推荐把“通用概念”和“课程内知识点实例”分开：

```text
CanonicalConcept
  ├─ CourseKnowledgePoint(course=A, evidence=...)
  └─ CourseKnowledgePoint(course=B, evidence=...)
```

归一化流水线：

1. 表面规范化：Unicode NFKC、大小写、全半角、可控标点/空白；保留原文本。
2. 高精度别名：教师确认词典，例如“二分查找/折半查找/Binary Search”。
3. 候选生成：字符 n-gram、token overlap，后续可加入 embedding。
4. 上下文消歧：课程、章节、定义、相邻概念、Evidence block。
5. 决策：`same / different / needs_review`，并记录 reason codes。
6. 跨课程默认只建立“候选同义”而不自动合并课程实例。

关键指标不是只有 pair F1，还要单报错误合并率。教学场景中错误合并可能把不相同概念、不同课程口径或不同难度层级混成一个节点，风险通常高于暂时未合并。

## 6. BM25、Dense 与 Graph 各自适合什么

### BM25

更适合：

- 精确术语、标题、定义关键词；
- 公式名、API 名、代码标识符；
- 小语料、离线、强可解释和无模型依赖场景。

较弱：

- 大幅同义改写；
- 跨语言别名；
- 必须依靠多跳关系才能找到的内容。

### Dense

更适合：

- 同义改写和语义相近表达；
- 训练/预训练语料覆盖良好时的自然语言查询。

风险：

- 模型域偏移；
- 公式/代码/稀有术语；
- 模型版本、权重、硬件和近似索引导致复现复杂；
- 相似不等于证据支撑。

### Graph expansion

更适合：

- 明确的 prerequisite、example、formula-use、misconception 等关系查询；
- 从已命中知识点扩展到有证据的相邻教学资源；
- 需要输出路径解释的场景。

风险：

- 错边和错误归一化放大；
- hub 节点导致主题漂移；
- 图覆盖不足时不如文本召回；
- 跨课程边造成污染；
- 成本和延迟增加。

因此图扩展是 Hybrid 后的受限增量，不是默认替代检索。

## 7. RRF 和其他融合方法

RRF 使用每个系统的名次而非原始分数：

```text
RRF(d) = Σ_s weight_s / (k + rank_s(d))
```

优点是避免 BM25 与 cosine score 直接不可比；缺点是丢弃分数间距，且 `k`、候选深度、权重和稳定 ID 都会影响结果。

本项目首轮：

- 预注册 `k ∈ {20, 60, 100}`；
- 默认等权，同时保留小型权重网格；
- 只对同课程候选融合；
- 使用 Evidence-backed stable chunk ID 去重；
- 相同 RRF score 用 chunk ID 稳定排序；
- 输出每个 hit 的 sparse rank、dense rank、RRF 分量和最终分数。

后续可比较归一化分数凸组合，但不得在 test 集上反复调权。

## 8. 跨课程污染与 Citation 完整性如何评测

### 8.1 跨课程污染

- fixture 至少两个课程，并包含同标题/同术语干扰项。
- 索引物理/逻辑上先按 course 分区，再评分。
- 每个 result 都校验 `result.course_id == query.course_id`。
- `cross_course_contamination_rate = wrong_course_hits / all_hits`。
- 门禁为精确 0；任何一次污染都列为 P0 失败样例。

### 8.2 Citation 结构完整性

每个非 abstain hit 必须有：

- `evidence_id`
- `artifact_id`
- `document_id`
- `unit_id`
- `block_id`
- `version_ref`
- `page_or_slide`
- active status
- 可重新计算且非空的 citation key

还要验证 Evidence 中的字符区间和 snippet 与 frozen block 一致。结构完整不等于语义正确；后者用 gold relevance、Evidence binding accuracy，以及后续独立人工 citation support 标注评估。

### 8.3 abstain

- 无 active Evidence：硬 abstain。
- 只有错误课程证据：硬 abstain，不能回退全局。
- 有 Evidence 但分数过低/映射歧义：使用验证集注册阈值后的软 abstain。
- abstain 时不创建 Citation，不把 `unknown` 包装成引用。

## 9. 开源项目适配审查

| 项目 | 官方定位 | 可借鉴内容 | 本轮决定 |
| --- | --- | --- | --- |
| [BM25S](https://github.com/xhluca/bm25s) | 基于 NumPy/稀疏矩阵的 Python BM25 实现，支持多种 BM25 变体 | 公式实现、语料接口、性能对照 | 不安装；B-R1 用标准库透明实现。未来可在独立环境做 parity/performance 对照。 |
| [Pyserini](https://github.com/castorini/pyserini) | 基于 Lucene/Anserini 与 Faiss 的可复现 sparse/dense 检索工具 | TREC run 格式、BM25/Dense/Hybrid 复现实验组织 | 依赖 Java、PyTorch/Transformers 等，当前过重；仅作为外部 oracle 候选。 |
| [BEIR](https://github.com/beir-cellar/beir) | 多数据集异构 IR benchmark 与统一评测代码 | qrels、corpus/query/run 分离和分层评测 | 借鉴数据组织；不用其公开分数代替课程 gold。 |
| [Sentence Transformers](https://github.com/huggingface/sentence-transformers) | embedding、reranker、sparse encoder 工具链 | 后续 Dense/Cross-Encoder 模型适配 | 不进入 B-R1/R2；B-R3 需单独批准模型、revision、权重与离线缓存。 |
| [Faiss](https://github.com/facebookresearch/faiss) | dense vector exact/approximate similarity search | exact flat baseline、后续 ANN 速度/质量对照 | 首个 Dense 实验优先 exact flat，避免 ANN 误差；不修改生产依赖。 |
| [ALCE](https://github.com/princeton-nlp/ALCE) | citation generation/evaluation benchmark | citation correctness/completeness 分离、失败分析 | 只借鉴指标思想；不运行真实 LLM/NLI 基线。 |
| [UIE](https://github.com/universal-ie/UIE) / [PaddleNLP](https://github.com/PaddlePaddle/PaddleNLP) | schema 驱动的通用信息抽取及实现生态 | 后续实体/关系 candidate 生成 | 依赖和模型成本高，许可证/商用边界也需独立审查；当前不接入。 |
| [Microsoft GraphRAG](https://github.com/microsoft/graphrag) | LLM 抽图、社区摘要、local/global/DRIFT 等查询流程 | query taxonomy、图检索失败模式、成本意识 | 官方仓库也提示索引成本与配置适配；本项目不安装、不调用、不实现生产 GraphRAG。 |

## 10. 技术选择建议

- B-R1：自包含、确定性 BM25；每课程独立索引；完整 Evidence sidecar；不新增依赖。
- B-R2：可解释三特征映射；输出 feature breakdown；无证据/歧义 abstain。
- B-R3 Dense：模型候选 bake-off 后再冻结一个版本；exact search 起步。
- B-R3 Hybrid：RRF 参数网格 + 单路对照；不要只跑默认参数。
- B-R3 Graph：accepted/active/same-course 一跳扩展；不做 LLM 抽图、社区摘要或生产 GraphRAG。
- 任何算法只有经过 P1-10 独立复核、Shadow/Canary 和人工批准才可能晋级；研究结果本身不改变生产状态。
