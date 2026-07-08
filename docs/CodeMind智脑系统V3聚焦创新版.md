> **规划状态说明**：本文档为 9 月后续能力规划与产品方案，不代表当前代码已实现。当前 8 月决赛前真实实现状态以 docs/phase1/ 和 docs/refactor/ 审计文档为准。本阶段禁止实现 BKT、HMM、LSTM、GraphRAG 和复杂多智能体等能力。

# CodeMind 智脑系统 V3.0 — 聚焦创新版

**生成日期**: 2026-06-21
**版本**: V3.0 (聚焦创新版)
**核心理念**: 做减法、加深度、造记忆点

---

## 🎯 设计哲学：从"功能堆砌"到"单点极致"

### V2.0 vs V3.0 对比

| 维度 | V2.0（增强版） | V3.0（聚焦版） | 改进 |
|------|--------------|--------------|------|
| 功能数量 | 8个功能模块 | **3个核心功能** | 砍掉62% |
| 核心创新 | 不明确 | **认知状态追踪引擎** | 明确唯一 |
| 智能体 | 8个线性流水线 | **3个动态协同智能体** | 真协同 |
| 大模型 | LoRA微调 | **GraphRAG知识图谱推理** | 有深度 |
| 可视化 | 排序动画 | **认知过程可视化** | 有创新 |
| 数据库 | 5个 | **2个** | 精简60% |
| 商业模式 | C端SaaS订阅 | **B端高校年度采购** | 可落地 |

---

## 🚀 三大核心功能（只做这三个，做到极致）

### 核心功能1：认知状态追踪引擎（Cognitive State Tracking Engine）

**这是整个系统的灵魂，是评委能记住的"Wow moment"**

#### 1.1 核心创新点

**传统教学系统的问题**：
- 只追踪"学生做对了/做错了"（结果导向）
- 不知道"学生为什么做错"（过程盲区）
- 无法预测"学生下一步会遇到什么困难"（无预测能力）

**CodeMind的突破**：
- ✅ **实时追踪学生的认知过程**（不只是结果）
- ✅ **可视化学生的思维路径**（看到思考过程）
- ✅ **预测学生的学习困难**（提前干预）

#### 1.2 技术架构

```python
class CognitiveStateEngine:
    """
    认知状态追踪引擎
    
    核心能力:
    1. 实时追踪学生在操作数据结构时的认知状态
    2. 基于操作序列推断学生的思维模型
    3. 预测学生可能遇到的学习困难
    4. 生成个性化干预策略
    """
    
    def __init__(self):
        # 认知状态模型（贝叶斯知识追踪改进版）
        self.bkt_model = BayesianKnowledgeTracing()
        
        # 思维路径推断模型
        self.cognitive_path_model = CognitivePathInference()
        
        # 困难预测模型
        self.difficulty_predictor = DifficultyPredictor()
        
        # 个性化干预策略生成器
        self.intervention_generator = InterventionGenerator()
    
    def track_student_cognition(self, student_id, action_sequence):
        """
        追踪学生认知状态
        
        输入: 学生的操作序列
            [
                {"action": "insert_node", "target": "linked_list", "position": 2, "value": 5},
                {"action": "pause", "duration": 15},  # 停顿15秒
                {"action": "delete_node", "target": "linked_list", "position": 1},
                {"action": "error", "type": "pointer_confusion"},  # 指针混淆错误
                {"action": "retry", "attempt": 2},
                {"action": "delete_node", "target": "linked_list", "position": 1, "success": True}
            ]
        
        输出: 认知状态分析报告
            {
                "understanding_level": 0.45,  # 理解程度 45%
                "cognitive_load": 0.78,       # 认知负荷 78%（偏高）
                "knowledge_gaps": ["指针操作", "边界条件处理"],
                "thinking_path": "linear→branching→backtrack",  # 思维路径
                "predicted_difficulty": "双向链表逆序删除",
                "confidence": 0.82,
                "intervention": {
                    "type": "scaffold",
                    "content": "检测到指针操作困难，建议先可视化指针指向...",
                    "priority": "high"
                }
            }
        """
        # Step 1: 实时认知状态评估
        cognitive_state = self.bkt_model.update(student_id, action_sequence)
        
        # Step 2: 思维路径推断
        thinking_path = self.cognitive_path_model.infer(action_sequence)
        
        # Step 3: 学习困难预测
        predicted_difficulty = self.difficulty_predictor.predict(
            cognitive_state, thinking_path
        )
        
        # Step 4: 生成干预策略
        intervention = self.intervention_generator.generate(
            cognitive_state, predicted_difficulty
        )
        
        return {
            "understanding_level": cognitive_state.understanding,
            "cognitive_load": cognitive_state.load,
            "knowledge_gaps": cognitive_state.gaps,
            "thinking_path": thinking_path,
            "predicted_difficulty": predicted_difficulty,
            "confidence": cognitive_state.confidence,
            "intervention": intervention
        }
```

