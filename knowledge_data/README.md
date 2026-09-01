# CS 学科垂类知识库（knowledge\_data/）

> 挑战杯 XH-202620《面向一流学科建设的学科垂类大模型与创新应用开发》——计算机学科垂类大模型
> 的领域知识层。2026-08-20 起由空占位填充为首批真实内容（R1）。

## 文件

| 文件                     | 内容                                                                                         | 状态               |
| ---------------------- | ------------------------------------------------------------------------------------------ | ---------------- |
| `data_structures.json` | 数据结构基础概念节点（数组/链表/栈/队列/哈希表/树/二叉树/BST/堆/图/并查集）                                               | ✅ 已填充（11 节点）     |
| `algorithms.json`      | 算法基础概念节点（复杂度/分治/DP/贪心/回溯/二分/排序/图算法/KMP 等）                                                  | ✅ 已填充（13 节点）     |
| `os.json`              | 计算机操作系统概念节点（进程/线程/调度/同步/死锁/内存/虚拟内存/文件系统/I/O/系统调用）                                          | ✅ 已填充（10 节点，R5）  |
| `net.json`             | 计算机网络概念节点（体系结构/TCP-IP/链路层/IP/传输层/三次握手/应用层/安全/无线）                                           | ✅ 已填充（9 节点，R6）   |
| `db.json`              | 数据库系统概念节点（关系模型/SQL/设计/事务/并发控制/索引/存储/恢复/安全/分布式）                                             | ✅ 已填充（10 节点，R6）  |
| `se.json`              | 软件工程概念节点（生命周期/需求/设计/测试/维护/项目/敏捷 DevOps/质量/配置管理）                                            | ✅ 已填充（9 节点，R7）   |
| `ml.json`              | 机器学习概念节点（基本概念/监督/无监督/评估/线性/集成/深度学习/SVM/特征工程/强化）                                            | ✅ 已填充（10 节点，R7）  |
| `compiler.json`        | 编译原理概念节点（编译过程/词法/语法/语法树/语义/中间代码/优化/目标代码/符号表）                                               | ✅ 已填充（9 节点，R10）  |
| `arch.json`            | 计算机组成原理概念节点（层次/数据表示/指令系统/CPU/存储层次/流水线/中断/I-O/并行）                                           | ✅ 已填充（9 节点，R10）  |
| `discrete.json`        | 离散数学概念节点（命题逻辑/谓词逻辑/证明方法/集合/关系/函数/图论/欧拉哈密顿/树/计数/代数结构/数论）                                    | ✅ 已填充（12 节点，R11） |
| `graphics.json`        | 计算机图形学概念节点（渲染管线/几何变换/投影/裁剪/光栅化/消隐/光照/纹理/曲线曲面/光线追踪）                                         | ✅ 已填充（10 节点，R11） |
| `relations.json`       | 概念间关系（prerequisite\_of / uses / defines / contrasts\_with / related\_to / derives\_from 等） | ✅ 已填充（106 条）     |
| `validate.py`          | schema + 引用完整性校验脚本（纯标准库）                                                                   | ✅ 可用             |
| `import_to_neo4j.py`   | 导入计划预览（**不连接 Neo4j**，诚实标注未接线）                                                              | ✅ 可用             |

## Schema（cs-knowledge/1.0）

* 节点（`nodes[]`）：`id`（全局唯一）、`name`、`node_type`（对齐
  `backend/app/domain/education_graph/enums.py::NodeType`）、`definition`、
  `key_points[]`、`example`、`source{title, authors, chapter}`（内容可追溯要求）。

* 关系（`relations[]`）：`from` / `to`（引用节点 id）、`relation_type`（对齐
  `RelationType` 语义子集）、`note`。

## 校验与导入

```bash
python knowledge_data/validate.py          # 0=通过；1=失败并打印错误
python knowledge_data/import_to_neo4j.py   # 校验 + 打印导入计划（不写状态）
```

## 集成路径（进度更新）

1. ✅ **已落地（R2）**：`backend/app/platform/knowledge/discipline_kb.py` 检索服务 +
   `GET/POST /api/v1/discipline-knowledge/*` 只读 API（关键词检索含权威来源、节点 + 图邻居、
   概览、重载）。这是学科知识层的独立可运行入口，直接服务"知识权威可信/内容可追溯"。
2. ✅ **已落地（2026-08-31，检索质量强化）**：

   * 精确概念命中前置扫描：查询中独立出现的概念（name/alias，左右 2 字窗口不与其他
     概念名重叠）置顶——修复对比类查询"堆和栈的区别"中次概念被"堆排序"挤出前二，
     同时避免"B+ 树索引"误命中单字泛概念"树"、"欧拉图"误命中"图"；

   * 教学口语化查询噪声剥离："如何给学生们讲清楚动态规划"剥离引导词后精准命中
     "动态规划"；剥离后为空（如"如何理解"）返回空结果；

   * 同课程加成：精确命中某概念时，同课程姊妹概念（动态规划→贪心算法）得分 ×1.5，
     压制其他课程靠"动作/状态"等偶然单字命中的节点（强化学习基础）；

   * 数据：ds-008 二叉搜索树补别名"二叉查找树"（教科书通用同义词）；

   * `discipline_knowledge` 注册进 ToolCatalog（LOW 风险只读上下文工具），
     进入 agent 治理默认策略派生。测试 25 passed。
