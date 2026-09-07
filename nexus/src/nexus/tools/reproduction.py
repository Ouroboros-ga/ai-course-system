"""Quick Reproduction 工具：论文复现计划生成 + Repro Worker 执行接口。

安全边界（AGENTS.md §4.1.10）：未知 GitHub Repo 视为不可信代码，只能在专用
Repro Worker 受限执行，禁止在 Nexus Runtime 或旧 Backend/Judge0 内运行。
License 必须允许演示/复现用途；Worker 未配置或不可达时 fail-closed 返回
REPRO_WORKER_UNAVAILABLE，绝不假造执行结果。
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import httpx
from langchain_core.tools import tool

from nexus.config import get_settings

logger = logging.getLogger(__name__)

# 已核验 License 的复现预设（License 经 GitHub API 核实，2026-09-03）。
REPRO_PRESETS: dict[str, dict[str, Any]] = {
    "nanogpt": {
        "preset_id": "nanogpt",
        # NX-LB1：运行默认显示名（服务端 display_title 回退链用；不入执行 hash）。
        "display_name": "nanoGPT",
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


# ---------------------------------------------------------------------------
# NX-LB4/LB5：运行操作工具（查询/取消/备注/提案）。
# 身份与当前会话来自请求作用域（ContextVar），模型传参只提供目标标识；
# Backend 内部端点做归属+会话绑定校验，工具如实透传失败语义。
# ---------------------------------------------------------------------------


def _internal_ready() -> tuple[str, str] | None:
    settings = get_settings()
    url = (settings.backend_internal_url or "").rstrip("/")
    token = settings.backend_internal_token or ""
    if not url or not token:
        return None
    return url, token


async def _internal_run_request(
    method: str, path: str, *, user_id: str, session_id: str,
    json_body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """调用 Backend 内部运行端点；返回 (status_code, data)。非 JSON 如实报错。"""
    ready = _internal_ready()
    if ready is None:
        return 503, {"code": "BACKEND_INTERNAL_NOT_CONFIGURED"}
    url, token = ready
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Nexus-User-Id": user_id,
        "X-Nexus-Session-Id": session_id,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.request(
                method, f"{url}{path}", json=json_body, headers=headers)
    except Exception as error:  # noqa: BLE001
        logger.warning("internal run request failed: %s", type(error).__name__)
        return 503, {"code": "BACKEND_INTERNAL_UNAVAILABLE"}
    try:
        payload = response.json()
    except ValueError:
        return 502, {"code": "BACKEND_INTERNAL_BAD_RESPONSE"}
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return response.status_code, payload["data"]
    return response.status_code, payload if isinstance(payload, dict) else {}


def _internal_unavailable(code: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "code": code,
        "detail": "后端内部服务不可用；不能确认运行状态，也不得编造状态。",
        "is_supplementary": True,
    }


def _scope_identity() -> tuple[str, str]:
    from nexus.request_scope import current_session_id, current_user_id

    return current_user_id() or "", current_session_id() or ""


async def _fetch_owned_run(run_id: str, user_id: str) -> dict[str, Any] | None:
    """经 Backend 内部端点取本人 run 全行（提案 parent 校验用）。"""
    status_code, data = await _internal_run_request(
        "GET", f"/api/v1/nexus-internal/repro-runs/{(run_id or '').strip()[:64]}",
        user_id=user_id, session_id="")
    if status_code == 200 and isinstance(data, dict) and data.get("run_id"):
        return data
    return None


@tool
async def get_reproduction_run(run_id: str) -> dict[str, Any]:
    """查询用户某次复现运行的状态与有界日志（只读，有界投影）。

    只能查询当前会话中属于当前用户且被明确提到 run_id 的运行；
    跨会话/他人的运行一律被拒。返回的状态与日志是服务端快照，
    与用户描述冲突时以快照为准，不凭记忆改写。
    """
    user_id, session_id = _scope_identity()
    if not user_id or not session_id:
        return {
            "status": "error", "code": "SCOPE_MISSING",
            "detail": "缺少用户/会话上下文，无法查询运行。",
            "is_supplementary": True,
        }
    status_code, data = await _internal_run_request(
        "GET", f"/api/v1/nexus-internal/runs/{(run_id or '').strip()[:64]}/status",
        user_id=user_id, session_id=session_id)
    if status_code == 200:
        return {"status": "success", "run": data, "is_supplementary": True}
    if status_code == 404:
        return {
            "status": "not_found", "code": "RUN_NOT_FOUND",
            "detail": "该 run_id 不存在或不属于当前用户；请与用户确认运行标识。",
            "is_supplementary": True,
        }
    if status_code == 403:
        return {
            "status": "rejected", "code": "RUN_SESSION_MISMATCH",
            "detail": "该运行属于其他会话；请用户切换到对应会话或提供本会话的运行。",
            "is_supplementary": True,
        }
    if status_code == 422:
        return {
            "status": "rejected", "code": str(data.get("code") or "RUN_REF_INVALID"),
            "detail": "run/step 标识不合法。",
            "is_supplementary": True,
        }
    return _internal_unavailable(str(data.get("code") or "BACKEND_INTERNAL_UNAVAILABLE"))


@tool
async def cancel_reproduction_run(run_id: str) -> dict[str, Any]:
    """取消用户指定的复现运行（破坏性操作，需要用户明确确认后才执行）。

    首次调用返回 confirmation_required：请向用户说明要取消的运行并请其
    在界面上确认；用户确认后服务端签发一次性授权，再次调用本工具才会
    真正取消。绝不因"正在讨论报错"而取消运行，也不代替用户做取消决定。
    """
    user_id, session_id = _scope_identity()
    if not user_id or not session_id:
        return {
            "status": "error", "code": "SCOPE_MISSING",
            "detail": "缺少用户/会话上下文，无法取消运行。",
            "is_supplementary": True,
        }
    status_code, data = await _internal_run_request(
        "POST", f"/api/v1/nexus-internal/runs/{(run_id or '').strip()[:64]}/cancel",
        user_id=user_id, session_id=session_id, json_body={})
    if status_code != 200:
        if status_code == 404:
            return {
                "status": "not_found", "code": "RUN_NOT_FOUND",
                "detail": "该 run_id 不存在或不属于当前用户。",
                "is_supplementary": True,
            }
        if status_code == 403:
            return {
                "status": "rejected", "code": "RUN_SESSION_MISMATCH",
                "detail": "该运行属于其他会话，不能取消。",
                "is_supplementary": True,
            }
        return _internal_unavailable(str(data.get("code") or "REPRO_CANCEL_UNAVAILABLE"))
    if data.get("status") == "confirmation_required":
        return {
            "status": "confirmation_required",
            "code": "CANCEL_CONFIRMATION_REQUIRED",
            "run_id": data.get("run_id"),
            "detail": str(data.get("detail") or ""),
            "is_supplementary": True,
        }
    return {"status": "success", "run_id": data.get("run_id"),
            "job_id": data.get("job_id"), "run_status": data.get("status"),
            "already_terminal": bool(data.get("already_terminal")),
            "note": str(data.get("note") or ""),
            "is_supplementary": True}


@tool
async def add_reproduction_note(run_id: str, content: str) -> dict[str, Any]:
    """给用户的复现运行追加一条备注（≤4000 字符；标记为智能体的解释/建议）。

    备注只是解释与建议的留痕，不会修改原始日志、指标或复现结论；
    用户自己的备注经界面写入，两者按 author 区分。
    """
    user_id, session_id = _scope_identity()
    if not user_id or not session_id:
        return {
            "status": "error", "code": "SCOPE_MISSING",
            "detail": "缺少用户/会话上下文，无法写入备注。",
            "is_supplementary": True,
        }
    cleaned = (content or "").strip()
    if not cleaned or len(cleaned) > 4000:
        return {
            "status": "rejected", "code": "NOTE_CONTENT_INVALID",
            "detail": "备注须为 1–4000 字符。",
            "is_supplementary": True,
        }
    status_code, data = await _internal_run_request(
        "POST", f"/api/v1/nexus-internal/runs/{(run_id or '').strip()[:64]}/notes",
        user_id=user_id, session_id=session_id,
        json_body={"content": cleaned, "request_id": f"agent-{uuid.uuid4().hex[:12]}"})
    if status_code == 200:
        return {"status": "success", "note": data, "is_supplementary": True}
    if status_code == 404:
        return {"status": "not_found", "code": "RUN_NOT_FOUND",
                "detail": "该 run_id 不存在或不属于当前用户。", "is_supplementary": True}
    if status_code == 403:
        return {"status": "rejected", "code": "RUN_SESSION_MISMATCH",
                "detail": "该运行属于其他会话。", "is_supplementary": True}
    return _internal_unavailable(str(data.get("code") or "NOTE_WRITE_FAILED"))


@tool
async def create_reproduction_proposal(
    preset_id: str, objective: str = "", parameters: dict[str, Any] | None = None,
    parent_run_id: str = "",
) -> dict[str, Any]:
    """为用户创建结构化复现提案草案（不执行、不批准）。

    只接受已核验预设 id；parameters 仅限该预设审核过的参数（见
    /nexus/repro/presets 的 schema）。可选 parent_run_id 基于本人某次
    旧运行派生新配置。返回真实 proposal_id/version 供浮窗展示；
    是否批准永远由用户决定。
    """
    from nexus import proposals as proposals_module
    from nexus.request_scope import current_session_id, current_user_id

    user_id = current_user_id() or ""
    session_id = current_session_id() or ""
    if not user_id or not session_id:
        return {
            "status": "error", "code": "SCOPE_MISSING",
            "detail": "缺少用户/会话上下文，无法创建提案。",
            "is_supplementary": True,
        }
    preset = REPRO_PRESETS.get((preset_id or "").strip().lower())
    if preset is None:
        return {
            "status": "rejected", "code": "UNKNOWN_PRESET",
            "detail": "只接受已核验预设（见 plan_reproduction 的 known_presets）。",
            "known_presets": list(REPRO_PRESETS.keys()),
            "is_supplementary": True,
        }
    parent_run: dict[str, Any] | None = None
    parent_id = (parent_run_id or "").strip()[:64]
    if parent_id:
        parent_run = await _fetch_owned_run(parent_id, user_id)
        if parent_run is None:
            return {
                "status": "not_found", "code": "PROPOSAL_PARENT_NOT_FOUND",
                "detail": "parent_run_id 不存在或不属于当前用户。",
                "is_supplementary": True,
            }
    try:
        row = proposals_module.create_proposal(
            user_id=user_id, session_id=session_id, preset=preset,
            parent_run=parent_run, objective=objective,
            parameters=parameters or {}, data=None,
        )
    except proposals_module.ProposalError as error:
        return {
            "status": "rejected", "code": error.code,
            "detail": str(error),
            "is_supplementary": True,
        }
    return {
        "status": "success",
        "proposal": proposals_module.public_proposal_view(row),
        "deduped": bool(row.get("deduped")),
        "next_step": (
            "向用户展示参数与差异；用户可在浮窗审阅后批准。批准由用户发起，"
            "你不得代批，也不得在未获批准时执行。"
        ),
        "is_supplementary": True,
    }


@tool
def update_reproduction_proposal(
    proposal_id: str, expected_version: int,
    objective: str | None = None, parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按用户要求修改提案参数（乐观锁；仅 draft；旧批准自动失效）。

    expected_version 必须为提案当前版本（修改会 +1）；parameters 传需要
    改动的键（其余保持原值）。返回结构化 diff 供浮窗展示。
    """
    from nexus import proposals as proposals_module
    from nexus.request_scope import current_user_id

    user_id = current_user_id() or ""
    if not user_id:
        return {
            "status": "error", "code": "SCOPE_MISSING",
            "detail": "缺少用户上下文，无法修改提案。",
            "is_supplementary": True,
        }
    try:
        result = proposals_module.patch_proposal(
            (proposal_id or "").strip()[:64], user_id=user_id,
            expected_version=int(expected_version),
            objective=objective, parameters=parameters,
        )
    except proposals_module.ProposalError as error:
        return {
            "status": "rejected", "code": error.code, "detail": str(error),
            "is_supplementary": True,
        }
    return {
        "status": "success",
        "proposal": proposals_module.public_proposal_view(result["proposal"]),
        "diff": result["diff"],
        "next_step": "把差异展示给用户；旧批准已随版本失效，需重新请求审批。",
        "is_supplementary": True,
    }


