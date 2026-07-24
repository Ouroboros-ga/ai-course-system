"""G4 算法可视化白名单注册表

首批支持：二分、排序、栈、队列、递归、树/图遍历。
每个算法定义允许的参数类型和范围，以及允许的步骤动作类型。
LLM 只能输出此白名单内的 VisualizationPlan JSON，不能输出任意 JS/HTML。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AlgorithmParamSpec:
    """算法参数规格"""
    name: str
    param_type: str  # "int_array" | "int" | "string" | "string_array" | "tree" | "graph"
    min_length: int = 0
    max_length: int = 20
    min_value: int = -1000
    max_value: int = 1000
    required: bool = True


@dataclass(frozen=True)
class AlgorithmSpec:
    """算法规格定义"""
    algorithm_id: str
    name: str
    category: str  # "binary" | "sorting" | "stack" | "queue" | "recursion" | "tree" | "graph"
    params: list[AlgorithmParamSpec]
    step_types: list[str]
    description: str = ""


# ==================== 算法白名单 ====================

ALGORITHM_WHITELIST: dict[str, AlgorithmSpec] = {
    # ---- 二分查找 ----
    "binary_search": AlgorithmSpec(
        algorithm_id="binary_search",
        name="二分查找",
        category="binary",
        params=[
            AlgorithmParamSpec("array", "int_array", min_length=1, max_length=30),
            AlgorithmParamSpec("target", "int", min_value=-1000, max_value=1000),
        ],
        step_types=["compare", "narrow_left", "narrow_right", "found", "not_found"],
        description="在有序数组中二分查找目标值",
    ),

    # ---- 排序算法 ----
    "bubble_sort": AlgorithmSpec(
        algorithm_id="bubble_sort",
        name="冒泡排序",
        category="sorting",
        params=[
            AlgorithmParamSpec("array", "int_array", min_length=2, max_length=20),
        ],
        step_types=["compare", "swap", "mark_sorted", "pass_complete"],
        description="冒泡排序过程演示",
    ),
    "selection_sort": AlgorithmSpec(
        algorithm_id="selection_sort",
        name="选择排序",
        category="sorting",
        params=[
            AlgorithmParamSpec("array", "int_array", min_length=2, max_length=20),
        ],
        step_types=["find_min", "swap", "mark_sorted"],
        description="选择排序过程演示",
    ),
    "insertion_sort": AlgorithmSpec(
        algorithm_id="insertion_sort",
        name="插入排序",
        category="sorting",
        params=[
            AlgorithmParamSpec("array", "int_array", min_length=2, max_length=20),
        ],
        step_types=["pick", "shift", "insert", "mark_sorted"],
        description="插入排序过程演示",
    ),
    "quick_sort": AlgorithmSpec(
        algorithm_id="quick_sort",
        name="快速排序",
        category="sorting",
        params=[
            AlgorithmParamSpec("array", "int_array", min_length=2, max_length=20),
        ],
        step_types=["pivot", "partition_compare", "partition_swap", "partition_done", "merge"],
        description="快速排序过程演示",
    ),

    # ---- 栈操作 ----
    "stack_operations": AlgorithmSpec(
        algorithm_id="stack_operations",
        name="栈操作",
        category="stack",
        params=[
            AlgorithmParamSpec("operations", "string_array", min_length=1, max_length=20),
        ],
        step_types=["push", "pop", "peek", "empty", "full"],
        description="栈的入栈、出栈操作演示",
    ),

    # ---- 队列操作 ----
    "queue_operations": AlgorithmSpec(
        algorithm_id="queue_operations",
        name="队列操作",
        category="queue",
        params=[
            AlgorithmParamSpec("operations", "string_array", min_length=1, max_length=20),
        ],
        step_types=["enqueue", "dequeue", "front", "rear", "empty"],
        description="队列入队、出队操作演示",
    ),

    # ---- 递归 ----
    "factorial_recursion": AlgorithmSpec(
        algorithm_id="factorial_recursion",
        name="阶乘递归",
        category="recursion",
        params=[
            AlgorithmParamSpec("n", "int", min_value=1, max_value=12),
        ],
        step_types=["call", "base_case", "return", "multiply"],
        description="阶乘递归调用栈演示",
    ),
    "fibonacci_recursion": AlgorithmSpec(
        algorithm_id="fibonacci_recursion",
        name="斐波那契递归",
        category="recursion",
        params=[
            AlgorithmParamSpec("n", "int", min_value=1, max_value=15),
        ],
        step_types=["call", "base_case", "return", "add"],
        description="斐波那契递归调用树演示",
    ),

    # ---- 树遍历 ----
    "tree_traversal": AlgorithmSpec(
        algorithm_id="tree_traversal",
        name="树遍历",
        category="tree",
        params=[
            AlgorithmParamSpec("tree", "tree", min_length=1, max_length=31),
            AlgorithmParamSpec("mode", "string", min_length=3, max_length=10),
        ],
        step_types=["visit", "go_left", "go_right", "backtrack", "push_stack", "pop_stack"],
        description="二叉树前序/中序/后序/层序遍历演示",
    ),

    # ---- 图遍历 ----
    "graph_bfs": AlgorithmSpec(
        algorithm_id="graph_bfs",
        name="广度优先搜索",
        category="graph",
        params=[
            AlgorithmParamSpec("graph", "graph", min_length=1, max_length=15),
            AlgorithmParamSpec("start", "int", min_value=0, max_value=14),
        ],
        step_types=["visit", "enqueue", "dequeue", "discover", "mark_visited"],
        description="图广度优先搜索演示",
    ),
    "graph_dfs": AlgorithmSpec(
        algorithm_id="graph_dfs",
        name="深度优先搜索",
        category="graph",
        params=[
            AlgorithmParamSpec("graph", "graph", min_length=1, max_length=15),
            AlgorithmParamSpec("start", "int", min_value=0, max_value=14),
        ],
        step_types=["visit", "push_stack", "pop_stack", "discover", "backtrack", "mark_visited"],
        description="图深度优先搜索演示",
    ),
}


def get_algorithm_spec(algorithm_id: str) -> AlgorithmSpec | None:
    """获取算法规格"""
    return ALGORITHM_WHITELIST.get(algorithm_id)


def list_allowed_algorithms() -> list[dict[str, Any]]:
    """列出所有允许的算法"""
    return [
        {
            "algorithm_id": spec.algorithm_id,
            "name": spec.name,
            "category": spec.category,
            "description": spec.description,
            "params": [
                {
                    "name": p.name,
                    "type": p.param_type,
                    "min_length": p.min_length,
                    "max_length": p.max_length,
                    "min_value": p.min_value,
                    "max_value": p.max_value,
                    "required": p.required,
                }
                for p in spec.params
            ],
            "step_types": spec.step_types,
        }
        for spec in ALGORITHM_WHITELIST.values()
    ]


def validate_param(spec: AlgorithmParamSpec, value: Any) -> tuple[bool, str]:
    """验证单个参数值是否在允许范围内"""
    if value is None:
        if spec.required:
            return False, f"参数 '{spec.name}' 是必填项"
        return True, ""

    if spec.param_type == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            return False, f"参数 '{spec.name}' 必须是整数"
        if value < spec.min_value or value > spec.max_value:
            return False, f"参数 '{spec.name}' 超出范围 [{spec.min_value}, {spec.max_value}]"
        return True, ""

    if spec.param_type == "string":
        if not isinstance(value, str):
            return False, f"参数 '{spec.name}' 必须是字符串"
        if len(value) < spec.min_length or len(value) > spec.max_length:
            return False, f"参数 '{spec.name}' 长度超出范围 [{spec.min_length}, {spec.max_length}]"
        return True, ""

    if spec.param_type == "int_array":
        if not isinstance(value, list):
            return False, f"参数 '{spec.name}' 必须是数组"
        if len(value) < spec.min_length or len(value) > spec.max_length:
            return False, f"参数 '{spec.name}' 长度超出范围 [{spec.min_length}, {spec.max_length}]"
        for v in value:
            if not isinstance(v, int) or isinstance(v, bool):
                return False, f"参数 '{spec.name}' 的所有元素必须是整数"
            if v < spec.min_value or v > spec.max_value:
                return False, f"参数 '{spec.name}' 的元素 {v} 超出范围 [{spec.min_value}, {spec.max_value}]"
        return True, ""

    if spec.param_type == "string_array":
        if not isinstance(value, list):
            return False, f"参数 '{spec.name}' 必须是数组"
        if len(value) < spec.min_length or len(value) > spec.max_length:
            return False, f"参数 '{spec.name}' 长度超出范围 [{spec.min_length}, {spec.max_length}]"
        for v in value:
            if not isinstance(v, str):
                return False, f"参数 '{spec.name}' 的所有元素必须是字符串"
        return True, ""

    if spec.param_type == "tree":
        if not isinstance(value, list):
            return False, f"参数 '{spec.name}' 必须是层序数组(可含null)"
        if len(value) < spec.min_length or len(value) > spec.max_length:
            return False, f"参数 '{spec.name}' 长度超出范围 [{spec.min_length}, {spec.max_length}]"
        return True, ""

    if spec.param_type == "graph":
        if not isinstance(value, dict):
            return False, f"参数 '{spec.name}' 必须是邻接表字典"
        if len(value) < spec.min_length or len(value) > spec.max_length:
            return False, f"参数 '{spec.name}' 节点数超出范围 [{spec.min_length}, {spec.max_length}]"
        return True, ""

    return False, f"未知参数类型: {spec.param_type}"
