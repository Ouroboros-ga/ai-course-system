"""Source-free TeachingAgent feedback projected from a bounded diagnosis."""
from __future__ import annotations

from typing import Any

from app.models.coding_diagnosis_model import CodingDiagnosisRecord


def build_teaching_feedback(record: CodingDiagnosisRecord) -> dict[str, Any]:
    """Return the fixed five-part learner feedback contract.

    The function intentionally accepts no ExperimentRun, artifact or source
    argument.  This makes it impossible for main TeachingAgent state or the
    Conversation Domain to acquire source code or hidden case payloads while
    still allowing a constrained teaching response.
    """
    steps = list(record.debug_steps or [])
    passed = record.outcome == "accepted"
    infrastructure = record.outcome == "sandbox_unavailable"
    return {
        "status": "insufficient_evidence" if infrastructure else "ready",
        "result_overview": record.summary,
        "done_well": (
            "本次实现通过了服务器评分检查；这是一条练习证据，还不足以单独判断掌握。"
            if passed
            else "你已经完成了一次可复现运行，当前结果可以用于定位下一步修改。"
        ),
        "current_issue": (
            "沙箱暂不可用，本次不计入正式学习证据。"
            if infrastructure
            else ("当前没有检测到阻塞性问题。" if passed else record.summary)
        ),
        "next_step": steps[0] if steps else "修改一个最小点后重新运行。",
        "optional_hint": steps[1] if len(steps) > 1 else None,
        "reason_codes": list(record.reason_codes or []),
        "policy_version": record.policy_version,
    }
