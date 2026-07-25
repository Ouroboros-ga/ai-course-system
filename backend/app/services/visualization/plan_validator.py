"""G4 VisualizationPlan 验证服务

验证 LLM/教师生成的 VisualizationPlan：
1. 算法标识必须在白名单内
2. 参数必须在允许范围内
3. 步骤类型必须合法
4. 课程和知识点必须关联
5. 不允许任意 JS/HTML

LLM 只能输出此受限 JSON 契约，不能执行任意前端代码。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.visualization.algorithm_registry import (
    ALGORITHM_WHITELIST,
    AlgorithmSpec,
    get_algorithm_spec,
    validate_param,
)

VISUALIZATION_PLAN_VERSION = "viz-plan-v1.0"
MAX_STEPS = 200
MAX_PLAN_CHARS = 200_000
MAX_PLAYBACK_SPEED = 5.0
MIN_PLAYBACK_SPEED = 0.1


@dataclass
class ValidationResult:
    """验证结果"""
    valid: bool
    errors: list[str]
    algorithm_spec: AlgorithmSpec | None = None
    sanitized_plan: dict[str, Any] | None = None


def validate_visualization_plan(plan: dict[str, Any]) -> ValidationResult:
    """验证 VisualizationPlan JSON

    确保计划只包含白名单算法、合法参数和受控步骤类型。
    任何不在契约中的字段或超范围值都会被拒绝。
    """
    errors: list[str] = []
    if len(repr(plan)) > MAX_PLAN_CHARS:
        return ValidationResult(valid=False, errors=["VisualizationPlan 体积超过上限"])

    # 1. 验证 algorithm_id
    algorithm_id = plan.get("algorithm_id")
    if not algorithm_id or not isinstance(algorithm_id, str):
        errors.append("algorithm_id 缺失或非字符串")
        return ValidationResult(valid=False, errors=errors)

    spec = get_algorithm_spec(algorithm_id)
    if spec is None:
        errors.append(f"算法 '{algorithm_id}' 不在白名单中")
        return ValidationResult(valid=False, errors=errors)

    # 2. 验证 initial_params
    initial_params = plan.get("initial_params", {})
    if not isinstance(initial_params, dict):
        errors.append("initial_params 必须是对象")
        return ValidationResult(valid=False, errors=errors)

    for param_spec in spec.params:
        value = initial_params.get(param_spec.name)
        ok, msg = validate_param(param_spec, value)
        if not ok:
            errors.append(msg)

    # 拒绝未声明的参数
    allowed_param_names = {p.name for p in spec.params}
    for key in initial_params:
        if key not in allowed_param_names:
            errors.append(f"未声明的参数 '{key}'（算法 '{algorithm_id}' 不支持）")

    # 3. 验证 steps
    steps = plan.get("steps", [])
    if not isinstance(steps, list):
        errors.append("steps 必须是数组")
        steps = []
    if len(steps) > MAX_STEPS:
        errors.append(f"步骤数 {len(steps)} 超过上限 {MAX_STEPS}")

    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"步骤 {i} 必须是对象")
            continue
        step_type = step.get("type")
        if not step_type:
            errors.append(f"步骤 {i} 缺少 type 字段")
        elif step_type not in spec.step_types:
            errors.append(
                f"步骤 {i} 的 type '{step_type}' 不在允许列表中 "
                f"(允许: {spec.step_types})"
            )

        allowed_step_fields = {
            "type", "description", "index", "i", "j", "range",
            "value", "elements", "target", "pivot",
        }
        unknown_fields = sorted(set(step) - allowed_step_fields)
        if unknown_fields:
            errors.append(f"步骤 {i} 包含未声明字段: {', '.join(unknown_fields)}")

        array_value = initial_params.get("array")
        array_length = len(array_value) if isinstance(array_value, list) else None
        for index_field in ("index", "i", "j", "pivot"):
            index_value = step.get(index_field)
            if index_value is None:
                continue
            if not isinstance(index_value, int) or isinstance(index_value, bool):
                errors.append(f"步骤 {i} 的 {index_field} 必须是整数")
            elif array_length is not None and not (0 <= index_value < array_length):
                errors.append(f"步骤 {i} 的 {index_field} 超出数组范围")

        range_value = step.get("range")
        if range_value is not None:
            if (
                not isinstance(range_value, list)
                or len(range_value) != 2
                or any(not isinstance(v, int) or isinstance(v, bool) for v in range_value)
            ):
                errors.append(f"步骤 {i} 的 range 必须是两个整数")
            elif array_length is not None and not (
                0 <= range_value[0] <= range_value[1] < array_length
            ):
                errors.append(f"步骤 {i} 的 range 超出数组范围")

        elements = step.get("elements")
        if elements is not None and (
            not isinstance(elements, list) or len(elements) > 50
        ):
            errors.append(f"步骤 {i} 的 elements 必须是最多 50 项的数组")

        # 验证 description 不含危险内容
        desc = step.get("description", "")
        if isinstance(desc, str) and len(desc) > 500:
            errors.append(f"步骤 {i} 的 description 过长 (>500字符)")

    # 4. 验证 highlights
    highlights = plan.get("highlights", [])
    if not isinstance(highlights, list):
        errors.append("highlights 必须是数组")
        highlights = []

    for i, hl in enumerate(highlights):
        if not isinstance(hl, dict):
            errors.append(f"高亮 {i} 必须是对象")
            continue
        if not isinstance(hl.get("step"), int):
            errors.append(f"高亮 {i} 缺少有效的 step 索引")
        elif not 0 <= hl["step"] < len(steps):
            errors.append(f"高亮 {i} 的 step 索引超出范围")
        elements = hl.get("elements", [])
        if not isinstance(elements, list) or len(elements) > 50:
            errors.append(f"高亮 {i} 的 elements 必须是最多 50 项的数组")
        color = hl.get("color", "")
        if color and color not in ("yellow", "green", "red", "blue", "orange"):
            errors.append(f"高亮 {i} 的 color '{color}' 不在允许列表中")

    # 5. 验证 playback_speed
    speed = plan.get("playback_speed", 1.0)
    if not isinstance(speed, (int, float)) or isinstance(speed, bool):
        errors.append("playback_speed 必须是数字")
    elif speed < MIN_PLAYBACK_SPEED or speed > MAX_PLAYBACK_SPEED:
        errors.append(f"playback_speed {speed} 超出范围 [{MIN_PLAYBACK_SPEED}, {MAX_PLAYBACK_SPEED}]")

    # 6. 验证 return_anchor (可选)
    return_anchor = plan.get("return_anchor")
    if return_anchor is not None:
        if not isinstance(return_anchor, dict):
            errors.append("return_anchor 必须是对象")
        elif not isinstance(return_anchor.get("node_id"), int):
            errors.append("return_anchor.node_id 必须是整数")

    # 7. 验证不含任意 JS/HTML
    plan_str = str(plan)
    dangerous_patterns = ["<script", "javascript:", "eval(", "Function(", "document.", "window.", "__proto__"]
    for pattern in dangerous_patterns:
        if pattern.lower() in plan_str.lower():
            errors.append(f"计划中检测到危险内容: '{pattern}'")

    if errors:
        return ValidationResult(valid=False, errors=errors, algorithm_spec=spec)

    # 构建净化后的计划（只保留白名单字段）
    sanitized = {
        "version": VISUALIZATION_PLAN_VERSION,
        "algorithm_id": algorithm_id,
        "algorithm_name": spec.name,
        "algorithm_category": spec.category,
        "initial_params": {
            p.name: initial_params.get(p.name) for p in spec.params
        },
        "steps": [
            {
                "type": s.get("type"),
                "description": str(s.get("description", ""))[:500],
                **{
                    k: v for k, v in s.items()
                    if k in (
                        "index", "i", "j", "range", "value",
                        "elements", "target", "pivot",
                    )
                }
            }
            for s in steps if isinstance(s, dict)
        ],
        "highlights": [
            {
                "step": hl.get("step"),
                "elements": hl.get("elements", []),
                "color": hl.get("color", "yellow"),
            }
            for hl in highlights if isinstance(hl, dict)
        ],
        "playback_speed": float(speed),
    }

    if return_anchor:
        sanitized["return_anchor"] = {
            "node_id": return_anchor.get("node_id"),
            "label": str(return_anchor.get("label", ""))[:200],
        }

    return ValidationResult(
        valid=True,
        errors=[],
        algorithm_spec=spec,
        sanitized_plan=sanitized,
    )
