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
            "pip install torch numpy transformers datasets tiktoken tqdm",
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
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{settings.repro_worker_url.rstrip('/')}/jobs",
            json=payload,
        )
        response.raise_for_status()
        return {
            "status": "submitted",
            "job": response.json(),
            "repo_url": preset["repo_url"],
            "repo_license": preset["repo_license"],
            "is_supplementary": True,
        }


@tool
async def run_reproduction(preset_id: str) -> dict[str, Any]:
    """把已核验预设的复现计划提交给专用 Repro Worker 执行。

    只接受 plan_reproduction 返回的预设 ID（如 "nanogpt"）；
    未知仓库不会被本工具执行。Worker 未配置/不可达时如实返回失败，
    不假造执行结果。
    """
    preset = REPRO_PRESETS.get(preset_id.strip().lower())
    if preset is None:
        return {
            "status": "rejected",
            "code": "UNKNOWN_PRESET",
            "detail": "只接受已核验预设（见 plan_reproduction 的 known_presets）。",
            "known_presets": list(REPRO_PRESETS.keys()),
        }
    try:
        return await _submit_to_worker(preset)
    except Exception as error:  # noqa: BLE001 - Worker 故障 fail-closed
        logger.warning("Repro Worker submit failed: %s", type(error).__name__)
        return {
            "status": "unavailable",
            "code": "REPRO_WORKER_UNAVAILABLE",
            "detail": f"Repro Worker 调用失败（{type(error).__name__}）；复现未执行。",
            "plan": preset,
            "is_supplementary": True,
        }
