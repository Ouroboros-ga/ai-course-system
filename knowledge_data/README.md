# CS 学科垂类知识库（knowledge_data/）

> 挑战杯 XH-202620《面向一流学科建设的学科垂类大模型与创新应用开发》——计算机学科垂类大模型
> 的领域知识层。2026-08-20 起由空占位填充为首批真实内容（R1）。

## 文件

| 文件 | 内容 | 状态 |
|---|---|---|
| `data_structures.json` | 数据结构基础概念节点（数组/链表/栈/队列/哈希表/树/二叉树/BST/堆/图/并查集） | ✅ 已填充（11 节点） |
| `algorithms.json` | 算法基础概念节点（复杂度/分治/DP/贪心/回溯/二分/排序/图算法/KMP 等） | ✅ 已填充（13 节点） |
| `os.json` | 计算机操作系统概念节点（进程/线程/调度/同步/死锁/内存/虚拟内存/文件系统/I/O/系统调用） | ✅ 已填充（10 节点，R5） |
| `net.json` | 计算机网络概念节点（体系结构/TCP-IP/链路层/IP/传输层/三次握手/应用层/安全/无线） | ✅ 已填充（9 节点，R6） |
| `db.json` | 数据库系统概念节点（关系模型/SQL/设计/事务/并发控制/索引/存储/恢复/安全/分布式） | ✅ 已填充（10 节点，R6） |
| `se.json` | 软件工程概念节点（生命周期/需求/设计/测试/维护/项目/敏捷 DevOps/质量/配置管理） | ✅ 已填充（9 节点，R7） |
| `ml.json` | 机器学习概念节点（基本概念/监督/无监督/评估/线性/集成/深度学习/SVM/特征工程/强化） | ✅ 已填充（10 节点，R7） |
| `compiler.json` | 编译原理概念节点（编译过程/词法/语法/语法树/语义/中间代码/优化/目标代码/符号表） | ✅ 已填充（9 节点，R10） |
| `arch.json` | 计算机组成原理概念节点（层次/数据表示/指令系统/CPU/存储层次/流水线/中断/I-O/并行） | ✅ 已填充（9 节点，R10） |
| `relations.json` | 概念间关系（prerequisite_of / uses / defines / contrasts_with / related_to / supported_by） | ✅ 已填充（82 条） |
| `validate.py` | schema + 引用完整性校验脚本（纯标准库） | ✅ 可用 |
| `import_to_neo4j.py` | 导入计划预览（**不连接 Neo4j**，诚实标注未接线） | ✅ 可用 |

## Schema（cs-knowledge/1.0）

- 节点（`nodes[]`）：`id`（全局唯一）、`name`、`node_type`（对齐
  `backend/app/domain/education_graph/enums.py::NodeType`）、`definition`、
  `key_points[]`、`example`、`source{title, authors, chapter}`（内容可追溯要求）。
- 关系（`relations[]`）：`from` / `to`（引用节点 id）、`relation_type`（对齐
  `RelationType` 语义子集）、`note`。

## 校验与导入

```bash
python knowledge_data/validate.py          # 0=通过；1=失败并打印错误
python knowledge_data/import_to_neo4j.py   # 校验 + 打印导入计划（不写状态）
```

## 集成路径（进度更新）

1. ✅ **已落地（R2）**：`backend/app/platform/knowledge/discipline_kb.py` 检索服务 +
   `GET/POST /api/v1/discipline-knowledge/*` 只读 API（关键词检索含权威来源、节点 + 图邻居、
   概览、重载；测试 13 passed）。这是学科知识层的独立可运行入口，直接服务"知识权威可信/内容可追溯"。
2. ⏳ 待接线：作为**课程知识图谱的种子候选**导入 `CourseKnowledgeNode` / `GraphRelation`，
   经教师审核门后进入正式图谱快照；
3. ⏳ 待接线：接入 `ActiveBundleCourseRetrievalPort` 检索白名单，使学科知识库与课件证据
   一并参与 RAG（BM25 + BGE + RRF + Citation 闭包）；
4. ✅ **已扩充（R5–R10）**：操作系统（`os.json`）、计算机网络（`net.json`）、数据库系统（`db.json`）、
   软件工程（`se.json`）、机器学习（`ml.json`）、编译原理（`compiler.json`）、计算机组成原理（`arch.json`）
   ——**九门课全部完成**（90 节点/82 关系）；后续按需扩充（如离散数学、计算机图形学）。

## 诚实边界

- 本目录是**数据与校验脚本**，不是已接线的生产知识库；"学科知识库已填充"
  只表示数据内容与校验脚本存在且可运行，不表示课程检索已消费这些数据。
- 权威来源为公开教材与经典专著（严蔚敏《数据结构》、Cormen《算法导论》等），
  章节号来自对应教材目录；未使用任何未经授权或敏感数据。
