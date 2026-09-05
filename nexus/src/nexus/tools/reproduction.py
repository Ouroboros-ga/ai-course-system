"""Quick Reproduction 工具：论文复现计划生成 + Repro Worker 执行接口。

安全边界（AGENTS.md §4.1.10）：未知 GitHub Repo 视为不可信代码，只能在专用
Repro Worker 受限执行，禁止在 Nexus Runtime 或旧 Backend/Judge0 内运行。
License 必须允许演示/复现用途；Worker 未配置或不可达时 fail-closed 返回
REPRO_WORKER_UNAVAILABLE，绝不假造执行结果。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from langchain_core.tools import tool

from nexus.config import get_settings

logger = logging.getLogger(__name__)

# 已核验 License 的复现预设（License 经 GitHub API 核实，2026-09-03）。
REPRO_PRESETS: dict[str, dict[str, Any]] = {
    "nanogpt": {
        "preset_id": "nanogpt",
        "paper_title": "Language Models are Unsupervised Multitask Learners (GPT-2, Radford et al., 2019)",
        "repo_url": "https://github.com/karpathy/nanoGPT",
        "repo_license": "MIT",
        "repo_stars": 62738,
        "cpu_friendly": True,
        "estimated_minutes": 5,
        "language": "python",
        "steps": [
            "git clone https://github.com/karpathy/nanoGPT && cd nanoGPT",
            # torch 由 Worker 镜像预装（阿里云 pytorch-wheels/cpu 轮子 ~190MB，
            # 官方 PyPI Linux 轮子捆绑 CUDA ~3GB 会击穿磁盘配额）；此处只装
            # 轻量依赖（清华 PyPI 镜像）。材料引用时如实标注"Worker 预置环境配置"。
            "pip install numpy transformers datasets tiktoken tqdm "
            "--index-url https://pypi.tuna.tsinghua.edu.cn/simple",
            "python data/shakespeare_char/prepare.py",
            "python train.py config/train_shakespeare_char.py --device=cpu --compile=False "
            "--eval_iters=20 --log_interval=1 --block_size=64 --batch_size=12 "
            "--n_layer=4 --n_head=4 --n_embd=128 --max_iters=2000 "
            "--lr_decay_iters=2000 --dropout=0.0",
            "python sample.py --out_dir=out-shakespeare-char --device=cpu",
        ],
        "expected_artifacts": [
            "training loss curve (converges around 1.88 with CPU config)",
            "generated Shakespeare-style text sample",
        ],
        # M4-B3：确定性判定的期望指标（LLM 不参与 PASS/FAIL）。
        # 来源：官方 README CPU 配置声明（"converges around 1.88"）；
        # 容差覆盖 CPU 数值噪声（2026-09-04 实测 val loss 1.8857）。
        "expected_metrics": {
            "val_loss": {"target": 1.88, "tolerance": 0.06},
        },
        "expected_metrics_source": (
            "nanoGPT 官方 README CPU 配置声明（converges around 1.88）；"
            "容差 ±0.06 覆盖 CPU 数值噪声"
        ),
        "notes": "官方 README 的 CPU 配置命令，训练闭环完整，适合现场演示。",
    },
}


@tool
def plan_reproduction(target: str) -> dict[str, Any]:
    """为一篇论文生成快速复现（Quick Reproduction）计划。

    target 可以是预设 ID（如 "nanogpt"）、论文标题或 arXiv 编号。
    命中已核验预设时返回完整复现步骤（仓库/License/命令/预期产物）；
    未命中预设时返回需要先调研的信息缺口，不编造复现命令。
    """
    key = target.strip().lower()
    for candidate, preset in REPRO_PRESETS.items():
        if (
            candidate == key
            or key in preset["paper_title"].lower()
            or key in preset["repo_url"].lower()
            or any(word in preset["paper_title"].lower() for word in ("gpt-2", "nanogpt") if word in key)
        ):
            return {
                "status": "success",
                "source": "verified_preset",
                "plan": preset,
                "is_supplementary": True,
            }
    return {
        "status": "no_preset",
        "target": target,
        "detail": (
            "没有已核验的复现预设。请先用 search_arxiv_papers 与 web_search 调研论文、"
            "官方仓库与 License；License 允许复现用途后，方可把复现步骤提交给 "
            "Repro Worker 执行。禁止直接信任未核验仓库的命令。"
        ),
        "known_presets": list(REPRO_PRESETS.keys()),
        "is_supplementary": True,
    }


async def _submit_to_worker(preset: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.repro_worker_url:
        return {
            "status": "unavailable",
            "code": "REPRO_WORKER_UNAVAILABLE",
            "detail": (
                "NEXUS_REPRO_WORKER_URL 未配置。复现计划已生成但未执行；"
                "不得向用户表述为已复现或已运行。"
            ),
            "plan": preset,
            "is_supplementary": True,
        }
    payload = {
        "preset_id": preset["preset_id"],
        "repo_url": preset["repo_url"],
        "repo_license": preset["repo_license"],
        "steps": preset["steps"],
    }
    headers = {
        **({"Authorization": f"Bearer {settings.repro_worker_token}"}
           if settings.repro_worker_token else {}),
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{settings.repro_worker_url.rstrip('/')}/jobs",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return {
            "status": "submitted",
            "job": response.json(),
            "repo_url": preset["repo_url"],
            "repo_license": preset["repo_license"],
            "is_supplementary": True,
        }


async def _record_job_ownership(job_id: str, preset: dict[str, Any]) -> bool:
    """M4-B1：向 Backend 登记作业归属（job 查询按发起人鉴权的依据）。

    best-effort：登记失败不阻断提交结果，但如实标注（前端进度查询将不可用）。
    """
    from nexus.artifact_client import _settings_ready
    from nexus.request_scope import current_user_id

    ready = _settings_ready()
    user_id = current_user_id()
    if ready is None or not user_id:
        return False
    url, token = ready
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{url}/api/v1/nexus-internal/repro-jobs",
                json={
                    "job_id": job_id,
                    "preset_id": preset.get("preset_id", ""),
                    "repo_url": preset.get("repo_url", ""),
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Nexus-User-Id": user_id,
                },
            )
        return response.status_code == 200
    except Exception as error:  # noqa: BLE001 - 登记失败如实标注
        logger.warning("repro job ownership record failed: %s", type(error).__name__)
        return False


async def _record_run_linkage(
    *, run_id: str, user_id: str, session_id: str,
    preset: dict[str, Any], approval_id: str, job_id: str,
) -> bool:
    """NX-E1：向 Backend 登记 run linkage（恢复查询依据）。

    best-effort：失败不阻断提交结果（审批记录仍是权威归属），仅记日志。
    """
    from nexus import approvals as approvals_module
    from nexus.artifact_client import _settings_ready
    from nexus.request_scope import current_user_id

    ready = _settings_ready()
    uid = user_id or current_user_id() or ""
    if ready is None or not uid:
        return False
    url, token = ready
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{url}/api/v1/nexus-internal/repro-runs",
                json={
                    "run_id": run_id,
                    "session_id": session_id,
                    "tool": "run_reproduction",
                    "preset_id": preset.get("preset_id", ""),
                    "plan_hash": approvals_module.plan_hash_for(preset),
                    "approval_id": approval_id,
                    "job_id": job_id,
                    "status": "submitted",
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Nexus-User-Id": uid,
                },
            )
        return response.status_code == 200
    except Exception as error:  # noqa: BLE001
        logger.warning("repro run linkage record failed: %s", type(error).__name__)
        return False


@tool
async def run_reproduction(preset_id: str) -> dict[str, Any]:
    """把已核验预设的复现计划提交给专用 Repro Worker 执行。

    NX-G2（v1.3 A3 Hard Workflow）：本工具不再直连 Worker。无有效审批
    票据时只创建持久化提案并返回 ``approval_required``（零 Worker 提交）；
    有票据时经 ``execute_approved_reproduction`` 服务端核销后执行。
    只接受 plan_reproduction 返回的预设 ID；未知仓库不会被本工具执行。
    """
    from nexus import approvals
    from nexus.request_scope import (
        current_approval_id,
        current_session_id,
        current_user_id,
    )

    preset = REPRO_PRESETS.get(preset_id.strip().lower())
    if preset is None:
        return {
            "status": "rejected",
            "code": "UNKNOWN_PRESET",
            "detail": "只接受已核验预设（见 plan_reproduction 的 known_presets）。",
            "known_presets": list(REPRO_PRESETS.keys()),
        }
    user_id = current_user_id() or ""
    session_id = current_session_id() or ""
    approval_id = current_approval_id()
    if not approval_id:
        # 提案：归属（user/session/tool/preset/plan hash/预算）此刻落库，
        # 不依赖提交后的 best-effort 登记；Worker 零接触。
        proposal = approvals.create_approval(
            user_id=user_id,
            session_id=session_id,
            tool="run_reproduction",
            preset=preset,
            ttl_s=_approval_ttl_s(),
        )
        return {
            "status": "approval_required",
            "code": "APPROVAL_REQUIRED",
            "detail": (
                "复现执行需要用户本次批准。已生成审批提案（未执行任何代码）；"
                "用户在审批卡批准后，服务端核销票据才会提交 Worker。"
            ),
            "approval": _public_approval(proposal, preset),
            "is_supplementary": True,
        }
    try:
        return await execute_approved_reproduction(
            approval_id=approval_id,
            user_id=user_id,
            session_id=session_id,
            preset_id=preset_id,
        )
    except approvals.ApprovalError as error:
        if error.code == "APPROVAL_NOT_APPROVED":
            # 票据存在但尚未批准（如用户还没点）：保持提案态，不报错执行。
            existing = approvals.get_approval(approval_id)
            return {
                "status": "approval_required",
                "code": "APPROVAL_REQUIRED",
                "detail": "审批尚未批准；批准后服务端才会执行。",
                "approval": _public_approval(existing, preset) if existing else None,
                "is_supplementary": True,
            }
        return {
            "status": "approval_denied",
            "code": error.code,
            "detail": f"{error}；复现未执行。",
            "is_supplementary": True,
        }


def _approval_ttl_s() -> int:
    from nexus.config import get_settings

    try:
        return max(60, int(get_settings().approval_ttl_s))
    except Exception:  # noqa: BLE001 - 配置异常用安全默认
        return 900


def _public_approval(
    row: dict[str, Any] | None, preset: dict[str, Any] | None
) -> dict[str, Any] | None:
    """审批的公开投影：给前端审批卡展示，不含任何内部令牌。"""
    if row is None:
        return None
    return {
        "approval_id": row["approval_id"],
        "status": row["status"],
        "preset_id": row["preset_id"],
        "repo_url": (preset or {}).get("repo_url", ""),
        "repo_license": (preset or {}).get("repo_license", ""),
        "plan_hash": row["plan_hash"],
        "budget": row["budget"],
        "expires_at": row["expires_at"],
        "job_id": row.get("job_id") or "",
    }


async def execute_approved_reproduction(
    *, approval_id: str, user_id: str, session_id: str, preset_id: str
) -> dict[str, Any]:
    """NX-G2 统一执行核心：聊天工具、手工执行、恢复入口共用同一检查。

    流程：取预设 → 原子核销批准（本人/同会话/plan_hash/有效期/一次性）→
    提交 Worker → 绑定 job → 登记归属。任何 ApprovalError 都意味着
    "不得提交 Worker"，调用方必须如实返回失败。
    """
    from nexus import approvals

    preset = REPRO_PRESETS.get(preset_id.strip().lower())
    if preset is None:
        return {
            "status": "rejected",
            "code": "UNKNOWN_PRESET",
            "detail": "只接受已核验预设（见 plan_reproduction 的 known_presets）。",
            "known_presets": list(REPRO_PRESETS.keys()),
        }
    approval = approvals.consume_approval(
        approval_id, user_id=user_id, session_id=session_id, preset=preset
    )
    if approval.get("job_id"):
        # 幂等重试：票据已消费过，直接返回原 job，不重复启动实验。
        return {
            "status": "submitted",
            "deduped": True,
            "detail": "该批准已执行过，返回原作业，不重复启动实验。",
            "job": {"job_id": approval["job_id"]},
            "approval_id": approval_id,
            "repo_url": preset["repo_url"],
            "repo_license": preset["repo_license"],
            "is_supplementary": True,
        }
    try:
        result = await _submit_to_worker(preset)
        # M4-B1：提交成功（拿到 job_id）后登记归属，进度查询按发起人鉴权。
        # NX-G2：执行前的归属绑定已由审批记录承担；此处是提交后的 job 关联。
        # NX-E1：同时登记 run linkage（run_id=approval_id），供刷新/换设备恢复。
        if result.get("status") == "submitted":
            job_id = str((result.get("job") or {}).get("job_id", ""))
            if job_id:
                approvals.attach_job(approval_id, job_id)
                recorded = await _record_job_ownership(job_id, preset)
                result["ownership_recorded"] = recorded
                await _record_run_linkage(
                    run_id=approval_id, user_id=user_id, session_id=session_id,
                    preset=preset, approval_id=approval_id, job_id=job_id,
                )
                if not recorded:
                    result["detail"] = (
                        "作业已提交，但归属登记失败：进度查询与报告生成暂不可用。"
                    )
        result["approval_id"] = approval_id
        return result
    except Exception as error:  # noqa: BLE001 - Worker 故障 fail-closed
        logger.warning("Repro Worker submit failed: %s", type(error).__name__)
        return {
            "status": "unavailable",
            "code": "REPRO_WORKER_UNAVAILABLE",
            "detail": f"Repro Worker 调用失败（{type(error).__name__}）；复现未执行。",
            "plan": preset,
            "is_supplementary": True,
        }