#### 1.3 核心技术难点（评委能看到深度）

**技术难点1：贝叶斯知识追踪（BKT）改进**
- 传统BKT只追踪"会/不会"二元状态
- CodeMind改进：追踪**多维认知状态**（理解、应用、分析、评估）
- 数学模型：
  ```
  P(理解_t | 操作_t) = P(操作_t | 理解_t) × P(理解_t | 理解_{t-1}) / P(操作_t)
  
  多维扩展:
  P(状态_t | 操作_1...t) = ∏ P(维度_i_t | 操作_1...t)
  其中: 维度 ∈ {理解, 应用, 分析, 评估, 创造}
  ```

**技术难点2：思维路径推断**
- 基于操作序列推断学生的思维模式
- 使用Hidden Markov Model（HMM）建模思维状态转移
- 创新点：结合**停顿时间**和**错误类型**推断认知负荷

**技术难点3：学习困难预测**
- 基于历史数据训练预测模型
- 使用LSTM建模操作序列的时序特征
- 预测准确率目标：>80%

#### 1.4 可视化呈现（答辩记忆点）

```
┌─────────────────────────────────────────────────────────┐
│              CodeMind 认知状态仪表盘                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  📊 学生认知状态（实时）                                 │
│  ┌──────────────────────────────────────────────┐      │
│  │  理解程度: ████████░░░░ 45%                  │      │
│  │  认知负荷: ██████████░░ 78% ⚠️ 偏高           │      │
│  │  操作流畅度: █████░░░░░░░ 32%                 │      │
│  │  自信心: ██████░░░░░░ 48%                    │      │
│  └──────────────────────────────────────────────┘      │
│                                                         │
│  🧠 思维路径可视化                                       │
│  ┌──────────────────────────────────────────────┐      │
│  │                                              │      │
│  │   [开始] → [线性思考] → [遇到困难]            │      │
│  │              ↓              ↓                │      │
│  │         [尝试解决] ← [回溯]                  │      │
│  │              ↓                               │      │
│  │         [分支思考] → [错误]                  │      │
│  │              ↓                               │      │
│  │         [重新尝试] → [成功]                  │      │
│  │                                              │      │
│  │   颜色编码: 🟢流畅 🟡停顿 🔴错误 🟣反思      │      │
│  └──────────────────────────────────────────────┘      │
│                                                         │
│  ⚠️ 知识缺口分析                                        │
│  ┌──────────────────────────────────────────────┐      │
│  │  🔴 指针操作 (掌握度: 20%)                    │      │
│  │  🔴 边界条件处理 (掌握度: 25%)                │      │
│  │  🟡 递归思维 (掌握度: 55%)                    │      │
│  │  🟢 基本操作 (掌握度: 85%)                    │      │
│  └──────────────────────────────────────────────┘      │
│                                                         │
│  🔮 学习困难预测                                        │
│  ┌──────────────────────────────────────────────┐      │
│  │  下一可能困难: 双向链表逆序删除               │      │
│  │  预测概率: 76%                               │      │
│  │  建议干预: 先可视化指针指向关系               │      │
│  │  干预时机: 立即                              │      │
│  └──────────────────────────────────────────────┘      │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

### 核心功能2：动态多智能体协同教学（真正的Multi-Agent）

**不是线性流水线，而是有竞争、协商、反思的动态协同**

#### 2.1 核心创新点

**传统"多智能体"的问题**：
- 线性流水线：A→B→C→D，不是真正协同
- 无竞争机制：只有一个智能体做决策
- 无协商机制：智能体之间不交流
- 无反思能力：不会从错误中学习

**CodeMind的突破**：
- ✅ **竞争机制**：多个智能体提出不同教学策略，择优采用
- ✅ **协商机制**：智能体之间就教学方案进行协商
- ✅ **反思能力**：从教学效果中学习，优化策略
- ✅ **动态角色**：根据教学场景动态切换角色

#### 2.2 智能体架构（只有3个，但真正协同）

```python
from langgraph import StateGraph, END
from typing import TypedDict, List, Dict, Any
import asyncio

