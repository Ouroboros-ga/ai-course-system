"""T3 无 preset 入口：最小输入 → 自主提案（最小 SR1/N1）。

- `prepare(target, objective)`：目标（GitHub 仓库 / 论文引用）＋目标描述 →
  自主提案（kind=autonomous_experiment）＋可读摘要＋缺失的用户输入；
  只准备、不执行（Worker 零接触；执行是 T4 的事）。
- 来源记录复用现有附件与研究结果 Norwegian：paper/search 引用记入 sources；
  来源无全文时不冒充已读（abstract_only 诚实标注）。
- License 沿既有规则：GitHub API 的 SPDX 视为已核验；未知仓库不信任，
  未核验如实标注进 missing_inputs，不阻止先配置/试跑（执行前核验属 T4 门）。
- 不确定的依赖版本留给沙箱试验：只记录"识别到/未识别到环境声明"，不虚构
  "已配置成功"。
- 只有目标真正歧义且无法合理推断时才问（need_input，问题数 ≤3），不把
  每个字段做确认表单。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 服务端声明的默认资源与源策略（任务书 T3：默认资源来自服务端可用配置；
# 当前平台尚无容量配置表，此即声明值；容量核对在 T4 执行时进行）。
DEFAULT_RESOURCES: dict[str, Any] = {
    "cpu": 2.0,
    "memory_mb": 4096,
    "disk_mb": 10240,
    "wall_time_s": 3600,
}
DEFAULT_NETWORK_PROFILE = "pypi-allowed"
RESOURCE_SOURCE = "server-default"

_GITHUB_RE = re.compile(
    r"github\.com/([^/\s?#]+)/([^/\s?#]+?)(?:\.git)?(?:[/?#]|$)",
    re.IGNORECASE,
)
_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([^\s?#\"']+)", re.IGNORECASE)

_ENV_FILES = (
    "requirements.txt",
    "environment.yml",
    "environment.yaml",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
)
_README_NAMES = ("README.md", "README.rst", "README")
_FILE_CAP = 2048
_TOTAL_CAP = 8192


def infer_mode(text: str) -> str:
    """由目标描述推断 ExperimentScope.mode（setup/smoke/reproduce）。

    优先级 reproduce > smoke > setup > 默认 smoke（"配置环境并试跑"落 smoke）。
    """
    lowered = (text or "").lower()
    if any(k in lowered for k in ("复现", "reproduce", "指标", "metric")):
        return "reproduce"
    if any(k in lowered for k in ("试跑", "跑通", "smoke", "冒烟", "运行一下", "跑一下")):
        return "smoke"
    if any(k in lowered for k in ("配置", "安装", "setup", "环境", "依赖")):
        return "setup"
    return "smoke"


def parse_github_repo(url: str) -> tuple[str, str] | None:
    """解析 GitHub 仓库地址 → (owner, repo)；非 GitHub 返回 None。"""
    match = _GITHUB_RE.search(url or "")
    if not match:
        return None
    owner = match.group(1).strip()
    repo = match.group(2).strip()
    if not owner or not repo or owner in ("settings", "orgs", "search"):
        return None
    return owner, repo


def canonical_repo_url(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}"


class GitHubReader:
    """生产 Reader：只读 GitHub 公开信息（API＋raw 文件），不执行任何代码。

    全部 fail-soft：取不到的字段记 unknown/空，不抛异常（调用方按 reachable
    决定 need_input 还是继续）。fixture:// 等非 GitHub 来源一律不可达——
    fixture 只在测试 Reader 中处理，不进正式白名单。
    """

    def __init__(self, timeout_s: float = 10.0) -> None:
        self._timeout = timeout_s

    async def read_repo(self, repo_url: str) -> dict[str, Any]:
        import httpx

        parsed = parse_github_repo(repo_url or "")
        if parsed is None:
            return {"repo_url": repo_url or "", "reachable": False,
                    "reason": "首版仅支持 GitHub 公开仓库"}
        owner, repo = parsed
        canonical = canonical_repo_url(owner, repo)
        meta: dict[str, Any] = {
            "repo_url": canonical, "reachable": False,
            "readme": "", "env_files": {},
            "license": {"spdx": "", "status": "unknown"},
            "default_branch": "", "revision_sha": "",
        }
        headers = {"Accept": "application/vnd.github+json",
                   "User-Agent": "code-nexus-nexus-ai/0.1"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout,
                                         follow_redirects=True) as client:
                repo_resp = await client.get(
                    f"https://api.github.com/repos/{owner}/{repo}",
                    headers=headers)
                if repo_resp.status_code != 200:
                    meta["reason"] = f"GitHub API HTTP {repo_resp.status_code}"
                    return meta
                info = repo_resp.json()
                branch = str(info.get("default_branch") or "main")
                meta["default_branch"] = branch
                lic = info.get("license") or {}
                spdx = str(lic.get("spdx_id") or "")
                if spdx and spdx.upper() != "NOASSERTION":
                    meta["license"] = {"spdx": spdx, "status": "verified"}
                try:
                    br_resp = await client.get(
                        f"https://api.github.com/repos/{owner}/{repo}/branches/{branch}",
                        headers=headers)
                    if br_resp.status_code == 200:
                        sha = ((br_resp.json().get("commit") or {}).get("sha")) or ""
                        meta["revision_sha"] = str(sha)
                except Exception as error:  # noqa: BLE001 - SHA 取不到不致命
                    logger.warning("github branch sha failed: %s", type(error).__name__)
                total = 0
                for name in (*_README_NAMES, *_ENV_FILES):
                    if total >= _TOTAL_CAP:
                        break
                    try:
                        f_resp = await client.get(
                            f"https://raw.githubusercontent.com/{owner}/{repo}"
                            f"/{branch}/{name}")
                    except Exception:  # noqa: BLE001 - 单文件失败跳过
                        continue
                    if f_resp.status_code != 200:
                        continue
                    text = f_resp.text[:_FILE_CAP]
                    total += len(text)
                    if name in _README_NAMES and not meta["readme"]:
                        meta["readme"] = text
                    else:
                        meta["env_files"][name] = text
        except Exception as error:  # noqa: BLE001 - 网络失败即不可达
            logger.warning("github read failed: %s", type(error).__name__)
            meta["reason"] = f"读取失败（{type(error).__name__}）"
            return meta
        meta["reachable"] = True
        return meta


async def _default_repo_search(query: str) -> dict[str, Any]:
    """默认论文→仓库发现：web_search 找官方仓库链接（作者页无机器可读代码字段，
    搜 "<标题> github" 是诚实机制；只取 github.com 命中）。"""
    from nexus.tools.web_search import web_search as web_search_tool

    try:
        result = await web_search_tool.ainvoke({"query": query, "max_results": 5})
    except Exception as error:  # noqa: BLE001
        logger.warning("repo search failed: %s", type(error).__name__)
        return {"repo_url": None}
    items = result.get("results") or result.get("items") or []
    for item in items:
        url = str((item or {}).get("url") or (item or {}).get("href") or "")
        parsed = parse_github_repo(url)
        if parsed is not None:
            return {"repo_url": canonical_repo_url(*parsed),
                    "source": "web_search", "query": query}
    return {"repo_url": None}


def _need_input(target: str, questions: list[str]) -> dict[str, Any]:
    return {
        "status": "need_input",
        "target": target,
        "proposal": None,
        "questions": list(questions)[:3],
        "is_supplementary": True,
    }


@tool
async def prepare_experiment(target: str, objective: str = "") -> dict[str, Any]:
    """由论文/仓库与一句话目标准备自主实验提案（只准备、不执行）。

    target 可以是 GitHub 仓库地址、论文标题或 arXiv 编号；objective 如
    "配置环境并试跑"。命中已核验预设时指引走预设提案流；未知来源返回自主
    提案草案＋可读摘要＋缺失的用户输入。绝不执行任何代码、不提交 Worker。
    """
    from nexus.request_scope import current_session_id, current_user_id

    user_id = current_user_id() or ""
    session_id = current_session_id() or ""
    if not user_id or not session_id:
        return {
            "status": "error", "code": "SCOPE_MISSING",
            "detail": "缺少用户/会话上下文，无法创建提案。",
            "is_supplementary": True,
        }
    return await prepare(target, objective, user_id=user_id,
                         session_id=session_id)


async def prepare(
    target: str, objective: str = "", *, user_id: str = "", session_id: str = "",
    reader: Any | None = None,
    searcher: Callable[[str], Awaitable[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """由最小输入准备自主实验提案（只准备、不执行）。

    reader：RepoReader 替身点（默认 GitHubReader）；searcher：论文→仓库发现
    替身点（默认 web_search）。fixture:// 只被测试 Reader 识别。
    """
    from nexus import proposals as proposals_module
    from nexus.tools.reproduction import REPRO_PRESETS

    cleaned_target = (target or "").strip()
    cleaned_objective = (objective or "").strip()
    if not cleaned_target:
        return _need_input(cleaned_target, [
            "请提供论文标题、arXiv 链接或 GitHub 仓库地址，我来准备实验提案。",
            "这次想达到什么目标（配置环境 / 试跑 / 复现指标）？",
        ])
    # 已核验预设 → 走预设提案流，不建自主提案。
    key = cleaned_target.strip().lower()
    for candidate, preset in REPRO_PRESETS.items():
        if (candidate == key or key in preset["paper_title"].lower()
                or key in preset["repo_url"].lower()):
            return {
                "status": "known_preset",
                "preset_id": preset["preset_id"],
                "proposal": None,
                "next_step": (
                    "该目标有已核验预设，请用 create_reproduction_proposal "
                    f"（preset_id={preset['preset_id']}）建预设提案；"
                    "不要为它建自主提案。"
                ),
                "is_supplementary": True,
            }
    active_reader = reader if reader is not None else GitHubReader()
    using_default_reader = reader is None
    repo_url = ""
    paper_ref: dict[str, Any] = {}
    scheme = (cleaned_target.split("://", 1)[0].lower()
              if "://" in cleaned_target else "")
    if parse_github_repo(cleaned_target) is not None or (
            scheme == "fixture" and not using_default_reader):
        # GitHub 仓库直达；fixture:// 只被注入的测试 Reader 识别，
        # 不进正式来源白名单（默认 Reader 见下拒绝分支）。
        repo_url = cleaned_target
    elif scheme:
        return {
            "status": "rejected", "code": "TARGET_UNSUPPORTED",
            "detail": "不支持的实验来源（首版仅支持 GitHub 公开仓库与论文引用）。",
            "proposal": None, "is_supplementary": True,
        }
    else:
        # 论文/文本输入：先定论文引用，再找仓库。
        arxiv_id = _ARXIV_RE.search(cleaned_target)
        paper_ref = {
            "query": cleaned_target,
            "arxiv_id": arxiv_id.group(1) if arxiv_id else "",
            "source": "user",
        }
        search = searcher if searcher is not None else _default_repo_search
        try:
            found = await search(f"{cleaned_target} github")
        except Exception as error:  # noqa: BLE001
            logger.warning("paper repo search failed: %s", type(error).__name__)
            found = {"repo_url": None}
        repo_url = str((found or {}).get("repo_url") or "")
        if not repo_url:
            return _need_input(cleaned_target, [
                f"没有找到与“{cleaned_target[:60]}”关联的公开仓库链接；"
                "请直接给出 GitHub 仓库地址，或上传论文全文，我再准备提案。",
            ])
    try:
        meta = await active_reader.read_repo(repo_url)
    except Exception as error:  # noqa: BLE001 - Reader 异常按不可达处理
        logger.warning("repo read failed: %s", type(error).__name__)
        meta = {"repo_url": repo_url, "reachable": False}
    if not meta.get("reachable"):
        return _need_input(cleaned_target, [
            f"仓库 {repo_url[:80]} 读取失败（{meta.get('reason', '不可达')}）；"
            "请检查地址是否有误，或提供论文全文/换一个可公开访问的仓库。",
        ])
    mode = infer_mode(f"{cleaned_objective} {cleaned_target}")
    final_objective = cleaned_objective or f"配置环境并试跑（{meta['repo_url']}）"
    sha = str(meta.get("revision_sha") or "")
    license_info = meta.get("license") or {"spdx": "", "status": "unknown"}
    scope = {
        "objective": final_objective,
        "repo_url": meta["repo_url"],
        "repo_revision": sha,
        "source_refs": [paper_ref.get("query", "")] if paper_ref else [meta["repo_url"]],
        "data_refs": [],
        "network_profile": DEFAULT_NETWORK_PROFILE,
        "resources": dict(DEFAULT_RESOURCES),
        "mode": mode,
        "allow_environment_repair": True,
    }
    try:
        row = proposals_module.create_proposal(
            user_id=user_id or "", session_id=session_id or "",
            preset=None, kind="autonomous_experiment", scope=scope,
            license_info=license_info)
    except proposals_module.ProposalError as error:
        return {
            "status": "rejected", "code": error.code, "detail": str(error),
            "proposal": None, "is_supplementary": True,
        }
    missing_inputs: list[str] = []
    if license_info.get("status") != "verified":
        missing_inputs.append(
            "License 未核验（只读到了仓库信息，未确认允许复现用途；"
            "执行前需确认 License，T4 执行门会复查）。")
    if mode == "reproduce":
        missing_inputs.append("未识别公开数据声明（复现需数据：请补充数据集来源或确认用合成数据）。")
    notes: list[str] = []
    if not sha:
        notes.append("revision 未固定到 commit（分支 HEAD 在执行时解析，T4 会记录实际 SHA）。")
    env_files = meta.get("env_files") or {}
    if env_files:
        notes.append(f"识别到环境声明：{', '.join(sorted(env_files))}（版本不确定处留给沙箱试验，不虚构已配置成功）。")
    else:
        notes.append("未识别环境声明文件（requirements/environment.yml/pyproject 均无）；依赖版本留给沙箱试验确定。")
    if meta.get("readme"):
        notes.append("已读 README（摘要）；全文与数据入口在 T4 沙箱内复核。")
    else:
        notes.append("未读到 README；环境与数据入口留给沙箱试验时确认。")
    sources = [{"kind": "repo", "ref": meta["repo_url"]}]
    if paper_ref:
        sources.append({"kind": "paper", "ref": paper_ref.get("query", "")[:200],
                        "arxiv_id": paper_ref.get("arxiv_id", "")})
    return {
        "status": "success",
        "kind": "autonomous_experiment",
        "proposal": proposals_module.public_proposal_view(row),
        "scope": row["scope"],
        "summary": {
            "objective": row["objective"],
            "repo_url": meta["repo_url"],
            "repo_revision": sha or meta.get("default_branch", ""),
            "revision_pinned": bool(sha),
            "mode": mode,
            "resources": dict(row["budget"].get("resources", {})),
            "resource_source": RESOURCE_SOURCE,
            "data_refs": [],
            "license": dict(license_info),
            "notes": notes,
        },
        "sources": sources,
        "license": dict(license_info),
        "missing_inputs": missing_inputs,
        "next_step": (
            "提案已建为草案（未执行）。向用户展示目标＋公开数据来源＋资源摘要；"
            "用户在浮窗确认一次后按 T2 审批流执行。"
        ),
        "is_supplementary": True,
    }
