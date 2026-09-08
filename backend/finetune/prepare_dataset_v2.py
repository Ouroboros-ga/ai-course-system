#!/usr/bin/env python3
"""垂类 SFT 指令集 v2——8 类多任务扩展版（挑战杯 XH-202620）。

在 v1（197 条 / 3 模板）基础上扩为 7 类训练任务 + 1 类评测任务，目标 800±条：

  T1 知识点讲解（2 种问法）        ← knowledge_data 节点
  T2 图谱关系判断                 ← relations.json
  T3 解题步骤推演（演算/复杂度）   ← 节点 example + key_points
  T4 代码三件套（复杂度/解释/纠错）← 人工核校的经典代码片段（10 主题）
  T5 多轮教学对话（2 轮）         ← 节点 + 关系组合
  T6 误区澄清                     ← 人工核校的 24 条常见误区 + contrasts_with
  T7 带引用作答（RAG 风格）       ← 节点定义/要点 + source 字段
  T8 评测基准（只进 eval，防污染） ← eval_baseline.json

数据工程约束：
- 节点级 90/10 划分（seed 固定）：进入 eval 的节点在**所有**训练任务中被排除，
  严于 v1（v1 只在讲解/关系生成时随机划分）。
- 基准 10 问只进 eval（与 v1 一致，防"记忆式"对比失真）。
- 全部答案可溯源到 knowledge_data 人工整理内容或经典代码事实，无 LLM 自由生成。
- 单条 input+output ≤ 4000 字符（兼容星火 MaaS 推理集上限），输出前校验去重。

    python backend/finetune/prepare_dataset_v2.py --output-dir data
"""
from __future__ import annotations

import argparse
import glob
import json
import random
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DEFAULT_KNOWLEDGE_DIR = BASE.parent.parent / "knowledge_data"
DEFAULT_BASELINE = BASE / "eval_baseline.json"
SEED = 20260908
EVAL_NODE_RATIO = 0.1
CHAR_LIMIT = 4000


def _chat(*messages: tuple[str, str]) -> dict:
    """(role, content) 序列 → messages 格式。"""
    return {"messages": [{"role": r, "content": c} for r, c in messages]}


# ---------------------------------------------------------------- 节点/关系加载