class TeachingState(TypedDict):
    student_cognition: Dict          # 学生认知状态（来自追踪引擎）
    proposed_strategies: List[Dict]  # 多个智能体提出的教学策略
    selected_strategy: Dict          # 最终选定的策略
    execution_result: Dict           # 执行结果
    reflection: Dict                 # 反思总结
    learning_history: List[Dict]     # 学习历史（用于反思）

class DynamicMultiAgentSystem:
    """
    动态多智能体协同教学系统
    
    核心创新:
    1. 竞争机制 - 多个智能体提出策略，择优采用
    2. 协商机制 - 智能体之间就方案进行协商
    3. 反思能力 - 从教学效果中学习
    4. 动态角色 - 根据场景切换角色
    """
    
    def __init__(self):
        # 只有3个智能体，但每个都有明确的差异化能力
        self.concept_agent = ConceptAgent()      # 概念讲解专家
        self.practice_agent = PracticeAgent()    # 实践引导专家
        self.meta_agent = MetaAgent()            # 元认知监控专家
        
        # 共享记忆（智能体间共享）
        self.shared_memory = SharedMemory()
        
        # 竞争评分器
        self.strategy_evaluator = StrategyEvaluator()
    
    async def teach(self, student_cognition: Dict) -> Dict:
        """
        动态协同教学流程
        
        核心创新：竞争 → 协商 → 执行 → 反思
        """
        
        # ========== Phase 1: 竞争阶段 ==========
        # 两个专家智能体同时提出教学策略
        concept_strategy = await self.concept_agent.propose_strategy(
            student_cognition, self.shared_memory
        )
        practice_strategy = await self.practice_agent.propose_strategy(
            student_cognition, self.shared_memory
        )
        
        # ========== Phase 2: 评估与协商阶段 ==========
        # 元认知智能体评估两个策略
        evaluation = await self.meta_agent.evaluate_strategies(
            concept_strategy, practice_strategy, student_cognition
        )
        
        # 如果两个策略评分接近，进入协商
        if abs(evaluation["concept_score"] - evaluation["practice_score"]) < 0.15:
            # 智能体协商，融合各自优势
            selected_strategy = await self.negotiate(
                concept_strategy, practice_strategy, evaluation
            )
        else:
            # 直接选择更优策略
            selected_strategy = (
                concept_strategy if evaluation["concept_score"] > evaluation["practice_score"]
                else practice_strategy
            )
        
        # ========== Phase 3: 执行阶段 ==========
        execution_result = await self.execute_strategy(selected_strategy)
        
        # ========== Phase 4: 反思阶段 ==========
        reflection = await self.meta_agent.reflect(
            selected_strategy, execution_result, student_cognition
        )
        
        # 更新共享记忆（智能体从经验中学习）
        self.shared_memory.add_experience({
            "cognition": student_cognition,
            "strategy": selected_strategy,
            "result": execution_result,
            "reflection": reflection
        })
        
        return {
            "strategy": selected_strategy,
            "execution": execution_result,
            "reflection": reflection
        }
    
    async def negotiate(self, strategy_a, strategy_b, evaluation):
        """
        智能体协商机制
        
        创新点: 两个智能体各自让步，融合优势
        """
        # 概念智能体让出"实践环节"，保留"概念讲解"
        # 实践智能体让出"概念铺垫"，保留"动手实践"
        
        merged_strategy = {
            "concept_part": strategy_a["concept_explanation"],  # 概念专家负责讲解
            "practice_part": strategy_b["hands_on_practice"],   # 实践专家负责实践
            "transition": await self.meta_agent.generate_transition(
                strategy_a["concept_explanation"],
                strategy_b["hands_on_practice"]
            ),
            "rationale": "协商融合：概念讲解(概念专家) + 动手实践(实践专家)"
        }
        
        return merged_strategy


