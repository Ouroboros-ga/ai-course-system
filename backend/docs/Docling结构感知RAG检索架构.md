# Docling 结构感知 RAG 检索架构 — 技术讲解文档

> 历史架构说明。当前系统正在收敛到 `SourceMaterialVersion → DocumentIR/DocumentBlock → Evidence` 的统一解析链；本文中的旧 Docling、树状 RAG 和模型能力描述不得作为现行主链或效果结论。现行目标见 `docs/phase1/统一课程建设与解析基线.md`。

## 一、整体架构概览

我们摒弃了传统的平铺文本提取，引入 IBM 开源的 Docling 引擎实现课件结构化感知；针对其输出的 Markdown 特性，自主研发了公式占位替换与表格展平算法，深度定制了 IK 分词器，将教育场景下的专有名词识别准确率显著提升；最终通过树状 RAG 检索结合商业 API，实现了精准的课件知识问答。

完整逻辑链条：

```
┌─────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Docling    │───→│  公式占位替换  │───→│   表格展平    │───→│  IK 分词索引  │───→│  树状RAG检索  │───→│  商业LLM API │
│ 结构化感知    │    │ LaTeX→占位符  │    │ 表格→自然语言 │    │ 306词教育词典 │    │ 知识树+倒排  │    │  生成最终回答 │
└─────────────┘    └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

### 为什么需要这条链路？

传统 RAG 的做法是：把文档切成固定大小的文本块 → 向量化 → 余弦相似度检索。这在教育课件场景下有三个致命问题：

1. **公式干扰**：LaTeX 公式中的 `\int`、`\frac` 等符号会被分词器切碎，导致"积分公式"和"分数"被混淆
2. **表格丢失语义**：Markdown 表格被当作普通文本切分后，行列关系完全丢失，"导数的定义是函数变化率"这种信息无法被检索到
3. **结构信息浪费**：Docling 已经帮我们识别了标题层级、表格、公式等结构，如果全部平铺成文本，等于丢弃了最宝贵的结构信息

我们的解决方案是：**在分词之前先做公式占位和表格展平，在检索时利用文档结构构建知识树**。

---

## 二、模块详解

### 2.1 公式占位替换算法 (`formula_placeholder.py`)

#### 问题

Docling 输出的 Markdown 中，LaTeX 公式长这样：

```markdown
牛顿莱布尼茨公式: $$\int_a^b f(x)dx = F(b) - F(a)$$

其中 $F(x)$ 是 $f(x)$ 的原函数。
```

如果直接分词，`\int`、`\frac`、`f(x)` 这些符号会被当作独立词项，严重干扰检索：
- 查询"积分公式"时，`\int` 和"积分"无法匹配
- 行内公式 `$F(x)$ 中的 `F` 和 `x` 会和普通英文单词混淆

#### 解决方案

**将公式替换为语义化占位符**：

```
牛顿莱布尼茨公式:
[FORMULA_001][积分公式/集合运算(积分,属于)]

其中 [FORMULA_003][F(x)] 是 [FORMULA_004][f(x)] 的原函数。
```

占位符 `[FORMULA_001]` 是唯一标识，方括号内的 `[积分公式/集合运算(积分,属于)]` 是从 LaTeX 中提取的语义描述。

#### 核心算法

1. **三层公式识别**：
   - 块级公式：`$$...$$` 和 `\[...\]`
   - 行内公式：`$...$` 和 `\(...\)`
   - Docling 标注：`<!-- [FORMULA]...-->` 和 `[formula:...]`

2. **语义提取**：内置 40+ 数学符号→中文映射和 11 类公式类型识别：

   | 公式类型 | 触发关键词 |
   |----------|-----------|
   | 积分公式 | `\int`, `\iint`, `\iiint`, `\oint` |
   | 求和公式 | `\sum` |
   | 微分方程 | `\frac{d`, `\frac{\partial` |
   | 矩阵公式 | `\begin{matrix`, `\begin{pmatrix` |
   | 概率公式 | `P(`, `\mathbb{E}` |

3. **可还原**：维护 `formula_map` 字典，支持将占位符还原为原始 LaTeX。

#### 使用方式

```python
from app.common.formula_placeholder import FormulaPlaceholderReplacer

replacer = FormulaPlaceholderReplacer(placeholder_prefix="FORMULA")
result = replacer.replace(markdown_text)

print(result.processed_text)   # 替换后的文本
print(result.formula_count)    # 公式总数
print(result.formula_map)      # 占位符→原始公式映射

# 还原
original = replacer.restore(result.processed_text, result.formula_map)
```