3. ✅ **已落地（2026-08-31 前后）**：TeachingAgent 教学问答链路经
   `DisciplineKnowledgePort` 消费学科知识库（`/teaching-agent/respond` 响应含
   `discipline_references`，prompt 版本 1.5，前端展示来源引用）。
4. ⏳ 待接线：作为**课程知识图谱的种子候选**导入 `CourseKnowledgeNode` / `GraphRelation`，
   经教师审核门后进入正式图谱快照；
5. ⏳ 待接线：接入 `ActiveBundleCourseRetrievalPort` 检索白名单，使学科知识库与课件证据
   一并参与 RAG（BM25 + BGE + RRF + Citation 闭包）；
6. ✅ **已扩充（R5–R11）**：操作系统（`os.json`）、计算机网络（`net.json`）、数据库系统（`db.json`）、
   软件工程（`se.json`）、机器学习（`ml.json`）、编译原理（`compiler.json`）、计算机组成原理（`arch.json`）、
   离散数学（`discrete.json`）、计算机图形学（`graphics.json`）
   ——**十一门课（112 节点/106 关系，2026-08-30）**；后续按需扩充（如信息安全、分布式系统）。

## 语料层（corpus/，2026-09-01 扩容至 3.26GB）

精编概念层（上表 JSON）之上新增**语料层**：计算机学科方向的开放许可大规模语料，
存放于 `.corpus_cache/`（本地，不入库），由 `corpus/` 下脚本构建，
统计汇总见 `corpus/manifest.json`。

| 语料文件                     | 来源                                            | 规模                    | 许可                     |
| ------------------------ | --------------------------------------------- | --------------------- | ---------------------- |
| `corpus_zhwiki_cs.jsonl` | 中文维基百科 CS 分类子集（PetScan 20 分类）                 | 22,770 篇 / 38.1M 字符   | CC BY-SA 4.0           |
| `corpus_enwiki_cs.jsonl` | 英文维基百科 CS 分类子集（PetScan 38 分类两轮）               | 117,779 篇 / 675.3M 字符 | CC BY-SA 4.0           |
| `corpus_rfc.jsonl`       | RFC 全集（rfc-editor.org，编号 1–10038）             | 9,824 篇 / 537.4M 字符   | 自由分发（IETF）             |
| `corpus_arxiv_cs.jsonl`  | arXiv cs.\* 论文全文（Common Pile CC 授权子集，6/23 分片） | 33,990 篇 / 2.07G 字符   | 论文自带 CC 许可             |
| `corpus_textbooks.jsonl` | 权威开放教材：OSTEP（67 章）、SICP 2e（5 章）               | 72 篇 / 3.07M 字符       | CC BY-NC-ND / CC BY-SA |

构建脚本（`corpus/`）：

* `fetch_petscan_en_robust.py` / `fetch_petscan_cs.py`：PetScan 分类清单（弱网降深度重试）；

* `fetch_hf_wiki.py`：HF wikimedia/wikipedia parquet 分片下载（断点续传）；

* `extract_hf_wiki_cs.py` / `extract_zhwiki_cs.py`：按清单过滤出 CS 语料；

* `fetch_rfc_texts.py` / `build_rfc_corpus.py`：RFC 逐篇抓取与 JSONL 清洗；

* `extract_arxiv_cs.py`：arXiv 元数据快照（librarian-bots）建 cs.\* ID 集，
  过滤 Common Pile 论文分片；

* `fetch_textbooks.py`：OSTEP 逐章 PDF 文本提取 + SICP HTML 章节抓取；

* `build_manifest.py`：汇总生成 `manifest.json`。

诚实边界：

* 语料层**尚未接入任何检索链路**（概念层检索 `discipline_kb.py` 仍只消费精编
  JSON）；接入需走 RAG 检索白名单（见"集成路径"第 5 条）并评估嵌入成本。

* 全部来源为开放许可内容；受版权保护的市售教材**未**纳入（用户持有的纸质书
  无法授权数字化复制）。OSTEP/SICP 为作者自行发布的自由授权版本。

* Think Python（Green Tea Press）抓取被站点限流（404），暂缺，可后续补。

* `archive.org`（Stack Exchange dump）在当前网络 DNS 不可达，未纳入。

## 诚实边界

* 本目录是**数据与校验脚本**，不是已接线的生产知识库；"学科知识库已填充"
  只表示数据内容与校验脚本存在且可运行，不表示课程检索已消费这些数据。

* 权威来源为公开教材与经典专著（严蔚敏《数据结构》、Cormen《算法导论》等），
  章节号来自对应教材目录；未使用任何未经授权或敏感数据。