class ConceptAgent:
    """概念讲解专家智能体"""
    
    async def propose_strategy(self, cognition, memory):
        """
        提出基于概念讲解的教学策略
        
        特点:
        - 擅长抽象概念的可视化解释
        - 善于使用类比和隐喻
        - 注重知识体系的建构
        """
        similar_cases = memory.retrieve_similar(cognition)
        
        return {
            "agent": "concept_agent",
            "approach": "concept_first",
            "concept_explanation": await self.generate_concept_explanation(cognition),
            "visualization": await self.design_concept_visualization(cognition),
            "analogy": await self.find_analogy(cognition["knowledge_gaps"]),
            "estimated_effectiveness": 0.75,
            "rationale": f"基于{len(similar_cases)}个相似案例，概念先行策略适合认知负荷高的学生"
        }


class PracticeAgent:
    """实践引导专家智能体"""
    
    async def propose_strategy(self, cognition, memory):
        """
        提出基于实践引导的教学策略
        
        特点:
        - 擅长通过动手操作学习
        - 善于设计渐进式练习
        - 注重错误驱动的学习
        """
        return {
            "agent": "practice_agent",
            "approach": "practice_first",
            "hands_on_practice": await self.design_practice_task(cognition),
            "error_scenarios": await self.generate_error_scenarios(cognition),
            "scaffolding": await self.design_scaffolding(cognition),
            "estimated_effectiveness": 0.72,
            "rationale": "实践先行策略适合操作流畅度低的学生，通过错误驱动学习"
        }


class MetaAgent:
    """元认知监控专家智能体"""
    
    async def evaluate_strategies(self, strategy_a, strategy_b, cognition):
        """
        评估两个策略的适用性
        
        评估维度:
        1. 与学生认知状态的匹配度
        2. 预期学习效果
        3. 认知负荷可控性
        4. 知识缺口覆盖度
        """
        concept_score = await self.score_strategy(strategy_a, cognition)
        practice_score = await self.score_strategy(strategy_b, cognition)
        
        return {
            "concept_score": concept_score,
            "practice_score": practice_score,
            "evaluation_details": {
                "cognition_match": {...},
                "expected_effect": {...},
                "load_control": {...},
                "gap_coverage": {...}
            }
        }
    
    async def reflect(self, strategy, result, cognition):
        """
        反思教学效果，积累经验
        
        创新点: 智能体从教学结果中学习
        """
        return {
            "what_worked": await self.analyze_success_factors(strategy, result),
            "what_failed": await self.analyze_failure_factors(strategy, result),
            "improvement": await self.suggest_improvement(strategy, result),
            "confidence_update": await self.update_confidence(strategy, result)
        }
```

#### 2.3 智能体协同可视化（答辩记忆点）

```
┌─────────────────────────────────────────────────────────┐
│           多智能体动态协同过程（实时可视化）              │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Phase 1: 竞争阶段 ⚔️                                   │
│  ┌──────────────────────────────────────────────┐      │
│  │                                              │      │
│  │  🤖 概念专家          🤖 实践专家             │      │
│  │  ┌─────────┐         ┌─────────┐            │      │
│  │  │策略A    │         │策略B    │            │      │
│  │  │概念先行 │  VS     │实践先行 │            │      │
│  │  │评分:0.75│         │评分:0.72│            │      │
│  │  └────┬────┘         └────┬────┘            │      │
│  │       │                   │                  │      │
│  └───────┼───────────────────┼──────────────────┘      │
│          ↓                   ↓                          │
│  Phase 2: 评估与协商 🤝                                  │
│  ┌──────────────────────────────────────────────┐      │
│  │           🤖 元认知专家                       │      │
│  │           ┌─────────────┐                    │      │
│  │           │ 评分差异<0.15│                    │      │
│  │           │ → 启动协商   │                    │      │
│  │           └──────┬──────┘                    │      │
│  │                  ↓                            │      │
│  │     融合策略: 概念讲解+动手实践               │      │
│  └──────────────────┬───────────────────────────┘      │
│                     ↓                                   │
│  Phase 3: 执行 ▶️                                       │
│  ┌──────────────────────────────────────────────┐      │
│  │  1. 概念可视化讲解 (2min)                    │      │
│  │  2. 过渡引导 (30s)                           │      │
│  │  3. 动手实践 (5min)                          │      │
│  │  4. 错误驱动学习 (3min)                      │      │
│  └──────────────────┬───────────────────────────┘      │
│                     ↓                                   │
│  Phase 4: 反思 📝                                        │
│  ┌──────────────────────────────────────────────┐      │
│  │  ✅ 有效: 概念可视化降低了认知负荷            │      │
│  │  ❌ 不足: 实践环节时间过长                    │      │
│  │  📝 改进: 下次缩短实践环节，增加检查点        │      │
│  │  📊 置信度更新: 0.75 → 0.78                  │      │
│  └──────────────────────────────────────────────┘      │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