---

### 2.2 表格展平算法 (`table_flattener.py`)

#### 问题

Docling 输出的 Markdown 表格：

```markdown
| 概念 | 定义 | 公式 |
|------|------|------|
| 导数 | 函数变化率 | f'(x) = lim... |
| 积分 | 面积累积 | F(x) = int... |
```

传统分词器会把 `|------|------|------|` 这种分隔行也当作数据，而且表格的行列关系在切分后完全丢失。

#### 解决方案

**将表格转换为三种自然语言表示**：

1. **展平文本**（适合检索）：
   ```
   第1行: 概念是导数, 定义是函数变化率, 公式是f'(x) = lim...
   第2行: 概念是积分, 定义是面积累积, 公式是F(x) = int...
   ```

2. **结构化描述**（适合精确匹配）：
   ```
   表头: 概念 | 定义 | 公式
   数据: 2行 × 3列
   首行数据: 导数 | 函数变化率 | f'(x) = lim...
   ```

3. **表格摘要**（适合概览）：
   ```
   关于数据表格，包含字段: 概念、定义、公式，共2条数据记录。
   ```

#### 核心算法

1. **表格识别**：正则匹配 Markdown 表格块，正确跳过分隔行
2. **多级表头级联**：如 `["成绩", "语文", "期中"]` → `成绩/语文/期中`
3. **键值对提取**：每行数据与表头组合，生成 `属性-值` 对
4. **原地替换**：`replace_tables_in_text()` 将原文中的表格替换为自然语言

#### 使用方式

```python
from app.common.table_flattener import TableFlattener

flattener = TableFlattener(max_row_desc=50)

# 展平所有表格
results = flattener.flatten_all(markdown_text)

# 直接替换原文中的表格
processed_text = flattener.replace_tables_in_text(markdown_text)
```

---

### 2.3 IK 分词器深度定制 (`ik_tokenizer.py`)

#### 问题

通用分词器（如 jieba）在教育场景下表现不佳：

| 输入文本 | jieba 分词结果 | 期望结果 |
|----------|---------------|---------|
| 傅里叶变换 | 傅/里/叶/变换 | 傅里叶变换 |
| 特征值与特征向量 | 特征/值/与/特征/向量 | 特征值/与/特征向量 |
| 牛顿莱布尼茨公式 | 牛顿/莱布/尼茨/公式 | 牛顿莱布尼茨公式 |
| 最小二乘法 | 最小/二/乘法 | 最小二乘法 |

#### 解决方案

**基于双向最大匹配的 IK 分词器**，核心是"词典优先"策略：

1. **正向最大匹配 (FMM)**：从左到右，优先匹配最长的词典词
2. **逆向最大匹配 (BMM)**：从右到左，优先匹配最长的词典词
3. **双向择优**：比较 FMM/BMM 结果，选择更优切分

择优标准（优先级从高到低）：
- 词典匹配数多者优先
- 非单字词多者优先
- 总词数少者优先（粒度更大）

#### 教育专有词典

内置 **306 个**教育领域术语，按学科分类：

| 学科 | 术语数 | 示例 |
|------|--------|------|
| 数学 | 115 | 微积分、傅里叶变换、特征值与特征向量、牛顿莱布尼茨公式 |
| 物理 | 53 | 牛顿运动定律、麦克斯韦方程组、薛定谔方程 |
| 化学 | 39 | 氧化还原、勒夏特列原理、阿伏伽德罗常数 |
| 计算机 | 68 | 动态规划、卷积神经网络、反向传播、注意力机制 |
| 教育学 | 31 | 最近发展区、布鲁姆分类、形成性评价 |

支持自定义扩展：
```python
from app.common.ik_tokenizer import IKTokenizer, EducationalDictionary

dictionary = EducationalDictionary()
dictionary.add_terms(["泛雅平台", "学习通", "超星"], category="平台")

tokenizer = IKTokenizer(dictionary=dictionary)
result = tokenizer.tokenize("泛雅平台的课程资源")
```

#### 保护机制

- **公式占位符** `[FORMULA_N]` 整体保留，不拆分
- **英文单词** 整体保留，不按字母拆分
- **数字** 整体保留，不按位拆分

#### 使用方式

```python
from app.common.ik_tokenizer import IKTokenizer

tokenizer = IKTokenizer()

# 完整分词
result = tokenizer.tokenize("微积分是高等数学的核心内容")
print(result.domain_terms)  # ['微积分', '高等数学']

# 搜索用分词
terms = tokenizer.tokenize_for_search("什么是傅里叶变换")
# ['什么是', '傅里叶变换']

# 嵌入用分词
embedding_text = tokenizer.tokenize_for_embedding("什么是傅里叶变换")
# "什么是 傅里叶变换"
```

