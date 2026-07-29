"""
安全审计脚本：检测已知安全漏洞是否已修复。

每项检查返回 pass/fail，并输出汇总报告。
可独立运行：python backend/scripts/security_audit.py

检查项：
  1. llm_client.py 是否还有 WenxinClient 引用（P0-1）
  2. deploy/judge0/docker-compose.yml 是否还有 privileged 字段（P0-2）
  3. deploy/docker-compose.yml 是否还有硬编码密码 codemind_dev_2026
  4. experiments.py 的 HintRequest 是否还有客户端可控的 full_solution_allowed
  5. workflows/teaching.py 的 validate_response 是否还允许无 evidence_id 的 citation
  6. tool_governance.py 的 is_tool_enabled 是否还 fail-open
  7. agent_governance_service.py 的 decide_proposal 是否用了 with_for_update
  8. course_build_editor.py 的 bypass_lock 路径是否要求 course.publish 权限（P1-B1）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from dataclasses import dataclass


# 路径解析：backend/scripts/security_audit.py
# backend_dir = scripts 的父目录；project_root = backend 的父目录
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str

    def format(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return f"  [{status}] {self.name}\n         {self.detail}"


def _read_file(path: Path) -> str:
    """读取文件内容，返回空字符串表示文件不存在。"""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except Exception as exc:
        return f"__READ_ERROR__: {exc}"


# ---------------------------------------------------------------------------
# 检查项 1：llm_client.py 是否还有 WenxinClient 引用（P0-1）
# ---------------------------------------------------------------------------

def check_no_wenxin_client() -> CheckResult:
    path = BACKEND_DIR / "app" / "common" / "llm_client.py"
    content = _read_file(path)
    if not content or content.startswith("__READ_ERROR__"):
        return CheckResult("1. WenxinClient 引用 (P0-1)", False, f"无法读取 {path}")
    if "WenxinClient" in content:
        return CheckResult("1. WenxinClient 引用 (P0-1)", False, "llm_client.py 仍包含 WenxinClient 引用")
    return CheckResult("1. WenxinClient 引用 (P0-1)", True, "llm_client.py 已无 WenxinClient 引用")


# ---------------------------------------------------------------------------
# 检查项 2：deploy/judge0/docker-compose.yml 是否还有 privileged 字段（P0-2）
# ---------------------------------------------------------------------------

def check_no_judge0_privileged() -> CheckResult:
    path = PROJECT_ROOT / "deploy" / "judge0" / "docker-compose.yml"
    content = _read_file(path)
    if not content or content.startswith("__READ_ERROR__"):
        return CheckResult("2. Judge0 privileged 字段 (P0-2)", False, f"无法读取 {path}")
    # 检查是否存在作为 YAML 字段的 privileged:（行首可选空白 + privileged:）
    # 排除注释行（# 开头）
    for lineno, line in enumerate(content.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if re.match(r"^\s*privileged\s*:", line):
            return CheckResult(
                "2. Judge0 privileged 字段 (P0-2)", False,
                f"第 {lineno} 行仍存在 privileged 字段: {line.strip()}",
            )
    return CheckResult("2. Judge0 privileged 字段 (P0-2)", True, "docker-compose.yml 已无 privileged 字段（注释除外）")


# ---------------------------------------------------------------------------
# 检查项 3：deploy/docker-compose.yml 是否还有硬编码密码 codemind_dev_2026
# ---------------------------------------------------------------------------

def check_no_hardcoded_password() -> CheckResult:
    path = PROJECT_ROOT / "deploy" / "docker-compose.yml"
    content = _read_file(path)
    if not content or content.startswith("__READ_ERROR__"):
        return CheckResult("3. 硬编码密码 codemind_dev_2026", False, f"无法读取 {path}")
    if "codemind_dev_2026" in content:
        return CheckResult("3. 硬编码密码 codemind_dev_2026", False, "deploy/docker-compose.yml 仍包含硬编码密码 codemind_dev_2026")
    return CheckResult("3. 硬编码密码 codemind_dev_2026", True, "deploy/docker-compose.yml 已无硬编码密码 codemind_dev_2026")


# ---------------------------------------------------------------------------
# 检查项 4：experiments.py 的 HintRequest 是否还有客户端可控的 full_solution_allowed
# ---------------------------------------------------------------------------

def check_no_full_solution_allowed() -> CheckResult:
    path = BACKEND_DIR / "app" / "api" / "v1" / "endpoints" / "experiments.py"
    content = _read_file(path)
    if not content or content.startswith("__READ_ERROR__"):
        return CheckResult("4. HintRequest full_solution_allowed", False, f"无法读取 {path}")
    # 定位 HintRequest 类体，检查是否包含 full_solution_allowed 字段
    match = re.search(r"class\s+HintRequest\s*\([^)]*\)\s*:", content)
    if not match:
        return CheckResult("4. HintRequest full_solution_allowed", True, "未找到 HintRequest 类定义（可能已重构）")
    # 从类定义开始截取到下一个类定义或文件末尾
    start = match.start()
    rest = content[start:]
    # 截取到下一个顶层 class 或 def 或文件末尾
    next_def = re.search(r"\nclass\s+\w+\s*\(", rest[1:])
    class_body = rest[: next_def.start() + 1] if next_def else rest
    if "full_solution_allowed" in class_body:
        return CheckResult("4. HintRequest full_solution_allowed", False, "HintRequest 类仍包含 full_solution_allowed 字段")
    return CheckResult("4. HintRequest full_solution_allowed", True, "HintRequest 类已无 full_solution_allowed 字段")


# ---------------------------------------------------------------------------
# 检查项 5：workflows/teaching.py 的 validate_response 是否还允许无 evidence_id 的 citation
# ---------------------------------------------------------------------------

def check_validate_response_requires_evidence_id() -> CheckResult:
    path = BACKEND_DIR / "app" / "platform" / "agents" / "workflows" / "teaching.py"
    content = _read_file(path)
    if not content or content.startswith("__READ_ERROR__"):
        return CheckResult("5. validate_response evidence_id 校验", False, f"无法读取 {path}")
    # 定位 validate_response 函数体
    match = re.search(r"(?:async\s+)?def\s+validate_response\s*\(", content)
    if not match:
        return CheckResult("5. validate_response evidence_id 校验", False, "未找到 validate_response 函数定义")
    # 截取函数体（到下一个同缩进 def 或文件末尾）
    start = match.start()
    rest = content[start:]
    lines = rest.splitlines()
    func_lines: list[str] = []
    for i, line in enumerate(lines):
        if i == 0:
            func_lines.append(line)
            continue
        # 遇到顶层 def/class 时停止
        if re.match(r"(?:async\s+)?def\s+\w+\s*\(", line) or re.match(r"class\s+\w+\s*\(", line):
            break
        func_lines.append(line)
    func_body = "\n".join(func_lines)
    # 检查是否要求 evidence_id 存在且在允许集合内
    has_evidence_id_check = "evidence_id" in func_body and (
        "in allowed" in func_body or "in valid" in func_body or "evidence_id]" in func_body
    )
    if has_evidence_id_check:
        return CheckResult("5. validate_response evidence_id 校验", True, "validate_response 已强制要求 evidence_id 存在且在已检索证据集合内")
    return CheckResult("5. validate_response evidence_id 校验", False, "validate_response 未强制要求 evidence_id，可能允许无证据引用")


# ---------------------------------------------------------------------------
# 检查项 6：tool_governance.py 的 is_tool_enabled 是否还 fail-open
# ---------------------------------------------------------------------------

def check_is_tool_enabled_not_fail_open() -> CheckResult:
    path = BACKEND_DIR / "app" / "platform" / "agents" / "tools" / "tool_governance.py"
    content = _read_file(path)
    if not content or content.startswith("__READ_ERROR__"):
        return CheckResult("6. is_tool_enabled fail-open", False, f"无法读取 {path}")
    # 定位 is_tool_enabled 方法体
    match = re.search(r"(?:async\s+)?def\s+is_tool_enabled\s*\(", content)
    if not match:
        return CheckResult("6. is_tool_enabled fail-open", False, "未找到 is_tool_enabled 方法定义")
    start = match.start()
    rest = content[start:]
    lines = rest.splitlines()
    func_lines: list[str] = []
    for i, line in enumerate(lines):
        if i == 0:
            func_lines.append(line)
            continue
        if re.match(r"(?:async\s+)?def\s+\w+\s*\(", line) or re.match(r"class\s+\w+\s*\(", line):
            break
        func_lines.append(line)
    func_body = "\n".join(func_lines)
    # 检查 except 块中是否有 return True（fail-open）
    # 修复后的代码应对高风险工具 fail-closed（return False），低风险才 fail-open
    has_return_true_in_except = bool(re.search(r"except\s.*:\s*.*\n.*return\s+True", func_body, re.DOTALL))
    has_high_risk_guard = "HIGH_RISK" in func_body or "high_risk" in func_body
    if has_return_true_in_except and not has_high_risk_guard:
        return CheckResult("6. is_tool_enabled fail-open", False, "is_tool_enabled 的 except 块无条件 return True（fail-open）")
    if has_return_true_in_except and has_high_risk_guard:
        return CheckResult("6. is_tool_enabled fail-open", True, "is_tool_enabled 已对高风险工具 fail-closed，低风险才 fail-open")
    return CheckResult("6. is_tool_enabled fail-open", True, "is_tool_enabled 的 except 块未无条件 fail-open")


# ---------------------------------------------------------------------------
# 检查项 7：agent_governance_service.py 的 decide_proposal 是否用了 with_for_update
# ---------------------------------------------------------------------------

def check_decide_proposal_uses_for_update() -> CheckResult:
    path = BACKEND_DIR / "app" / "services" / "agent_governance_service.py"
    content = _read_file(path)
    if not content or content.startswith("__READ_ERROR__"):
        return CheckResult("7. decide_proposal with_for_update", False, f"无法读取 {path}")
    # 检查 decide_proposal 方法是否存在
    match = re.search(r"def\s+decide_proposal\s*\(", content)
    if not match:
        return CheckResult("7. decide_proposal with_for_update", False, "未找到 decide_proposal 方法定义")
    # 检查文件中是否使用 with_for_update
    if "with_for_update" not in content:
        return CheckResult("7. decide_proposal with_for_update", False, "agent_governance_service.py 未使用 with_for_update")
    # 检查 decide_proposal 是否通过 for_update=True 调用 get_proposal
    start = match.start()
    rest = content[start:]
    lines = rest.splitlines()
    func_lines: list[str] = []
    for i, line in enumerate(lines):
        if i == 0:
            func_lines.append(line)
            continue
        if re.match(r"\s{0,4}def\s+\w+\s*\(", line):
            break
        func_lines.append(line)
    func_body = "\n".join(func_lines)
    if "for_update=True" in func_body or "for_update = True" in func_body:
        return CheckResult("7. decide_proposal with_for_update", True, "decide_proposal 已通过 for_update=True 加行锁")
    return CheckResult("7. decide_proposal with_for_update", False, "decide_proposal 未通过 for_update=True 加行锁，可能存在 TOCTOU 竞态")


# ---------------------------------------------------------------------------
# 检查项 8：course_build_editor.py 的 bypass_lock 路径是否要求 course.publish 权限（P1-B1）
# ---------------------------------------------------------------------------

def check_bypass_lock_requires_publish() -> CheckResult:
    path = BACKEND_DIR / "app" / "api" / "v1" / "endpoints" / "course_build_editor.py"
    content = _read_file(path)
    if not content or content.startswith("__READ_ERROR__"):
        return CheckResult("8. bypass_lock 要求 course.publish (P1-B1)", False, f"无法读取 {path}")
    # course_build.py 也包含 bypass_lock 逻辑（update_step 端点）
    course_build_path = BACKEND_DIR / "app" / "api" / "v1" / "endpoints" / "course_build.py"
    course_build_content = _read_file(course_build_path)
    combined = content + "\n" + course_build_content
    # 检查 bypass_lock 附近是否有 course.publish 权限校验
    if "bypass_lock" not in combined:
        return CheckResult("8. bypass_lock 要求 course.publish (P1-B1)", True, "未找到 bypass_lock 引用（可能已移除）")
    # 查找 bypass_lock 出现的位置，检查附近是否有 course.publish
    found_publish_guard = False
    for match in re.finditer(r"bypass_lock", combined):
        start = max(0, match.start() - 300)
        end = min(len(combined), match.end() + 300)
        context = combined[start:end]
        if "course.publish" in context:
            found_publish_guard = True
            break
    if found_publish_guard:
        return CheckResult("8. bypass_lock 要求 course.publish (P1-B1)", True, "bypass_lock 路径已要求 course.publish 权限")
    return CheckResult("8. bypass_lock 要求 course.publish (P1-B1)", False, "bypass_lock 路径未要求 course.publish 权限")


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def main() -> int:
    checks = [
        check_no_wenxin_client,
        check_no_judge0_privileged,
        check_no_hardcoded_password,
        check_no_full_solution_allowed,
        check_validate_response_requires_evidence_id,
        check_is_tool_enabled_not_fail_open,
        check_decide_proposal_uses_for_update,
        check_bypass_lock_requires_publish,
    ]

    print("=" * 72)
    print("安全审计报告")
    print("=" * 72)
    print()

    results: list[CheckResult] = []
    for check in checks:
        results.append(check())

    for result in results:
        print(result.format())

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    print()
    print("-" * 72)
    print(f"汇总: {passed} 通过, {failed} 失败, 共 {len(results)} 项")
    if failed > 0:
        print("状态: 存在未修复的安全问题")
        return 1
    print("状态: 所有检查项通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