### 核心功能3：GraphRAG知识图谱推理（真正的大模型创新）

**不是LoRA微调，而是知识图谱引导的大模型推理**

#### 3.1 核心创新点

**传统RAG的问题**：
- 只做向量相似度检索，缺乏逻辑推理
- 检索到的知识片段之间无关联
- 无法回答需要多跳推理的复杂问题

**GraphRAG的突破**：
- ✅ **知识图谱+向量检索**融合
- ✅ **多跳推理**能力（回答复杂问题）
- ✅ **可解释的推理路径**（不是黑盒）

#### 3.2 技术架构

```python
class GraphRAGEngine:
    """
    GraphRAG: 知识图谱引导的大模型推理引擎
    
    核心创新:
    1. 融合知识图谱结构检索和向量语义检索
    2. 支持多跳逻辑推理
    3. 提供可解释的推理路径
    """
    
    def __init__(self):
        # 知识图谱存储（Neo4j）
        self.graph_store = Neo4jGraphStore()
        
        # 向量检索（Milvus）
        self.vector_store = MilvusVectorStore()
        
        # 大模型推理
        self.llm = CodeMindLLM()
        
        # 推理路径记录器
        self.reasoning_tracer = ReasoningTracer()
    
    async def answer(self, question: str, student_cognition: dict = None):
        """
        GraphRAG推理流程
        
        示例问题: "为什么快速排序在最坏情况下是O(n²)，而归并排序始终是O(n log n)？"
        
        传统RAG: 只能检索到"快排最坏O(n²)"和"归并始终O(n log n)"的片段
        
        GraphRAG: 
        1. 检索知识图谱中的"快速排序"节点
        2. 沿关系边找到"时间复杂度"、"最坏情况"、"分区策略"
        3. 多跳推理: 分区不均匀 → 递归深度n → 比较次数n²
        4. 对比归并排序: 固定二分 → 递归深度log n → 比较次数n log n
        5. 生成可解释的推理路径
        """
        
        # ========== Step 1: 实体识别 ==========
        entities = await self.llm.extract_entities(question)
        # ["快速排序", "最坏情况", "O(n²)", "归并排序", "O(n log n)"]
        
        # ========== Step 2: 知识图谱检索（结构化）==========
        graph_context = await self.graph_store.multi_hop_search(
            entities, max_hops=3
        )
        """
        检索到的知识图谱子图:
        
        [快速排序] --分区策略--> [固定pivot]
                    --最坏情况--> [已排序数组]
                    --递归深度--> [O(n)]
                    --比较次数--> [O(n²)]
        
        [归并排序] --分区策略--> [二分]
                    --递归深度--> [O(log n)]
                    --比较次数--> [O(n log n)]
        """
        
        # ========== Step 3: 向量检索（语义化）==========
        vector_context = await self.vector_store.search(question, top_k=5)
        
        # ========== Step 4: 融合上下文 ==========
        fused_context = await self.fuse_context(graph_context, vector_context)
        
        # ========== Step 5: 大模型推理（知识图谱引导）==========
        answer = await self.llm.generate_with_graph(
            question=question,
            graph_context=fused_context,
            reasoning_path=True,  # 要求生成推理路径
            student_level=student_cognition.get("understanding_level", 0.5)
        )
        
        # ========== Step 6: 记录推理路径（可解释性）==========
        reasoning_path = self.reasoning_tracer.trace()
        
        return {
            "answer": answer,
            "reasoning_path": reasoning_path,  # 可解释的推理路径
            "knowledge_graph": graph_context,   # 用到的知识图谱子图
            "confidence": 0.89
        }


class KnowledgeGraphBuilder:
    """
    计算机学科知识图谱构建器
    
    规模目标:
    - 实体: 10,000+
    - 关系: 100,000+
    - 覆盖: 数据结构、算法、计算机组成、操作系统、网络
    """
    
    SCHEMA = {
        # 实体类型
        "entity_types": [
            "DataStructure",    # 数据结构（数组、链表、树、图...）
            "Algorithm",        # 算法（排序、搜索、DP...）
            "Concept",          # 概念（时间复杂度、空间复杂度...）
            "Operation",        # 操作（插入、删除、查找...）
            "Property",         # 属性（稳定性、原地排序...）
            "Application"       # 应用场景（数据库索引、路由算法...）
        ],
        
        # 关系类型
        "relation_types": [
            "is_a",             # 继承关系（红黑树 is_a 二叉搜索树）
            "has_property",     # 属性关系（快速排序 has_property 不稳定）
            "has_complexity",   # 复杂度关系（快速排序 has_complexity O(n log n)）
            "uses",             # 使用关系（哈希表 uses 哈希函数）
            "alternative_to",   # 替代关系（归并排序 alternative_to 快速排序）
            "prerequisite",     # 前置关系（学红黑树 prerequisite 学二叉树）
            "applied_in"        # 应用关系（B树 applied_in 数据库索引）
        ]
    }
    
    async def build_graph(self):
        """构建知识图谱"""
        
        # 数据结构实体
        data_structures = [
            "数组", "链表", "栈", "队列", "二叉树", "二叉搜索树",
            "AVL树", "红黑树", "B树", "B+树", "堆", "哈希表",
            "图", "有向图", "无向图", "并查集", "字典树"
        ]
        
        # 算法实体
        algorithms = [
            "冒泡排序", "选择排序", "插入排序", "快速排序", "归并排序",
            "堆排序", "桶排序", "计数排序", "基数排序",
            "二分搜索", "深度优先搜索", "广度优先搜索",
            "Dijkstra算法", "Floyd算法", "Prim算法", "Kruskal算法",
            "动态规划", "贪心算法", "回溯算法", "分支限界"
        ]
        
        # 构建实体和关系
        for ds in data_structures:
            await self.add_entity(ds, "DataStructure")
            await self.add_relations(ds)
        
        for algo in algorithms:
            await self.add_entity(algo, "Algorithm")
            await self.add_relations(algo)
```