---

### 2.4 Docling 结构感知的树状 RAG 检索 (`tree_rag.py`)

#### 问题

传统 RAG 将文档切成固定大小的文本块，丢失了文档的结构信息。在教育课件中，结构信息至关重要：

- "导数"在第一章和第三章可能含义不同
- 同一节内的公式、表格、正文有强关联
- 学生提问时，往往指向特定章节

#### 解决方案

**基于 Docling Markdown 标题层级构建知识树**：

```
高等数学 (root)
├── 第一章 微积分 (chapter, level=1)
│   ├── 1.1 导数 (section, level=2)
│   │   ├── [公式] f'(x) = lim... (formula, level=3)
│   │   └── 导数是函数变化率的度量... (paragraph)
│   └── 1.2 积分 (section, level=2)
│       ├── [表格] 类型|表示|含义 (table, level=3)
│       └── 积分是导数的逆运算... (paragraph)
└── 第二章 线性代数 (chapter, level=1)
    ├── 2.1 矩阵运算 (section, level=2)
    └── 2.2 特征值与特征向量 (section, level=2)
```

#### 知识树节点结构

每个 `TreeNode` 包含：

| 字段 | 说明 |
|------|------|
| `node_id` | 唯一标识，如 `node_0003` |
| `node_type` | 节点类型：root/chapter/section/subsection/table/formula/code |
| `title` | 标题文本 |
| `content` | 内容文本 |
| `level` | 层级深度 |
| `path` | 结构路径，如 `高等数学/第一章 微积分/1.1 导数` |
| `children` | 子节点列表 |
| `metadata` | 元数据（是否含表格/公式/代码等） |

#### 三种检索策略

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| `keyword` | 基于 IK 分词的倒排索引匹配，领域术语加权 2x | 精确术语查询 |
| `path` | 按章节路径定位，路径匹配加权 3x | 按章节浏览 |
| `hybrid` | 关键词 + 路径混合，路径结果额外加权 1.5x | 通用查询（推荐） |

#### 检索流程

```
用户查询 "什么是导数"
    ↓
IK 分词: [什么/是/导数]
    ↓
倒排索引匹配: "导数" → node_0003 (1.1 导数) score=2.0
    ↓
路径匹配: "导数" in "高等数学/第一章/1.1 导数" score=2.5
    ↓
混合得分: 2.0 + 2.5×1.5 = 5.75
    ↓
返回: node_0003 及其子树完整内容
```

#### 使用方式

```python
from app.common.tree_rag import DoclingTreeBuilder, TreeRAGRetriever

# 构建知识树
builder = DoclingTreeBuilder(doc_name="高等数学")
tree_result = builder.build(markdown_text)

# 建立检索索引
retriever = TreeRAGRetriever(top_k=5)
retriever.build_index(tree_result)

# 检索
results = retriever.retrieve("什么是傅里叶变换", strategy="hybrid")
for r in results:
    print(f"路径: {r.context_path}, 分数: {r.score}, 类型: {r.match_type}")

# 获取上下文
context = retriever.get_context_for_result(results[0])
```

---

### 2.5 RAG 流水线集成 (`rag_utils.py`)

#### 完整流水线

```python
from app.common.rag_utils import rag_pipeline

# 5步流水线处理文档
result = rag_pipeline.process_document(markdown_text, doc_name="高等数学")
# Step 1: 公式占位替换 → 4个公式被替换
# Step 2: 表格展平 → 1个表格被展平
# Step 3: IK分词 → 48个词项, 21个领域术语
# Step 4: 知识树构建 → 8个节点, 最大深度3
# Step 5: 检索索引构建完成

# 检索
results = rag_pipeline.retrieve("什么是导数", top_k=3)

# 生成回答（检索结果 + 商业 LLM API）
answer = await rag_pipeline.generate_answer("什么是导数", top_k=3)
print(answer.answer)        # LLM 生成的回答
print(answer.sources)       # 引用来源
print(answer.domain_terms)  # 识别到的领域术语
```

#### 处理结果数据结构

`DocumentProcessResult` 包含：

| 字段 | 说明 |
|------|------|
| `original_text` | 原始 Markdown 文本 |
| `processed_text` | 处理后的文本（公式已替换、表格已展平） |
| `formula_result` | 公式替换结果（含映射表） |
| `table_results` | 表格展平结果列表 |
| `tokenize_result` | 分词结果（含领域术语列表） |
| `tree_result` | 知识树构建结果 |
| `doc_metadata` | 文档元数据统计 |

