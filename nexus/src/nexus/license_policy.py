"""T7 License 政策与修订固定门（执行前核验）。

- 允许复现/演示用途的 SPDX 白名单（V1 保守策略）：只放行宽松许可；
  copyleft（GPL/LGPL/MPL 等）与未知/未核验一律拒绝并说明原因，需人工
  复核，不自动执行——对应 AGENTS.md §4.1.10 "License 越线拒绝执行"。
- 修订固定：repo_revision 必须为 commit SHA（≥7 位 hex），分支名不算
  固定；未固定拒绝执行（REVISION_NOT_PINNED），调用方须重新走 intake
  固定 revision 后再建提案。
- 纯函数，无 IO，可单测；执行门在 experiment_agent 调用。
"""

from __future__ import annotations

from typing import Any

# V1 允许自动复现的 SPDX（GitHub API spdx_id 原样匹配）。
ALLOWED_REPRO_SPDX = frozenset({
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "CC0-1.0",
    "Unlicense",
    # Python 生态常见宽松许可（SPDX 写法）。
    "PSF-2.0",
    "PSF",
    "Python-2.0",
})


def normalize_spdx(spdx: Any) -> str:
    """归一化 SPDX（去空白；空/None → 空串）。大小写按 SPDX 原样比对之外，
    附带大小写不敏感回退（调用方先精确匹配，再 upper 匹配）。"""
    if not isinstance(spdx, str):
        return ""
    return spdx.strip()


def _allowed_case_insensitive(spdx: str) -> bool:
    if spdx in ALLOWED_REPRO_SPDX:
        return True
    upper = spdx.upper()
    return any(candidate.upper() == upper for candidate in ALLOWED_REPRO_SPDX)


def is_sha_pinned(revision: Any) -> bool:
    """修订是否固定到 commit（≥7 位 hex；分支名/空串不算固定）。"""
    cleaned = (revision or "").strip() if isinstance(revision, str) else ""
    return len(cleaned) >= 7 and all(
        c in "0123456789abcdefABCDEF" for c in cleaned)


def verify_license(license_info: Any) -> dict[str, Any]:
    """核验 License 是否允许自动复现（纯函数，不抛异常）。

    返回 {"allowed": bool, "code": str, "detail": str}：
    - LICENSE_OK：已核验＋白名单内，可执行；
    - LICENSE_UNVERIFIED：未核验/缺失/NOASSERTION，需先确认；
    - LICENSE_NOT_ALLOWED：已核验但不在白名单（copyleft/专有），拒绝并说明。
    """
    if not isinstance(license_info, dict):
        return {
            "allowed": False, "code": "LICENSE_UNVERIFIED",
            "detail": "License 未核验（无结论）；执行前需确认允许复现用途。",
        }
    status = str(license_info.get("status") or "").strip().lower()
    spdx = normalize_spdx(license_info.get("spdx"))
    if status != "verified" or not spdx or spdx.upper() == "NOASSERTION":
        return {
            "allowed": False, "code": "LICENSE_UNVERIFIED",
            "detail": "License 未核验（只读到了仓库信息，未确认允许复现用途）；"
                      "执行前需确认 License。",
        }
    if _allowed_case_insensitive(spdx):
        return {"allowed": True, "code": "LICENSE_OK",
                "detail": f"License 已核验（{spdx}），允许复现用途。"}
    return {
        "allowed": False, "code": "LICENSE_NOT_ALLOWED",
        "detail": f"License 已核验为 {spdx}，不在 V1 自动复现白名单内"
                  "（仅 MIT/Apache-2.0/BSD/ISC/CC0/Unlicense/PSF 自动放行；"
                  "copyleft/专有需人工复核），拒绝自动执行。",
    }


def verify_execution_gate(*, scope: Any, license_info: Any) -> dict[str, Any]:
    """执行前核验门（修订固定＋License；纯函数，不碰存储）。

    返回 {"ok": bool, "code": str, "detail": str}：
    - ok True（code GATE_OK）方可执行；
    - 修订未固定优先返回 REVISION_NOT_PINNED；
    - 其次 License（LICENSE_UNVERIFIED / LICENSE_NOT_ALLOWED）。
    scope 缺失/无 revision 同样判未固定（fail-closed）。
    """
    scope_dict = scope if isinstance(scope, dict) else {}
    revision = str(scope_dict.get("repo_revision") or "")
    if not is_sha_pinned(revision):
        return {
            "ok": False, "code": "REVISION_NOT_PINNED",
            "detail": "repo_revision 未固定到 commit SHA（分支名不算固定）；"
                      "请经 intake 固定 revision 后重建提案再执行。",
        }
    licensed = verify_license(license_info)
    if not licensed["allowed"]:
        return {"ok": False, "code": licensed["code"],
                "detail": licensed["detail"]}
    return {"ok": True, "code": "GATE_OK",
            "detail": f"修订已固定（{revision[:12]}）＋{licensed['detail']}"}