#### 3.3 推理路径可视化（答辩记忆点）

```
┌─────────────────────────────────────────────────────────┐
│           GraphRAG 推理路径可视化                         │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ❓ 学生问题:                                            │
│  "为什么快速排序最坏是O(n²)，归并排序始终O(n log n)?"   │
│                                                         │
│  🧠 GraphRAG推理路径:                                   │
│                                                         │
│  [快速排序]                                             │
│     │                                                   │
│     ├──(分区策略)──→ [固定pivot选择]                    │
│     │                      │                            │
│     │                      ├──(最坏情况)──→ [已排序数组]│
│     │                      │                            │
│     │                      └──(导致)──→ [分区极度不均]  │
│     │                                   │               │
│     ├──(递归深度)──────────────────→ [O(n)] ←─┘         │
│     │                                                   │
│     └──(比较次数)──────────────────→ [O(n²)]            │
│                                                         │
│  VS                                                     │
│                                                         │
│  [归并排序]                                             │
│     │                                                   │
│     ├──(分区策略)──→ [固定二分]                         │
│     │                      │                            │
│     │                      └──(保证)──→ [均匀分区]      │
│     │                                   │               │
│     ├──(递归深度)──────────────────→ [O(log n)] ←─┘     │
│     │                                                   │
│     └──(比较次数)──────────────────→ [O(n log n)]       │
│                                                         │
│  💡 核心差异: 分区策略决定了递归深度，进而决定复杂度     │
│                                                         │
│  📊 置信度: 89%                                         │
│  📚 引用知识: 快速排序、归并排序、时间复杂度、分区策略   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 📐 精简技术架构

### 从5个数据库精简到2个

```
┌─────────────────────────────────────────────┐
│         CodeMind V3.0 精简架构              │
├─────────────────────────────────────────────┤
│                                             │
│  【前端】Vue 3 + D3.js                      │
│  ├─ 认知状态仪表盘                          │
│  ├─ 智能体协同可视化                        │
│  ├─ 推理路径可视化                          │
│  └─ 数据结构交互编辑器                      │
│                                             │
│  【后端】FastAPI + LangGraph                │
│  ├─ 认知状态追踪引擎                        │
│  ├─ 动态多智能体系统                        │
│  ├─ GraphRAG推理引擎                        │
│  └─ RESTful API                            │
│                                             │
│  【数据层】只有2个数据库                     │
│  ├─ PostgreSQL（业务数据+认知状态）         │
│  └─ Neo4j（知识图谱，兼具向量索引）         │
│                                             │
│  【AI层】                                   │
│  ├─ Qwen-14B（通过API调用，不自训练）       │
│  ├─ LangChain（编排工具）                   │
│  └─ Neo4j GraphRAG（知识图谱检索）          │
│                                             │
└─────────────────────────────────────────────┘
```

### 技术选型理由

| 组件 | 选择 | 理由 |
|------|------|------|
| 前端框架 | Vue 3 | 团队熟悉，生态成熟 |
| 可视化 | D3.js | 认知状态可视化必需 |
| 后端框架 | FastAPI | Python生态，适合AI |
| 智能体编排 | LangGraph | 支持动态状态图 |
| 业务数据库 | PostgreSQL | 成熟可靠，支持JSON |
| 知识图谱 | Neo4j | 原生图数据库，支持向量索引 |
| 大模型 | Qwen-14B API | 不自训练，降低成本 |
| 向量检索 | Neo4j Vector | 不额外引入Milvus |

---

## 💰 商业模式：B端切入

### 从C端订阅转向B端采购

```
【B端商业模式】