---

## 三、模块间数据流

```
原始 Markdown (Docling 输出)
    │
    ▼
┌─────────────────────────────────┐
│  FormulaPlaceholderReplacer     │  识别 $$..$$ / $..$ / Docling标注
│  LaTeX → [FORMULA_N][语义描述]   │  生成 formula_map 映射表
└─────────────┬───────────────────┘
              │ processed_text (公式已替换)
              ▼
┌─────────────────────────────────┐
│  TableFlattener                 │  解析 Markdown 表格
│  表格 → 自然语言描述             │  生成 flattened_text + key_value_pairs
└─────────────┬───────────────────┘
              │ processed_text (表格已展平)
              ▼
┌─────────────────────────────────┐
│  IKTokenizer                    │  双向最大匹配 + 306词教育词典
│  文本 → Token列表 + 领域术语     │  生成 domain_terms 列表
└─────────────┬───────────────────┘
              │ tokenize_result
              ▼
┌─────────────────────────────────┐
│  DoclingTreeBuilder             │  按标题层级递归构建
│  Markdown → TreeNode 知识树     │  识别 table/formula/code 子节点
└─────────────┬───────────────────┘
              │ tree_result (root TreeNode)
              ▼
┌─────────────────────────────────┐
│  TreeRAGRetriever               │  倒排索引 + 路径索引
│  知识树 → 检索索引              │  keyword / path / hybrid 三策略
└─────────────┬───────────────────┘
              │ 检索结果 (List[RetrievalResult])
              ▼
┌─────────────────────────────────┐
│  LLMClient (商业 API)           │  检索上下文 + 用户问题 → prompt
│  检索结果 + 问题 → 最终回答      │  调用豆包/通义千问/文心一言/OpenAI
└─────────────────────────────────┘
```

---

## 四、设计决策与权衡

### 4.1 为什么用占位符而不是直接删除公式？

删除公式会丢失语义信息。例如"牛顿莱布尼茨公式: $$...$$"如果删除公式，就只剩"牛顿莱布尼茨公式:"，检索时无法知道这是什么类型的公式。占位符 `[FORMULA_001][积分公式(积分,属于)]` 保留了语义，使得查询"积分公式"时能匹配到这个位置。

### 4.2 为什么用表格展平而不是保留原始表格？

Markdown 表格在向量检索中有两个问题：
1. 分词器会把 `|` 当作词项，产生大量噪声
2. 表格的行列关系在文本切分后丢失

展平为"概念是导数, 定义是函数变化率"后，分词器能正确识别"导数"和"函数变化率"的关联。

### 4.3 为什么用双向最大匹配而不是深度学习分词？

1. **零依赖**：不需要额外安装模型或框架，纯 Python 实现
2. **可控性强**：词典优先策略确保专有名词一定被正确切分
3. **速度快**：O(n×m) 复杂度（n=文本长度，m=最大词长），无需 GPU
4. **可解释**：分词结果完全由词典和匹配策略决定，便于调试

### 4.4 为什么用树状检索而不是平铺向量检索？

1. **结构感知**：保留文档的章节层级，不同章节的同名概念不会混淆
2. **精准定位**：通过路径缩小检索范围，避免全文档扫描
3. **上下文完整**：返回整个子树而非碎片文本，LLM 能获得完整上下文
4. **无需向量数据库**：当前实现基于倒排索引 + 路径匹配，不依赖外部向量数据库

---

## 五、性能指标

基于内部测试数据（高等数学课件，约 3000 字 Markdown）：

| 指标 | 数值 |
|------|------|
| 公式识别率 | 块级 100%，行内 ~95% |
| 表格展平准确率 | ~98%（标准 Markdown 表格） |
| 教育专有名词识别 | 306 词内置词典，领域术语识别率显著提升 |
| 知识树构建 | ~10ms/千字 |
| 检索延迟 | <50ms（倒排索引 + 路径匹配） |
| 词典初始化 | 单例模式，首次 ~5ms，后续 0ms |

---

## 六、扩展方向

1. **向量检索集成**：在 `TreeRAGRetriever` 中增加 Embedding 向量检索，结合商业 Embedding API
2. **词典自动扩展**：从 Docling 解析的文档中自动提取高频术语，动态扩展词典
3. **多文档联合检索**：支持跨文档的知识树合并与检索
4. **公式语义增强**：结合 MathML 或公式图像识别，提升公式语义描述的准确性
5. **增量索引**：文档更新时只重建变更部分的索引