@tool
def request_reproduction_approval(proposal_id: str, expected_version: int) -> dict[str, Any]:
    """为提案当前版本请求执行审批（pin 住版本+hash；不执行）。

    返回真实 approval 引用供浮窗展示；同一版本重复请求返回同一待办
    （幂等）。批准与否由用户在浮窗决定——批准后前端会在下一次对话请求
    带上 approval_id，服务端核销后才会执行。
    """
    from nexus import proposals as proposals_module
    from nexus.request_scope import current_user_id

    user_id = current_user_id() or ""
    if not user_id:
        return {
            "status": "error", "code": "SCOPE_MISSING",
            "detail": "缺少用户上下文，无法请求审批。",
            "is_supplementary": True,
        }
    try:
        result = proposals_module.request_approval_for_proposal(
            (proposal_id or "").strip()[:64], user_id=user_id,
            expected_version=int(expected_version))
    except proposals_module.ProposalError as error:
        return {
            "status": "rejected", "code": error.code, "detail": str(error),
            "is_supplementary": True,
        }
    return {
        "status": "success",
        "approval": result["approval"],
        "deduped": bool(result.get("deduped")),
        "next_step": "等待用户在浮窗批准；不要重复请求，也不要在未批准时执行。",
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


async def _record_job_ownership(
    job_id: str, preset: dict[str, Any], user_id: str | None = None
) -> bool:
    """M4-B1：向 Backend 登记作业归属（job 查询按发起人鉴权的依据）。

    best-effort：登记失败不阻断提交结果，但如实标注（前端进度查询将不可用）。
    ``user_id`` 显式传参优先（审批执行路径无聊天请求作用域，ContextVar 为空——
    2026-09-06 线上验收发现的集成缺口）；无传参时回退请求作用域（聊天工具路径）。
    """
    from nexus.artifact_client import _settings_ready
    from nexus.request_scope import current_user_id

    ready = _settings_ready()
    effective_user_id = user_id or current_user_id()
    if ready is None or not effective_user_id:
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
                    "X-Nexus-User-Id": str(effective_user_id),
                },
            )
        return response.status_code == 200
    except Exception as error:  # noqa: BLE001 - 登记失败如实标注
        logger.warning("repro job ownership record failed: %s", type(error).__name__)
        return False