目标客户: 高校计算机学院/软件学院
采购主体: 学院/系/教研室
采购周期: 学期采购（3-6个月）
客单价: 5-10万元/校/年

【产品形态】
├─ 标准版: 5万元/年
│   ├─ 认知状态追踪（50人并发）
│   ├─ 多智能体教学
│   ├─ GraphRAG问答
│   └─ 基础数据结构库
│
├─ 专业版: 10万元/年
│   ├─ 标准版全部功能
│   ├─ 不限并发人数
│   ├─ 自定义知识图谱
│   ├─ 教学数据分析报告
│   └─ 优先技术支持
│
└─ 定制版: 20万元+
    ├─ 专业版全部功能
    ├─ 校本知识图谱定制
    ├─ 与教务系统对接
    ├─ 教师培训服务
    └─ 专属运维支持
```

### 商业可行性分析

| 维度 | 分析 |
|------|------|
| **目标市场** | 全国500+开设计算机专业的高校 |
| **渗透率假设** | 首年5%（25所），次年10%（50所） |
| **首年收入** | 25所 × 8万元 = 200万元 |
| **次年收入** | 50所 × 8万元 = 400万元 |
| **毛利率** | 70%+（软件产品特性） |
| **竞争壁垒** | 认知状态数据飞轮（越用越准） |

---

## 📅 开发计划（10周，聚焦核心）

### Phase 1: 认知状态追踪引擎 (Week 1-3)

```
Week 1: 认知状态建模
├─ Day 1-2: 文献调研（BKT、DKT模型）
├─ Day 3-4: 多维认知状态模型设计
├─ Day 5-7: 贝叶斯知识追踪算法实现

Week 2: 思维路径推断
├─ Day 1-3: HMM思维状态建模
├─ Day 4-5: 操作序列分析算法
├─ Day 6-7: 认知负荷估算算法

Week 3: 可视化与集成
├─ Day 1-3: 认知状态仪表盘前端
├─ Day 4-5: 困难预测模型训练
├─ Day 6-7: 与数据结构编辑器集成
```

### Phase 2: 动态多智能体系统 (Week 4-6)

```
Week 4: 智能体开发
├─ Day 1-2: ConceptAgent开发
├─ Day 3-4: PracticeAgent开发
├─ Day 5-7: MetaAgent开发

Week 5: 协同机制
├─ Day 1-3: 竞争机制实现
├─ Day 4-5: 协商机制实现
├─ Day 6-7: 反思机制实现

Week 6: 可视化与测试
├─ Day 1-3: 智能体协同可视化
├─ Day 4-5: 端到端流程测试
├─ Day 6-7: 性能优化
```

### Phase 3: GraphRAG知识图谱 (Week 7-8)

```
Week 7: 知识图谱构建
├─ Day 1-2: 知识图谱Schema设计
├─ Day 3-5: 数据结构/算法实体录入
├─ Day 6-7: 关系抽取与录入

