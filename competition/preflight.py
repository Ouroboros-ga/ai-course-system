#!/usr/bin/env python3
"""参赛材料打包预检脚本（挑战杯 XH-202620，2026-09-05 截止前运行）。

检查 competition/ 目录与关键材料：
1. 必交材料文件是否存在（01–07）；
2. 材料中是否残留真实密钥/令牌（api_key=、secret、token、PRIVATE KEY、sk- 等）；
3. 待填写占位（作品名称/学校/负责人/报名表等）逐项报告（warning，不阻塞）；
4. 输出最终打包命名模板与复核结论。

纯标准库，只读不写：
    python competition/preflight.py
退出码：0=可以打包（仅 warnings 亦可接受）；1=存在阻塞项（缺必交文件或疑似密钥）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPETITION = ROOT / "competition"

REQUIRED_FILES = {
    "01-参赛信息/CHECKLIST.md": "报名核对清单",
    "02-伦理与安全合规性声明/伦理与安全合规性声明.md": "伦理与安全合规性声明（待签字）",
    "03-作品Demo/Demo说明.md": "Demo 说明",
    "04-作品方案/作品方案.md": "作品方案",
    "04-作品方案/PPT演讲脚本.md": "答辩脚本",
    "05-作品代码/代码与模型清单.md": "代码与模型清单",
    "06-效果验证报告/效果验证报告模板.md": "效果验证报告模板",
    "07-其他材料/测试报告说明.md": "测试报告说明",
    "README.md": "提交检查清单",
}

SECRET_PATTERNS = [
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)secret\s*[:=]\s*[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?i)token\s*[:=]\s*[A-Za-z0-9_.-]{20,}"),
    re.compile(r"BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"),  # JWT
]

PLACEHOLDER_PATTERNS = [
    re.compile(r"待确认|待填写|待回填|待部署|（待|________|____|XXX|TBD"),
]


def _scan_text(text: str, rel: str, issues: list[str], warnings: list[str]) -> None:
    for pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match:
            issues.append(f"[密钥风险] {rel}: 疑似敏感串 {match.group(0)[:24]}...（请改用占位符）")
    for pattern in PLACEHOLDER_PATTERNS:
        if pattern.search(text):
            warnings.append(f"[待填写] {rel}: 存在未填充占位（作品名/学校/用户反馈/URL 等）")
            break


def main() -> int:
    issues: list[str] = []
    warnings: list[str] = []
    print("=== 1. 必交材料检查 ===")
    for rel, label in REQUIRED_FILES.items():
        path = COMPETITION / rel
        if path.exists():
            print(f"  [OK] {rel}（{label}）")
        else:
            issues.append(f"[缺文件] {rel}（{label}）")
            print(f"  [FAIL] {rel}")

    print("=== 2. 密钥/占位扫描（competition/ 全部文本） ===")
    text_files = [
        p for p in COMPETITION.rglob("*")
        if p.is_file() and p.suffix.lower() in {".md", ".txt", ".json", ".py"}
        and p.name != "preflight.py"
    ]
    for path in sorted(text_files):
        rel = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        _scan_text(text, rel, issues, warnings)
    if not any("密钥风险" in issue for issue in issues):
        print("  [OK] 未发现疑似密钥")

    print("=== 3. 结论 ===")
    for issue in issues:
        print(f"  [BLOCK] {issue}", file=sys.stderr)
    for warning in sorted(set(warnings)):
        print(f"  [WARN ] {warning}")

    if issues:
        print("\n结论：存在阻塞项，请修复后再打包。", file=sys.stderr)
        return 1
    print("\n结论：必交文件齐全、无密钥泄露；占位项请按清单补齐后打包。")
    print("\n压缩包命名模板：")
    print("  提报单位(学校全称)—学科垂类大模型与创新应用开发—作品名称—团队负责人姓名—团队负责人联系方式")
    print("示例：XX大学—学科垂类大模型与创新应用开发—智溯CS—张三—186XXXXXXXX")
    return 0


if __name__ == "__main__":
    sys.exit(main())