def _load_nodes(knowledge_dir: Path) -> list[dict]:
    nodes = []
    for path in sorted(p for p in knowledge_dir.glob("*.json") if p.name != "relations.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for node in data.get("nodes", []):
            if node.get("id"):
                node["_course"] = path.stem
                nodes.append(node)
    return nodes


def _load_relations(knowledge_dir: Path) -> list[dict]:
    rel_path = knowledge_dir / "relations.json"
    if not rel_path.exists():
        return []
    return json.loads(rel_path.read_text(encoding="utf-8")).get("relations", [])


def _cite(node: dict) -> str:
    src = node.get("source") or {}
    cite = "（来源：%s" % src.get("title", "")
    if src.get("chapter"):
        cite += "，" + src["chapter"]
    return cite + "）"


# ---------------------------------------------------------------- T1 讲解

def t1_explain(node: dict, variant: int) -> dict:
    key_points = "\n".join("- " + kp for kp in node.get("key_points", []))
    answer = node.get("definition", "")
    if key_points:
        answer += "\n要点：\n" + key_points
    if node.get("example"):
        answer += "\n示例：" + node["example"]
    answer += "\n" + _cite(node)
    if variant == 0:
        q = f"请讲解计算机学科知识点「{node['name']}」：给出定义、关键要点与示例，并注明权威来源。"
    else:
        q = (f"假设你是计算机课程的助教，请面向初学者通俗地讲解「{node['name']}」，"
             "先给定义，再列关键要点，配一个例子，最后注明教材来源。")
    return _chat(("user", q), ("assistant", answer))


# ---------------------------------------------------------------- T2 关系

_REL_NOTE = {
    "defines": "定义/构成关系",
    "uses": "使用关系",
    "prerequisite_of": "先修关系",
    "contrasts_with": "对比关系",
    "related_to": "相关关系",
    "supported_by": "支撑关系",
    "derives_from": "派生关系",
    "part_of": "组成关系",
}


def t2_relation(rel: dict, names: dict[str, str]) -> dict:
    frm = names.get(rel["from"], rel["from"])
    to = names.get(rel["to"], rel["to"])
    q = f"在计算机学科知识图谱中，「{frm}」与「{to}」之间是什么关系？请解释。"
    a = f"「{frm}」与「{to}」的关系类型为 {rel['relation_type']}（{_REL_NOTE.get(rel['relation_type'], '关联')}）：{rel.get('note', '')}"
    return _chat(("user", q), ("assistant", a))


# ---------------------------------------------------------------- T3 解题推演

def t3_problem(node: dict) -> list[dict]:
    out = []
    example = node.get("example", "")
    kps = node.get("key_points", [])
    cite = _cite(node)
    # (a) 过程演算/应用题：从 example 出发
    if example:
        head = example.split("→")[0].split("：")[0].strip()
        conclusion = example.split("→")[-1].strip() if "→" in example else example.strip()
        q = (f"请运用「{node['name']}」的知识完成下面的分析或演算，写出推理过程并给出结论：\n{head}")
        a = (f"推理过程：结合 {node['name']} 的方法要点——\n"
             + "\n".join("- " + kp for kp in kps[:3])
             + f"\n结论：{conclusion}\n" + cite)
        out.append(_chat(("user", q), ("assistant", a)))
    # (b) 复杂度分析题：key_points 含复杂度记号
    complexity_kp = [kp for kp in kps if any(m in kp for m in ("O(", "O(log", "Ω", "Θ"))]
    if complexity_kp:
        q = f"请分析「{node['name']}」相关方法的时间复杂度，说明平均/最坏情况（若有区别）并给出依据。"
        a = ("分析：\n" + "\n".join("- " + kp for kp in complexity_kp)
             + f"\n结论：以教材中该知识点的复杂度结论为准。\n" + cite)
        out.append(_chat(("user", q), ("assistant", a)))
    return out


# ---------------------------------------------------------------- T4 代码三件套

# 人工核校的经典代码任务（代码事实确定，非 LLM 生成）
CODE_TASKS: dict[str, dict] = {
    "二分查找": {
        "code": "def bsearch(a, x):\n    low, high = 0, len(a) - 1\n    while low <= high:\n        mid = (low + high) // 2\n        if a[mid] == x:\n            return mid\n        elif a[mid] < x:\n            low = mid + 1\n        else:\n            high = mid - 1\n    return -1",
        "complexity": "时间 O(log n)：每轮比较后搜索区间减半；空间 O(1)。前提是数组有序。",
        "explain": "在有序数组 a 中二分查找 x：[low, high] 为当前闭区间，mid 取中点；命中返回下标，否则按大小收缩区间；未命中返回 -1。",
        "bug_code": "def bsearch(a, x):\n    low, high = 0, len(a) - 1\n    while low < high:            # BUG\n        mid = (low + high) // 2\n        if a[mid] == x:\n            return mid\n        elif a[mid] < x:\n            low = mid + 1\n        else:\n            high = mid - 1\n    return a[low] if a and a[low] == x else -1",
        "bug_fix": "循环条件应为 while low <= high：闭区间写法下 low < high 会漏掉 low == high 的单元素区间，导致区间内最后一个元素永远不被比较（例如在 [5] 中查找 5 会误判为不存在）。改为 low <= high 即可。",
    },
    "快速排序": {
        "code": "def qsort(a):\n    if len(a) <= 1:\n        return a\n    pivot, rest = a[0], a[1:]\n    left = [v for v in rest if v < pivot]\n    right = [v for v in rest if v >= pivot]\n    return qsort(left) + [pivot] + qsort(right)",
        "complexity": "平均 O(n log n)；最坏 O(n²)（如每次基准都取到极值、划分极不均衡）；递归栈平均 O(log n)，最坏 O(n)。不稳定。",
        "explain": "分治：取基准 pivot，把其余元素划分为小于/不小于两段，分别递归后与基准拼接。划分是核心步骤。",
        "bug_code": "def qsort(a):\n    if len(a) <= 1:\n        return a\n    pivot = a[0]\n    left = [v for v in a if v < pivot]\n    right = [v for v in a if v >= pivot]   # BUG\n    return qsort(left) + [pivot] + qsort(right)",
        "bug_fix": "划分时把 pivot 本身也包含进了 right（v >= pivot），且左右两侧都包含 pivot，导致基准元素永远留在子问题中无法缩小规模，等于 pivot 重复出现时会无限递归（栈溢出）。应从 rest = a[1:] 中划分，或让 right 只取 v > pivot。",
    },
    "图遍历（BFS/DFS）": {
        "code": "from collections import deque\n\ndef bfs(graph, start):\n    visited = {start}\n    queue = deque([start])\n    order = []\n    while queue:\n        u = queue.popleft()\n        order.append(u)\n        for v in graph.get(u, []):\n            if v not in visited:\n                visited.add(v)\n                queue.append(v)\n    return order",
        "complexity": "时间 O(V + E)：每个顶点入队一次、每条边访问一次；空间 O(V)（visited 与队列）。",
        "explain": "从 start 出发做广度优先遍历：队列保证按层扩展，visited 防止环图重复访问；order 即 BFS 序。",
        "bug_code": "from collections import deque\n\ndef bfs(graph, start):\n    visited = set()\n    queue = deque([start])\n    order = []\n    while queue:\n        u = queue.popleft()\n        if u in visited:\n            continue\n        visited.add(u)\n        order.append(u)\n        for v in graph.get(u, []):\n            queue.append(v)      # BUG\n    return order",
        "bug_fix": "入队前不检查 visited，会把同一节点重复入队（环图/重边下队列可能被撑到指数级），虽然结果仍正确但复杂度退化、可能内存耗尽。应在 for v 循环中加入 if v not in visited: visited.add(v) 再入队。",
    },
    "字符串匹配（KMP）": {
        "code": "def kmp_next(p):\n    nxt = [0] * len(p)\n    k = 0\n    for i in range(1, len(p)):\n        while k and p[i] != p[k]:\n            k = nxt[k - 1]\n        if p[i] == p[k]:\n            k += 1\n        nxt[i] = k\n    return nxt",
        "complexity": "构造 next 数组 O(m)；匹配阶段主串指针不回退，O(n + m)。空间 O(m)。",
        "explain": "next[i] 是 p[0..i] 的最长相等前后缀长度；失配时模式串指针 j 回退到 next[j-1]，主串指针 i 永不回退。",
        "bug_code": "def kmp_next(p):\n    nxt = [0] * len(p)\n    k = 0\n    for i in range(1, len(p)):\n        while k and p[i] != p[k]:\n            k = 0                  # BUG\n        if p[i] == p[k]:\n            k += 1\n        nxt[i] = k\n    return nxt",
        "bug_fix": "失配时应回退到 k = nxt[k - 1]（次长前后缀继续尝试），直接置 k = 0 会丢失部分匹配信息，构造出的 next 数组错误，匹配退化甚至失配处理不正确（如模式 aabaaac 的 next 会算错）。",
    },
    "动态规划": {
        "code": "def knapsack(weights, values, cap):\n    dp = [0] * (cap + 1)\n    for w, v in zip(weights, values):\n        for c in range(cap, w - 1, -1):\n            dp[c] = max(dp[c], dp[c - w] + v)\n    return dp[cap]",
        "complexity": "时间 O(n·cap)，空间 O(cap)（一维滚动数组）。每个物品只处理一次。",
        "explain": "0-1 背包：dp[c] 表示容量 c 下的最大价值；对每个物品逆序枚举容量，保证 dp[c - w] 取到的是不含当前物品的上一轮状态。",
        "bug_code": "def knapsack(weights, values, cap):\n    dp = [0] * (cap + 1)\n    for w, v in zip(weights, values):\n        for c in range(w, cap + 1):        # BUG：正序\n            dp[c] = max(dp[c], dp[c - w] + v)\n    return dp[cap]",
        "bug_fix": "一维数组写法下必须逆序枚举容量（cap → w）。正序会让 dp[c - w] 已经包含当前物品，同一物品被重复选取，0-1 背包退化成完全背包。",
    },
    "堆": {
        "code": "def sift_down(a, i, n):\n    while True:\n        l, r, largest = 2 * i + 1, 2 * i + 2, i\n        if l < n and a[l] > a[largest]:\n            largest = l\n        if r < n and a[r] > a[largest]:\n            largest = r\n        if largest == i:\n            return\n        a[i], a[largest] = a[largest], a[i]\n        i = largest",
        "complexity": "建堆 O(n)（自底向上下沉），单次插入/弹出 O(log n)。堆排序整体 O(n log n)、原地。",
        "explain": "对以 i 为根的子树做下沉（sift-down）：与左右孩子中最大者比较，若父节点已最大则停止，否则交换后继续下沉。",
        "bug_code": "def sift_down(a, i, n):\n    while True:\n        l, r, largest = 2 * i + 1, 2 * i + 2, i\n        if l < n and a[l] > a[i]:\n            largest = l\n        if r < n and a[r] > a[i]:      # BUG\n            largest = r\n        if largest == i:\n            return\n        a[i], a[largest] = a[largest], a[i]\n        i = largest",
        "bug_fix": "右孩子应与 a[largest]（左孩子胜出后的较大者）比较而不是与 a[i] 比较：当左孩子已大于父节点时，右孩子只比父节点大并不能保证它是三者最大，会把较小的右孩子换上去，破坏堆序。",
    },
    "归并排序": {
        "code": "def merge(a, b):\n    i = j = 0\n    out = []\n    while i < len(a) and j < len(b):\n        if a[i] <= b[j]:\n            out.append(a[i]); i += 1\n        else:\n            out.append(b[j]); j += 1\n    out.extend(a[i:]); out.extend(b[j:])\n    return out",
        "complexity": "时间 O(n log n)，空间 O(n)（辅助数组）。稳定排序。",
        "explain": "合并两个有序段：双指针取较小者放入结果；循环结束后把未耗尽的剩余段整体接上。",
        "bug_code": "def merge(a, b):\n    i = j = 0\n    out = []\n    while i < len(a) and j < len(b):\n        if a[i] <= b[j]:\n            out.append(a[i]); i += 1\n        else:\n            out.append(b[j]); j += 1\n    return out                              # BUG",
        "bug_fix": "合并循环结束后必须把 a[i:] 与 b[j:] 中尚未耗尽的剩余元素追加到结果末尾，否则当一段先耗尽时另一段的尾部元素全部丢失（例如 merge([1,3,5],[2]) 会返回 [1,2]，丢失 3、5）。",
    },
    "二叉搜索树": {
        "code": "class Node:\n    def __init__(self, key):\n        self.key, self.left, self.right = key, None, None\n\ndef insert(root, key):\n    if root is None:\n        return Node(key)\n    if key < root.key:\n        root.left = insert(root.left, key)\n    elif key > root.key:\n        root.right = insert(root.right, key)\n    return root",
        "complexity": "查找/插入平均 O(log n)，最坏 O(n)（退化成链）；中序遍历得升序序列。",
        "explain": "BST 插入：小于当前节点走左子树，大于走右子树，相等则忽略（不存重复键）；空位处创建新节点并挂在父节点上。",
        "bug_code": "def insert(root, key):\n    if root is None:\n        return Node(key)\n    if key < root.key:\n        insert(root.left, key)             # BUG\n    elif key > root.key:\n        insert(root.right, key)\n    return root",
        "bug_fix": "递归返回值被丢弃：必须把子调用的返回值接回 root.left / root.right。否则新建的节点没有与任何父节点相连，插入后整棵树不变（新节点成为孤儿，永远查不到）。",
    },
    "哈希表": {
        "code": "def put(table, key, value):\n    idx = hash(key) % len(table)\n    bucket = table[idx]\n    for i, (k, _) in enumerate(bucket):\n        if k == key:\n            bucket[i] = (key, value)\n            return\n    bucket.append((key, value))",
        "complexity": "平均 O(1)（按桶长度期望常数）；最坏 O(n)（全部键碰撞到同一桶）。装填因子过高需扩容（rehash）。",
        "explain": "链地址法：哈希到同一桶的键值对以链表存储；put 先线性查找同键覆盖，否则追加。",
        "bug_code": "def put(table, key, value):\n    idx = hash(key) % len(table)\n    table[idx] = (key, value)              # BUG",
        "bug_fix": "直接用槽位覆盖整个桶，发生碰撞时同桶的既有键值对被抹掉（丢失数据）。链地址法必须先在桶内查找同键覆盖、否则追加，扩容重哈希逻辑也不能省。",
    },
    "并查集": {
        "code": "def find(parent, x):\n    while parent[x] != x:\n        parent[x] = parent[parent[x]]   # 路径减半\n        x = parent[x]\n    return x\n\ndef union(parent, rank, a, b):\n    ra, rb = find(parent, a), find(parent, b)\n    if ra == rb:\n        return\n    if rank[ra] < rank[rb]:\n        ra, rb = rb, ra\n    parent[rb] = ra\n    if rank[ra] == rank[rb]:\n        rank[ra] += 1",
        "complexity": "按秩合并 + 路径压缩后，单次操作均摊 O(α(n))（反阿克曼，近似常数）。",
        "explain": "find 沿父指针找根并做路径压缩；union 先找两个根，按秩把矮树挂到高树下，等高时秩加一。",
        "bug_code": "def union(parent, rank, a, b):\n    ra, rb = find(parent, a), find(parent, b)\n    if ra == rb:\n        return\n    if rank[ra] < rank[rb]:\n        ra, rb = rb, ra\n    parent[a] = ra                           # BUG\n    if rank[ra] == rank[rb]:\n        rank[ra] += 1",
        "bug_fix": "应挂根而不是挂元素：parent[rb] = ra。写成 parent[a] = ra 只改了 a 一个节点的父指针，b 所在树的根仍是 rb，两个集合并没有真正合并，后续 find 会得到错误归属。",
    },
}


def _code_node(nodes: list[dict]) -> dict | None:
    for n in nodes:
        for key in CODE_TASKS:
            if key in n.get("name", ""):
                return n
    return None


def t4_code(nodes: list[dict], used: set[str]) -> list[dict]:
    out = []
    for n in nodes:
        name = n.get("name", "")
        task = None
        for key, spec in CODE_TASKS.items():
            if key in name and key not in used:
                task = spec
                used.add(key)
                break
        if task is None:
            continue
        cite = _cite(n)
        out.append(_chat(
            ("user", f"请分析下面这段代码的时间/空间复杂度，并说明理由：\n{task['code']}"),
            ("assistant", task["complexity"] + "\n" + f"（对应知识点「{name}」{cite}）")))
        out.append(_chat(
            ("user", f"请解释这段代码做了什么，逐步说明其核心逻辑：\n{task['code']}"),
            ("assistant", task["explain"] + "\n" + f"（对应知识点「{name}」{cite}）")))
        out.append(_chat(
            ("user", f"下面的代码有 Bug，请指出问题并给出修复方案：\n{task['bug_code']}"),
            ("assistant", task["bug_fix"] + "\n" + f"（对应知识点「{name}」{cite}）")))
    return out


# ---------------------------------------------------------------- T5 多轮对话

def t5_dialogue(node: dict, names: dict[str, str], rels_by_node: dict[str, list[dict]], variant: int) -> dict:
    kps = node.get("key_points", [])
    example = node.get("example", "")
    cite = _cite(node)
    rels = rels_by_node.get(node["id"], [])
    # 学生口吻首轮（与 T1 讲解模板区分开）
    q1 = f"老师，这节课的「{node['name']}」我没太听懂，能用通俗的方式给我讲一下吗？最好带个例子。"
    a1 = ("好的。先说定义：**" + node.get("definition", "") + "**"
          + ("\n要点：\n" + "\n".join("- " + kp for kp in kps[:3]) if kps else "")
          + (f"\n举个例子：{example}" if example else "")
          + "\n" + cite)
    follow = variant % 3
    if follow == 0 and example:
        q2 = "能针对我实际的场景再举一个例子，并说明它体现了哪些要点吗？"
        a2 = ("可以。例如：" + example
              + "\n它体现的要点：\n" + "\n".join("- " + kp for kp in kps[:2])
              + "\n" + _cite(node))
    elif follow == 1 and rels:
        rel = rels[0]
        other = names.get(rel["to"] if rel["from"] == node["id"] else rel["from"], "?")
        q2 = f"那它和「{other}」是什么关系？学习时需要注意先后顺序吗？"
        a2 = (f"在课程知识图谱中二者为 {rel['relation_type']}（{_REL_NOTE.get(rel['relation_type'], '关联')}）关系：{rel.get('note', '')}"
              + ("\n建议先掌握「" + other + "」再学本知识点。" if rel["relation_type"] == "prerequisite_of" and rel["to"] == node["id"] else ""))
    else:
        q2 = "这部分最核心、考试最容易考的要点是哪些？"
        a2 = "最核心的要点：\n" + "\n".join("- " + kp for kp in kps[:3]) + "\n" + _cite(node)
    return _chat(("user", q1), ("assistant", a1), ("user", q2), ("assistant", a2))


# ---------------------------------------------------------------- T6 误区澄清

MISCONCEPTIONS: list[tuple[str, str, str]] = [
    ("二分查找", "无序的数组也可以用二分查找来加速", "不对。二分查找的前提是序列有序；无序时二分的中点判断毫无意义，结果不可靠。应先排序（O(n log n)）或改用哈希表/线性扫描。（参考：算法导论，查找部分）"),
    ("快速排序", "快速排序在任何情况下的时间复杂度都是 O(n log n)", "不对。快排平均 O(n log n)，但最坏 O(n²)（如每次基准划分极不均衡、对有序序列固定取首元素为基准）。随机基准/三数取中可让最坏情况几乎不出现。（算法导论 第 7 章）"),
    ("归并排序", "归并排序是原地排序，不需要额外空间", "不对。归并排序合并步骤需要 O(n) 辅助数组，空间开销是它的主要代价；它的优势是稳定且时间严格 O(n log n)。（算法导论 第 2 章）"),
    ("堆", "堆中的元素是完全有序的，可以顺序取出任意位置的元素", "不对。堆只满足堆序性质（父≥子或父≤子），兄弟之间无序，也不支持高效按位置访问；只保证堆顶是极值，取任意元素需 O(n)。（数据结构教材，堆一章）"),
    ("哈希表", "哈希表的查找时间一定是 O(1)", "不准确。哈希表是平均 O(1)（期望常数），发生大量碰撞或装填因子过高时单次操作最坏退化到 O(n)；工程上靠好的哈希函数与扩容维持期望性能。（算法导论 第 11 章 散列表）"),
    ("死锁", "只要系统中出现了循环等待，就一定发生了死锁", "不对。循环等待只是死锁的必要条件之一，还须同时满足互斥、占有并等待、不可抢占；且循环等待的进程组各自等待的资源若可被外部释放，未必构成死锁。四条件缺一不可。（计算机操作系统，死锁一章）"),
    ("进程与线程", "同一进程内的线程共享该进程的全部资源", "不准确。线程共享进程的地址空间与大部分资源（堆、全局变量、打开文件），但每个线程有独立的栈、寄存器上下文和程序计数器，正是这些私有部分构成调度的基本单位。（操作系统概念 第 4 章）"),
    ("TCP", "TCP 用两次握手就足够建立连接", "不对。两次握手无法防止『失效的连接请求突然到达服务端』造成的错误连接（历史 SYN 迟到时服务端单方面建立连接并维持资源）。三次握手让双方都确认对方的收发能力。（TCP 协议 RFC 793；计算机网络教材）"),
    ("索引与查询优化", "数据库索引建得越多，查询性能一定越好", "不对。索引加速读但拖累写（每次写入要同步维护所有索引），还占存储并可能干扰优化器选择。应针对高频查询的过滤/排序列建索引，并定期评估。（数据库系统概论，索引部分）"),
    ("事务与 ACID", "事务的一致性完全由数据库系统负责保证", "不准确。原子性/持久性由日志（undo/redo）保证、隔离性由并发控制（锁/MVCC）保证，但一致性是数据库与应用共同维护的结果——应用层违反约束（如转账只扣款不入账）数据库无能为力。（数据库系统概论 第 11 章）"),
    ("图的遍历", "BFS 使用的队列决定了它一定比 DFS 慢", "不对。两者时间复杂度都是 O(V + E)，只是访问顺序与适用场景不同：最短路（无权）用 BFS，拓扑/回溯类用 DFS；快慢取决于实现与图结构，而非队列/栈本身。（算法导论 第 22 章）"),
    ("贪心算法", "只要每一步都选当前最优，贪心法总能得到全局最优解", "不对。贪心成立需要问题具备贪心选择性质与最优子结构（如活动选择、Huffman）；不满足时贪心只得到近似解，例如 0-1 背包按性价比贪心并不最优，必须用动态规划。（算法导论 第 15/16 章）"),
    ("动态规划", "动态规划就是记忆化搜索，两者完全等价", "不准确。两者思想同源（最优子结构+重叠子问题），但自底向上填表与自顶向下记忆化在实现、空间与常数上不同，且 DP 强调状态转移方程的设计，不只是『加个缓存』。（算法导论 第 15 章）"),
    ("页式存储管理", "分页管理会产生外部碎片", "不对。分页按固定页大小划分，页内未用满产生的是内部碎片；外部碎片是分段/可变分区分配的问题。这正是分页相对分段的优点之一。（计算机操作系统，存储器管理）"),
    ("二叉树", "满二叉树和完全二叉树是同一个概念", "不对。满二叉树每层都满；完全二叉树只要求除最后一层外全满、且最后一层节点靠左对齐。完全二叉树未必是满的（最下一层可缺右侧），堆结构用的正是完全二叉树。（数据结构教材，树一章）"),
    ("软件测试", "只要测试全部通过，就能证明程序没有 Bug", "不对。Dijkstra 的经典论断：测试只能证明错误存在，不能证明错误不存在。穷尽所有输入/路径通常不可行，测试通过只是置信度证据，还需代码评审、静态分析等手段。（软件工程教材，测试一章）"),
    ("编译原理", "解释型语言不经过任何翻译就直接执行", "不准确。解释型同样要先做词法/语法分析甚至字节码编译（如 CPython 生成 .pyc），只是不在运行前整体翻译为目标机器码；现代实现普遍采用『编译+解释』混合（JIT 亦是）。（编译原理教材，第 1 章）"),
    ("中断", "CPU 在处理一个中断时，不能响应任何其他中断", "不对。中断有优先级与屏蔽机制，高优先级中断可以打断低优先级处理程序（中断嵌套）；同级或低级则需等待或被屏蔽。（计算机组成原理，输入输出系统）"),
    ("机器学习", "模型在训练集上误差越低，模型就越好", "不对。训练误差低可能只是过拟合（记住了噪声），泛化误差才是评价标准；应使用验证/测试集评估，并用正则化、交叉验证控制过拟合。（机器学习（西瓜书）第 1、2 章）"),
    ("神经网络与深度学习", "深度学习不需要任何特征工程，原始数据直接扔进去就一定最好", "不准确。深度学习虽能自动学习特征表示，但数据质量、预处理、结构选择与超参仍极大影响效果；『不需要特征工程』是夸大，且小样本场景传统方法常更优。（深度学习教材 第 5 章）"),
    ("谓词逻辑", "∀x P(x) 为真时，∃x P(x) 一定为真，反之也成立", "前半句在个体域非空时成立，但 ∃x P(x) 为真不能推出 ∀x P(x) 为真（存在一个个体满足不等于全部满足）。另外个体域为空时 ∀x P(x) 空真而 ∃x P(x) 为假。（离散数学，一阶逻辑）"),
    ("SQL", "SQL 中 WHERE 子句可以用聚合函数的结果做过滤", "不对。WHERE 在分组前逐行过滤，不能引用聚合结果；对聚合结果过滤要用 HAVING（GROUP BY 之后）。执行顺序：FROM→WHERE→GROUP BY→HAVING→SELECT→ORDER BY。（数据库系统概论 第 3 章）"),
    ("时间复杂度", "嵌套循环的时间复杂度一定是 O(n²)", "不对。要看循环次数是否相互独立：外层 i 从 1 到 n、内层也执行 n 次才是 O(n²)；若内层次数随 i 递减（如 for j in range(i)），总量是 n(n+1)/2，仍记为 O(n²)，但若内层是 O(log i)（如倍增跳步），总量是 O(n log n)。（算法导论 第 3 章）"),
]


def t6_misconception(node_by_name_sub: dict[str, dict]) -> list[dict]:
    out = []
    for key, wrong, clarify in MISCONCEPTIONS:
        node = node_by_name_sub.get(key)
        if node is None:
            continue
        q = f"有人说：「{wrong}」。这种说法对吗？为什么？"
        a = clarify
        out.append(_chat(("user", q), ("assistant", a)))
    return out


# ---------------------------------------------------------------- T7 带引用作答

def t7_cited(node: dict, variant: int) -> dict:
    kps = node.get("key_points", [])
    context = f"【资料】{node.get('definition', '')}\n" + "\n".join("- " + kp for kp in kps)
    cite = _cite(node)
    if variant == 0:
        q = f"根据下面的资料回答问题，回答末尾注明资料来源。\n{context}\n\n问题：什么是「{node['name']}」？它包含哪些要点？"
        a = (f"根据资料，「{node['name']}」：{node.get('definition', '')}"
             + ("\n要点包括：" + "；".join(kps) if kps else "")
             + "\n来源：" + cite.strip("（）"))
    else:
        target = kps[0] if kps else node.get("definition", "")
        q = (f"阅读资料后回答：关于「{node['name']}」，{target.split('：')[0]}指的是什么？请依据资料作答并给出出处。\n{context}")
        a = f"依据资料：{target}\n出处：" + cite.strip("（）")
    return _chat(("user", q), ("assistant", a))


# ---------------------------------------------------------------- T9-T11 扩充任务

_COURSE_ZH = {
    "algorithms": "算法设计与复杂度分析", "arch": "计算机组成与体系结构", "compiler": "编译原理",
    "data_structures": "数据结构", "db": "数据库系统", "discrete": "离散数学",
    "graphics": "计算机图形学", "ml": "机器学习", "net": "计算机网络",
    "os": "操作系统", "se": "软件工程",
}


def t7b_judge(node: dict) -> dict:
    """判断题：说法取自 key_points 原文（保证事实正确），训练资料比对与引用习惯。"""
    kp = (node.get("key_points") or [""])[0]
    cite = _cite(node)
    q = f"请依据教材判断下面这句话是否正确，并说明出处：\n「{kp}」"
    a = ("正确。该表述与教材内容一致。"
         + (f"补充：{node.get('definition', '')}" if node.get("definition") else "")
         + "\n出处：" + cite.strip("（）"))
    return _chat(("user", q), ("assistant", a))


def t9_terminology(node: dict) -> dict | None:
    aliases = node.get("aliases") or []
    if not aliases:
        return None
    q = f"计算机学科知识点「{node['name']}」常见的英文术语（别名）有哪些？"
    a = (f"「{node['name']}」的常见英文表述：{ '、'.join(aliases) }。\n"
         f"阅读英文教材/文档时，这些术语等价使用。" + _cite(node))
    return _chat(("user", q), ("assistant", a))


def t10_locator(node: dict, names: dict[str, str], rels_by_node: dict[str, list[dict]]) -> dict:
    course = _COURSE_ZH.get(node.get("_course", ""), node.get("_course", "计算机科学"))
    prereq = [r["from"] for r in rels_by_node.get(node["id"], [])
              if r["relation_type"] == "prerequisite_of" and r["to"] == node["id"]]
    src = node.get("source") or {}
    prereq_txt = ("建议先掌握：" + "、".join("「" + names.get(p, p) + "」" for p in prereq)) if prereq \
        else "知识图谱中未标记强先修节点，按课程章节顺序学习即可"
    q = (f"我想系统学习「{node['name']}」。它属于计算机科学的哪个领域？学习前需要哪些基础？"
         "应该参考什么教材？")
    a = (f"1）领域：「{node['name']}」属于{course}。\n"
         f"2）先修：{prereq_txt}。\n"
         f"3）教材：{src.get('title', '')}{('，' + src['chapter']) if src.get('chapter') else ''}"
         f"{('（作者：' + src['authors'] + '）') if src.get('authors') else ''}。")
    return _chat(("user", q), ("assistant", a))


def t11_source(node: dict) -> dict:
    src = node.get("source") or {}
    q = f"如果要权威地学习「{node['name']}」，应该参考哪本教材的哪一部分？"
    a = (f"推荐参考：{src.get('title', '')}"
         + (f"（作者：{src['authors']}）" if src.get("authors") else "")
         + (f"，{src['chapter']}" if src.get("chapter") else "")
         + f"。该章节系统讲解「{node['name']}」的定义、要点与示例，与课程知识图谱条目一一对应。")
    return _chat(("user", q), ("assistant", a))


# ---------------------------------------------------------------- T12 课件语料问答（真实课件）

# 课程15《算法》真实上传课件（document_blocks）的核校问答，按页码索引；
# 问题与答案均人工对照课件原文编写，出处标注课件页码。
COURSEWARE_QA: list[tuple[int, str, str]] = [
    (2, "什么是连通图的生成树？它有多少条边？",
     "一个连通图的生成树是一个极小连通子图，它含有图中全部 n 个顶点和构成一棵树的 (n-1) 条边。也就是说，生成树保持图的连通性，但去掉所有构成回路的冗余边，恰好保留 n-1 条边。"),
    (5, "什么是图的最小生成树？一个图的最小生成树唯一吗？",
     "对于带权连通图 G（每条边上的权均为大于零的实数），可能存在多棵不同的生成树，每棵生成树所有边的权值之和也可能不同。其中权值之和最小的生成树称为图的最小生成树（MST）。由于可能存在多棵权值和相同的生成树，最小生成树并不一定唯一，但其权值之和唯一。"),
    (6, "对连通图如何得到生成树？对非连通图呢？",
     "连通图：仅需调用一次遍历过程（DFS 或 BFS），从图中任一顶点出发即可遍历所有顶点，遍历经过的顶点和边就产生相应的生成树。非连通图：需要多次调用遍历过程，每个连通分量各产生一棵生成树，所有连通分量的生成树合起来构成非连通图的生成森林。"),
    (7, "请描述 Prim 算法构造最小生成树的基本步骤。",
     "Prim 算法分两步：（1）初始化 U={v}，v 到其他顶点的所有边作为候选边；（2）重复以下步骤 n-1 次，把其余 n-1 个顶点逐个加入 U：从候选边中挑选权值最小的边输出，设该边在 V-U 中的顶点是 k，将 k 加入 U；然后考察当前 V-U 中的所有顶点 j，修改候选边——若边 (k, j) 的权值小于原来顶点 j 关联的候选边，则用 (k, j) 取代后者作为新的候选边。"),
    (15, "Prim 算法代码中的 INF 常量起什么作用？初始化阶段做了什么？",
     "代码中 #define INF 32767，INF 表示无穷大（∞），用于表示两顶点间暂无直接边相连的候选边权值。初始化阶段：对 i 从 0 到 g.n-1，令 lowcost[i] = g.edges[v][i]（起点 v 到各顶点的直接边权作为初始候选边权），closest[i] = v（各顶点的候选边暂时都关联起点 v）。"),
    (16, "Prim 算法主循环中，lowcost[k]=0 这条语句有什么含义？",
     "lowcost[k]=0 用于标记顶点 k 已经加入集合 U。在 Prim 的数据结构约定中，lowcost[j]=0 表示顶点 j 已进入 U；此后主循环挑选最近顶点时通过 lowcost[j]!=0 排除已在 U 中的顶点，只继续考察 V-U 中的顶点。"),
    (16, "Prim 算法每一轮迭代是如何选出要加入 U 的顶点的？",
     "每一轮在 (V-U) 中找出离 U 最近的顶点 k：置 min=INF，扫描所有顶点 j，若 lowcost[j]!=0（j 尚未加入 U）且 lowcost[j]<min，则更新 min=lowcost[j]、k=j。循环结束后 k 就是当前离 U 最近的顶点，输出边 (closest[k], k)（权 min），并通过 lowcost[k]=0 将 k 标记加入 U。"),
    (17, "Prim 算法选出新顶点 k 加入 U 之后，还需要对候选边做什么修改？",
     "需要扫描所有顶点 j（j 在 V-U 中），用新加入的 k 更新候选边：若 g.edges[k][j] < lowcost[j]（经过 k 到 j 的边比 j 原来关联的候选边更短），则更新 lowcost[j] = g.edges[k][j]，同时 closest[j] = k。这一步保证 lowcost 始终保存各顶点到 U 的最短候选边。"),
]


def t12_courseware(cw_path: Path) -> list[dict]:
    """真实课件语料问答：context=课件原文，出处标注课件页码。"""
    if not cw_path.exists():
        return []
    blocks = {b["page"]: b["text"] for b in json.loads(cw_path.read_text(encoding="utf-8"))["blocks"]}
    out = []
    for page, question, answer in COURSEWARE_QA:
        text = blocks.get(page)
        if not text:
            continue
        context = "【课件原文】\n" + text.strip()
        out.append(_chat(
            ("user", f"根据课程课件片段回答问题，并说明出自课件哪一页。\n{context}\n\n问题：{question}"),
            ("assistant", f"{answer}\n（出处：课程《算法》课件 第 {page} 页）")))
    return out


# ---------------------------------------------------------------- 主流程

def build_v2(knowledge_dir: Path, baseline: Path) -> tuple[list[dict], list[dict], dict]:
    rng = random.Random(SEED)
    nodes = _load_nodes(knowledge_dir)
    rels = _load_relations(knowledge_dir)
    names = {n["id"]: n.get("name", n["id"]) for n in nodes}
    rels_by_node: dict[str, list[dict]] = {}
    for r in rels:
        rels_by_node.setdefault(r["from"], []).append(r)
        rels_by_node.setdefault(r["to"], []).append(r)

    # 节点级划分（确定性）：eval 节点在所有训练任务中被排除
    ordered = sorted(nodes, key=lambda n: n["id"])
    rng.shuffle(ordered)
    n_eval = max(1, round(len(ordered) * EVAL_NODE_RATIO))
    eval_nodes = {n["id"] for n in ordered[:n_eval]}
    train_nodes = [n for n in nodes if n["id"] not in eval_nodes]
    train_names = {n["id"]: n.get("name", n["id"]) for n in train_nodes}

    stats: dict[str, int] = {}

    def reg(bucket: list[dict], tag: str) -> list[dict]:
        stats[tag] = len(bucket)
        return bucket

    # T1 讲解 ×2
    t1: list[dict] = []
    for i, n in enumerate(train_nodes):
        t1.append(t1_explain(n, 0))
        t1.append(t1_explain(n, 1))
    reg(t1, "T1_讲解")

    # T2 关系（两端点都在 train 节点集内）
    t2 = [t2_relation(r, train_names) for r in rels
          if r["from"] not in eval_nodes and r["to"] not in eval_nodes]
    reg(t2, "T2_关系")

    # T3 解题推演
    t3: list[dict] = []
    for n in train_nodes:
        t3.extend(t3_problem(n))
    reg(t3, "T3_解题推演")

    # T4 代码三件套（每主题只挂一次）
    t4 = t4_code(train_nodes, set())
    reg(t4, "T4_代码")

    # T5 多轮对话（每节点 1 条；偶数位节点扩为三轮）
    t5: list[dict] = []
    for i, n in enumerate(train_nodes):
        d = t5_dialogue(n, train_names, rels_by_node, i)
        if i % 2 == 0 and n.get("key_points"):
            kp = n["key_points"][-1]
            d["messages"].extend([
                {"role": "user", "content": "最后帮我划一下重点：这部分我最该记住的一句话是什么？"},
                {"role": "assistant", "content": f"记住这句就够了：「{kp}」\n" + _cite(n)},
            ])
        t5.append(d)
    reg(t5, "T5_多轮对话")

    # T6 误区澄清
    sub_map: dict[str, dict] = {}
    for key, _, _ in MISCONCEPTIONS:
        for n in train_nodes:
            if key in n.get("name", ""):
                sub_map[key] = n
                break
    t6 = t6_misconception(sub_map)
    reg(t6, "T6_误区澄清")

    # T7 带引用作答（每节点 2 种问法）
    t7: list[dict] = []
    for n in train_nodes:
        t7.append(t7_cited(n, 0))
        t7.append(t7_cited(n, 1))
    reg(t7, "T7_引用作答")

    # T7b 判断题（说法取自 key_points 原文，训练资料比对）
    t7b = [t7b_judge(n) for n in train_nodes]
    reg(t7b, "T7b_判断题")

    # T9 术语对照（有 aliases 的节点）
    t9 = [x for x in (t9_terminology(n) for n in train_nodes) if x is not None]
    reg(t9, "T9_术语对照")

    # T10 知识定位/学习路径
    t10 = [t10_locator(n, train_names, rels_by_node) for n in train_nodes]
    reg(t10, "T10_知识定位")

    # T11 出处溯源
    t11 = [t11_source(n) for n in train_nodes]
    reg(t11, "T11_出处溯源")

    # T12 课件语料问答（真实上传课件的 document_blocks，人工核校）
    t12 = t12_courseware(BASE / "data" / "rag_corpus_course15.json")
    reg(t12, "T12_课件语料")

    # T13 学科语料接地问答（LLM 生成 + 接地/主题规则过滤，来源含 OSTEP/维基/RFC）
    t13_path = BASE / "data" / "corpus_qa.jsonl"
    if t13_path.exists():
        t13 = [json.loads(l) for l in t13_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        t13 = []
    reg(t13, "T13_语料接地问答")

    train = t1 + t2 + t3 + t4 + t5 + t6 + t7 + t7b + t9 + t10 + t11 + t12 + t13

    # 评测集：eval 节点的讲解/关系/引用 + 基准 10 问（不进训练），目标 50 条
    ev: list[dict] = []
    eval_node_list = [n for n in nodes if n["id"] in eval_nodes]
    for n in eval_node_list:
        ev.append(t1_explain(n, 0))
        ev.append(t7_cited(n, 0))
    for r in rels:
        if r["from"] in eval_nodes or r["to"] in eval_nodes:
            ev.append(t2_relation(r, names))
    if baseline.exists():
        for case in json.loads(baseline.read_text(encoding="utf-8")).get("cases", []):
            ev.append(_chat(("user", case["question"]),
                            ("assistant", "标准答案：" + case["expected"] + "（来源：" + case["source"]["title"] + "）")))
    stats["EVAL_基准"] = 10

    return train, ev, stats


def _validate(train: list[dict], ev: list[dict]) -> list[str]:
    issues = []
    seen = set()
    dup = 0
    for r in train + ev:
        q = r["messages"][0]["content"]
        if q in seen:
            dup += 1
        seen.add(q)
        total = sum(len(m["content"]) for m in r["messages"])
        if total > CHAR_LIMIT:
            issues.append(f"超长 {total} 字符: {q[:40]}...")
    if dup:
        issues.append(f"重复问题 {dup} 条")
    train_text = json.dumps(train, ensure_ascii=False)
    baseline = json.loads((DEFAULT_BASELINE).read_text(encoding="utf-8"))["cases"]
    leak = [c["id"] for c in baseline if c["question"] in train_text]
    if leak:
        issues.append(f"基准泄漏进训练集: {leak}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="生成垂类 SFT 指令集 v2（8 类多任务）")
    parser.add_argument("--knowledge-dir", type=Path, default=DEFAULT_KNOWLEDGE_DIR)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--output-dir", type=Path, default=BASE / "data")
    args = parser.parse_args()

    train, ev, stats = build_v2(args.knowledge_dir, args.baseline)
    rng = random.Random(SEED)
    rng.shuffle(train)

    issues = _validate(train, ev)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, samples in (("instruction_train_v2.jsonl", train), ("instruction_eval_v2.jsonl", ev)):
        with (args.output_dir / name).open("w", encoding="utf-8") as fh:
            for s in samples:
                fh.write(json.dumps(s, ensure_ascii=False) + "\n")

    print(f"[OK] 训练集 v2 {len(train)} 条 → data/instruction_train_v2.jsonl")
    for k in sorted(stats):
        print(f"     {k}: {stats[k]}")
    print(f"[OK] 评测集 v2 {len(ev)} 条 → data/instruction_eval_v2.jsonl（含基准 10 问）")
    if issues:
        print("[WARN] 校验问题：")
        for msg in issues[:10]:
            print("  -", msg)
    else:
        print("[OK] 校验通过：无重复、无超长（≤4000）、基准 0 泄漏")
    return 0


if __name__ == "__main__":
    sys.exit(main())