Week 8: GraphRAG引擎
├─ Day 1-3: 多跳检索算法实现
├─ Day 4-5: 推理路径生成
├─ Day 6-7: 推理路径可视化
```

### Phase 4: 集成与答辩准备 (Week 9-10)

```
Week 9: 系统集成
├─ Day 1-3: 三大功能模块集成
├─ Day 4-5: 端到端测试
├─ Day 6-7: Bug修复与优化

Week 10: 答辩准备
├─ Day 1-2: 演示流程设计
├─ Day 3-4: 演示脚本编写
├─ Day 5-7: 模拟答辩与优化
```

---

## 🎯 答辩演示策略（10分钟，3个记忆点）

### 演示流程

```
【开场】(30秒)
"CodeMind智脑系统，三大核心创新：
认知追踪、动态协同、图谱推理。
我们解决了计算机教学中最核心的问题——
不知道学生'为什么'不会。"

【记忆点1: 认知状态追踪】(3分钟)
"传统系统只知道学生做错了，不知道为什么。
CodeMind能实时看到学生的认知状态——
理解程度45%，认知负荷78%偏高，
思维路径从线性到回溯到出错。
并且预测出下一步可能遇到的困难。
这是传统系统做不到的。"

【记忆点2: 动态多智能体协同】(3分钟)
"传统'多智能体'是线性流水线。
CodeMind的智能体会竞争、协商、反思。
两个专家智能体提出不同策略，
元认知智能体评估后决定协商融合，
执行后还会反思改进。
这是真正的Multi-Agent。"

【记忆点3: GraphRAG推理】(3分钟)
"传统RAG只做向量检索，无法多跳推理。
CodeMind的GraphRAG能沿知识图谱
进行多跳逻辑推理，并展示推理路径。
比如回答'为什么快排最坏O(n²)而归并始终O(n log n)'，
我们的系统能展示完整的推理链路。"

【收尾】(30秒)
"认知追踪让我们'看见'学生的思维，
动态协同让智能体'真正'合作，
图谱推理让大模型'会'逻辑推理。
这就是CodeMind的核心价值。"
```

---

## 📊 V3.0 vs V2.0 对比总结

| 维度 | V2.0 | V3.0 | 提升 |
|------|------|------|------|
| 核心创新明确性 | ❌ 不明确 | ✅ 认知追踪引擎 | ⭐⭐⭐⭐⭐ |
| 技术深度 | ⭐⭐ | ⭐⭐⭐⭐⭐ | +150% |
| 原创性 | ⭐⭐ | ⭐⭐⭐⭐ | +100% |
| 智能体真实性 | ❌ 线性流水线 | ✅ 竞争协商反思 | ⭐⭐⭐⭐⭐ |
| 大模型创新 | ❌ LoRA微调 | ✅ GraphRAG推理 | ⭐⭐⭐⭐⭐ |
| 可视化创新 | ❌ 排序动画 | ✅ 认知过程可视化 | ⭐⭐⭐⭐⭐ |
| 技术栈复杂度 | ❌ 5个数据库 | ✅ 2个数据库 | -60% |
| 商业模式可行性 | ❌ C端订阅 | ✅ B端采购 | ⭐⭐⭐⭐⭐ |
| 答辩记忆点 | ❌ 无差异 | ✅ 3个记忆点 | ⭐⭐⭐⭐⭐ |
| 开发可行性 | ⚠️ 12周紧张 | ✅ 10周可行 | ⭐⭐⭐⭐ |

---

## 💡 核心结论

### V3.0的三大核心竞争力

1. **认知状态追踪引擎** — 评委能记住的"Wow moment"
   - 传统系统只看结果，CodeMind看过程
   - 实时追踪理解程度、认知负荷、思维路径
   - 预测学习困难，提前干预

2. **动态多智能体协同** — 真正的Multi-Agent
   - 不是线性流水线，而是竞争+协商+反思
   - 3个智能体，每个有明确差异化能力
   - 从教学效果中学习，持续优化

3. **GraphRAG知识图谱推理** — 真正的大模型创新
   - 不是LoRA微调，而是知识图谱引导推理
   - 支持多跳逻辑推理
   - 提供可解释的推理路径

### V3.0的设计哲学

> **做减法**：8个功能砍到3个，每个做到极致
> **加深度**：每个功能都有明确的技术难点
> **造记忆点**：3个功能对应3个答辩记忆点
> **接地气**：B端高校采购，商业模式可落地