async def _record_run_linkage(
    *, run_id: str, user_id: str, session_id: str,
    preset: dict[str, Any], approval_id: str, job_id: str,
    proposal_ref: dict[str, Any] | None = None,
    effective_preset: dict[str, Any] | None = None,
    frozen_snapshot: dict[str, Any] | None = None,
) -> bool:
    """NX-E1：向 Backend 登记 run linkage（恢复查询依据）。

    NX-N0/P1-A：提案票据的冻结配置快照只取核销时冻结体（frozen_snapshot，
    调用方 execute_approved_reproduction 在 consume 返回中携带）——本函数
    不再读取可变现行提案。frozen 缺失属内部不一致：保留提案 id/version
    引用但快照置空（恢复视图按 unknown 历史展示），并记 error 日志。
    普通票据快照为空（legacy preset 判定）。
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
    config_snapshot: dict[str, Any] = {}
    if proposal_ref:
        if isinstance(frozen_snapshot, dict) and frozen_snapshot.get("steps"):
            config_snapshot = {
                "proposal_id": frozen_snapshot.get("proposal_id", ""),
                "proposal_version": int(frozen_snapshot.get("version", 0) or 0),
                "preset_id": frozen_snapshot.get("preset_id", ""),
                "parameters": frozen_snapshot.get("parameters", {}),
                "environment": frozen_snapshot.get("environment", {}),
                "repo_revision": frozen_snapshot.get("repo_revision", ""),
                "revision_status": frozen_snapshot.get("revision_status", ""),
                "data": frozen_snapshot.get("data", {}),
                "steps": list(frozen_snapshot.get("steps") or []),
                "budget": frozen_snapshot.get("budget", {}),
                "metric_policy": frozen_snapshot.get("metric_policy", {}),
            }
        else:
            logger.error("run linkage missing frozen snapshot for proposal %s",
                         (proposal_ref or {}).get("proposal_id", ""))
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
                    "repo_url": preset.get("repo_url", ""),
                    "title": "",
                    "parent_run_id": "",
                    "proposal_id": (proposal_ref or {}).get("proposal_id", ""),
                    "proposal_version": int((proposal_ref or {}).get("proposal_version", 0) or 0),
                    "config_snapshot": config_snapshot,
                    "preset_display_name": str(preset.get("display_name", "")),
                    "paper_title": str(preset.get("paper_title", "")),
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
    view: dict[str, Any] = {
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
    # NX-LB2：提案绑定票据带出引用（浮窗展示版本/hash；冻结步骤本身不下发）。
    if row.get("proposal_id"):
        view["proposal_id"] = row["proposal_id"]
        view["proposal_version"] = row.get("proposal_version", 0)
        view["proposal_hash"] = row.get("proposal_hash", "")
    return view


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
    # NX-N0/P1-A：提案绑定票据只消费核销时冻结的快照（approval.frozen_proposal，
    # consume 内 CAS 锁定行内 full body）。不再读取可变现行提案——核销后任何
    # PATCH（锁拒绝）或绕过锁的修改都进不了执行载荷与登记快照；快照缺失则
    # fail-closed 拒绝执行。普通票据用预设 steps。
    effective = dict(preset)
    proposal_ref: dict[str, Any] = {}
    frozen_snapshot: dict[str, Any] | None = None
    if approval.get("proposal_id"):
        frozen = approval.get("frozen_proposal")
        if not isinstance(frozen, dict) or not frozen.get("steps"):
            raise approvals.ApprovalError(
                "APPROVAL_PROPOSAL_CHANGED", "批准绑定的冻结快照缺失，请重新走审批")
        effective = {**preset, "steps": list(frozen["steps"])}
        proposal_ref = {
            "proposal_id": frozen["proposal_id"],
            "proposal_version": int(frozen.get("version", 0) or 0),
        }
        frozen_snapshot = dict(frozen)
    try:
        result = await _submit_to_worker(effective)
        # M4-B1：提交成功（拿到 job_id）后登记归属，进度查询按发起人鉴权。
        # NX-G2：执行前的归属绑定已由审批记录承担；此处是提交后的 job 关联。
        # NX-E1：同时登记 run linkage（run_id=approval_id），供刷新/换设备恢复。
        if result.get("status") == "submitted":
            job_id = str((result.get("job") or {}).get("job_id", ""))
            if job_id:
                approvals.attach_job(approval_id, job_id)
                recorded = await _record_job_ownership(job_id, preset, user_id=user_id)
                result["ownership_recorded"] = recorded
                await _record_run_linkage(
                    run_id=approval_id, user_id=user_id, session_id=session_id,
                    preset=preset, approval_id=approval_id, job_id=job_id,
                    proposal_ref=proposal_ref, effective_preset=effective,
                    frozen_snapshot=frozen_snapshot,
                )
                # 提案票据执行成功→冻结提案版本（后续修改须走新提案；best-effort）。
                if proposal_ref:
                    from nexus import proposals as proposals_module

                    proposals_module.mark_proposal_executed(
                        proposal_ref["proposal_id"], proposal_ref["proposal_version"])
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
