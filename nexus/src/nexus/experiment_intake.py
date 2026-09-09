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
# F4：arXiv ID 形态（`arxiv:ID` 前缀与裸 ID；新旧编号规则）。
_ARXIV_ID_RE = re.compile(
    r"(?:arxiv\s*:\s*)?((?:\d{4}\.\d{4,5})(?:v\d+)?|[a-z\-]+(?:\.[a-z\-]+)?/\d{7}(?:v\d+)?)",
    re.IGNORECASE,
)
# F4：既有附件引用形（内容解析 defer 到 T4 沙箱 read_attachment，此处只记录）。
_ATTACHMENT_RE = re.compile(r"attachment\s*[:#]\s*([A-Za-z0-9\-_]{1,64})", re.IGNORECASE)

# F4：出网读取的安全边界（公开元数据/源码 hosts 白名单＋体量上限）。
_FETCH_ALLOWED_HOSTS = frozenset({
    "api.github.com", "raw.githubusercontent.com", "arxiv.org", "export.arxiv.org",
})
_FETCH_MAX_BYTES = 1024 * 1024
_FETCH_MAX_REDIRECTS = 3


def parse_paper_ref(text: str) -> dict[str, Any]:
    """F4：规范识别论文引用（arXiv URL/id、附件引用、标题文本）。

    返回 {kind, arxiv_id, url, query}；kind ∈ arxiv_url/arxiv_id/
    attachment/title。识别先于来源限制（arXiv URL 不再被 scheme 分支拒）。
    """
    cleaned = (text or "").strip()
    arxiv_url = _ARXIV_RE.search(cleaned)
    if arxiv_url:
        arxiv_id = arxiv_url.group(1).strip().rstrip(".pdf").rstrip("/")
        return {"kind": "arxiv_url", "arxiv_id": arxiv_id,
                "url": f"https://arxiv.org/abs/{arxiv_id}", "query": cleaned}
    # GitHub 形优先由调用方判定；此处只处理非仓库输入。
    if parse_github_repo(cleaned) is not None:
        return {"kind": "github", "arxiv_id": "", "url": "", "query": cleaned}
    arxiv_id_match = _ARXIV_ID_RE.search(cleaned)
    if arxiv_id_match and len(cleaned) <= 120:
        arxiv_id = arxiv_id_match.group(1)
        return {"kind": "arxiv_id", "arxiv_id": arxiv_id,
                "url": f"https://arxiv.org/abs/{arxiv_id}", "query": cleaned}
    attachment = _ATTACHMENT_RE.search(cleaned)
    if attachment:
        return {"kind": "attachment", "arxiv_id": "",
                "url": "", "query": cleaned,
                "attachment_id": attachment.group(1)}
    return {"kind": "title", "arxiv_id": "", "url": "", "query": cleaned}

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
        try:
            async with httpx.AsyncClient(timeout=self._timeout,
                                         follow_redirects=True,
                                         max_redirects=_FETCH_MAX_REDIRECTS) as client:
                info_resp = await _checked_get(
                    client, f"https://api.github.com/repos/{owner}/{repo}",
                    self._timeout)
                if info_resp is None:
                    meta["reason"] = "GitHub API 不可达/拒绝"
                    return meta
                info = info_resp.json()
                branch = str(info.get("default_branch") or "main")
                meta["default_branch"] = branch
                lic = info.get("license") or {}
                spdx = str(lic.get("spdx_id") or "")
                if spdx and spdx.upper() != "NOASSERTION":
                    meta["license"] = {"spdx": spdx, "status": "verified"}
                # F4：先固定 SHA，后续 README/环境文件全部按同 SHA 读取
                # （分支滑动不再导致读到混合版本）。
                sha_resp = await _checked_get(
                    client,
                    f"https://api.github.com/repos/{owner}/{repo}/branches/{branch}",
                    self._timeout)
                sha = ""
                if sha_resp is not None:
                    try:
                        sha = str(((sha_resp.json().get("commit") or {}).get("sha")) or "")
                    except Exception:  # noqa: BLE001 - 解析失败即未固定
                        sha = ""
                meta["revision_sha"] = sha
                ref = sha or branch
                total = 0
                for name in (*_README_NAMES, *_ENV_FILES):
                    if total >= _TOTAL_CAP:
                        break
                    f_resp = await _checked_get(
                        client,
                        f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{name}",
                        self._timeout)
                    if f_resp is None:
                        continue
                    raw = f_resp.text
                    truncated = len(raw) > _FILE_CAP
                    text = raw[:_FILE_CAP]
                    total += len(text)
                    if name in _README_NAMES and not meta["readme"]:
                        meta["readme"] = text
                        if truncated:
                            meta.setdefault("truncated_files", []).append(name)
                    elif name not in _README_NAMES:
                        meta["env_files"][name] = {
                            "text": text, "truncated": truncated, "sha": ref}
        except Exception as error:  # noqa: BLE001 - 网络失败即不可达
            logger.warning("github read failed: %s", type(error).__name__)
            meta["reason"] = f"读取失败（{type(error).__name__}）"
            return meta
        meta["reachable"] = True
        return meta

    async def read_file_at_sha(self, repo_url: str, path: str, *,
                               sha: str = "", offset: int = 0,
                               limit: int = _FILE_CAP) -> dict[str, Any]:
        """F4：按固定 SHA 分段续读文件（截断状态可见）。

        返回 {text, truncated, sha, offset}；读不到即 reachable=False。
        未见≠不存在——调用方须据 truncated 决定是否续读(offset+limit)。
        """
        import httpx

        parsed = parse_github_repo(repo_url or "")
        if parsed is None:
            return {"reachable": False, "reason": "非 GitHub 仓库"}
        owner, repo = parsed
        cleaned_path = (path or "").strip().strip("/")
        if not cleaned_path or ".." in cleaned_path.split("/"):
            return {"reachable": False, "reason": "非法路径"}
        try:
            offset = max(0, int(offset or 0))
            limit = max(1, min(int(limit or _FILE_CAP), 65536))
        except (TypeError, ValueError):
            return {"reachable": False, "reason": "非法分段参数"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout,
                                         follow_redirects=True,
                                         max_redirects=_FETCH_MAX_REDIRECTS) as client:
                if not sha:
                    info_resp = await _checked_get(
                        client, f"https://api.github.com/repos/{owner}/{repo}",
                        self._timeout)
                    branch = "main"
                    if info_resp is not None:
                        try:
                            branch = str(info_resp.json().get("default_branch") or "main")
                        except Exception:  # noqa: BLE001
                            pass
                    br_resp = await _checked_get(
                        client,
                        f"https://api.github.com/repos/{owner}/{repo}/branches/{branch}",
                        self._timeout)
                    if br_resp is not None:
                        try:
                            sha = str(((br_resp.json().get("commit") or {}).get("sha")) or "")
                        except Exception:  # noqa: BLE001
                            sha = ""
                ref = sha or "main"
                f_resp = await _checked_get(
                    client,
                    f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{cleaned_path}",
                    self._timeout, max_bytes=limit + offset + 16)
                if f_resp is None:
                    return {"reachable": False, "reason": "文件不可读"}
                raw = f_resp.text
                window = raw[offset:offset + limit]
                return {"reachable": True, "text": window,
                        "truncated": len(raw) > offset + limit,
                        "sha": ref, "offset": offset}
        except Exception as error:  # noqa: BLE001
            logger.warning("github file read failed: %s", type(error).__name__)
            return {"reachable": False, "reason": f"读取失败（{type(error).__name__}）"}


async def _checked_get(client: Any, url: str, timeout_s: float,
                       max_bytes: int = _FETCH_MAX_BYTES) -> Any | None:
    """F4：受控出网读取（host 白名单＋体量上限；违例即 None，不抛）。

    重定向由调用方 client 的 follow 行为承担（上限见构造）；此处校验最终
    host 落在白名单内，且先看 content-length 拒绝超大体（防内存撑爆）。
    """
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower()
    if host not in _FETCH_ALLOWED_HOSTS:
        logger.warning("fetch blocked off-allowlist host: %s", host)
        return None
    try:
        response = await client.get(url)
    except Exception as error:  # noqa: BLE001
        logger.warning("fetch failed for %s: %s", host, type(error).__name__)
        return None
    try:
        final_host = (urlsplit(str(response.url)).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return None
    if final_host not in _FETCH_ALLOWED_HOSTS:
        logger.warning("fetch redirected off-allowlist: %s", final_host)
        return None
    if response.status_code != 200:
        return None
    try:
        length = response.headers.get("content-length")
        if length is not None and int(length) > max_bytes:
            logger.warning("fetch body too large for %s: %s", host, length)
            return None
    except (TypeError, ValueError):
        pass
    return response


async def _fetch_paper_code_links(arxiv_id: str, timeout_s: float = 10.0) -> list[str]:
    """F4：论文页明确代码链接优先（arXiv abs 页的 GitHub 外链）。

    返回去重后的规范仓库地址（≤3）；失败即空（搜索候选兜底，不抛）。
    """
    import httpx

    arxiv_id = (arxiv_id or "").strip()
    if not arxiv_id:
        return []
    links: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True,
                                     max_redirects=_FETCH_MAX_REDIRECTS) as client:
            response = await _checked_get(
                client, f"https://arxiv.org/abs/{arxiv_id}", timeout_s,
                max_bytes=512 * 1024)
            if response is None:
                return []
            html = response.text
    except Exception as error:  # noqa: BLE001
        logger.warning("arxiv page fetch failed: %s", type(error).__name__)
        return []
    for match in _GITHUB_RE.finditer(html or ""):
        parsed = parse_github_repo(match.group(0))
        if parsed is None:
            continue
        canonical = canonical_repo_url(*parsed)
        if canonical not in links:
            links.append(canonical)
        if len(links) >= 3:
            break
    return links


async def _fetch_arxiv_meta(arxiv_id: str, timeout_s: float = 10.0) -> dict[str, Any]:
    """F4：arXiv API 取标题/作者（关联核验用；失败即空，不抛）。"""
    import httpx

    arxiv_id = (arxiv_id or "").strip()
    if not arxiv_id:
        return {}
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=True,
                                     max_redirects=_FETCH_MAX_REDIRECTS) as client:
            response = await _checked_get(
                client,
                "https://export.arxiv.org/api/query?id_list="
                f"{arxiv_id}&max_results=1",
                timeout_s, max_bytes=256 * 1024)
            if response is None:
                return {}
            text = response.text
    except Exception as error:  # noqa: BLE001
        logger.warning("arxiv api fetch failed: %s", type(error).__name__)
        return {}
    title = ""
    authors: list[str] = []
    title_match = re.search(r"<title>(.*?)</title>", text or "", re.DOTALL)
    if title_match:
        title = re.sub(r"\s+", " ", title_match.group(1)).strip()
    for author_match in re.finditer(
            r"<author>\s*<name>(.*?)</name>", text or "", re.DOTALL):
        authors.append(re.sub(r"\s+", " ", author_match.group(1)).strip())
    # 首个 <title> 是 feed 标题，第二个才是条目标题。
    titles = [re.sub(r"\s+", " ", part).strip() for part in re.findall(
        r"<title>(.*?)</title>", text or "", re.DOTALL)]
    entry_title = titles[1] if len(titles) > 1 else (titles[0] if titles else "")
    return {"title": entry_title or title, "authors": authors[:8]}


def verify_repo_paper_link(readme: str, paper: dict[str, Any]) -> dict[str, Any]:
    """F4：仓库—论文关联核验（确定性信号分级，可单测）。

    strong：README 含 arXiv ID；weak：含标题实词（≥3 个长度≥4 的词命中）；
    否则 none。信号本身不是"作者仓库"证明，排序只用于候选取舍。
    """
    text = (readme or "").lower()
    arxiv_id = str((paper or {}).get("arxiv_id") or "").lower()
    if arxiv_id and arxiv_id.split("v")[0] in text:
        return {"level": "strong", "reason": "README 含 arXiv ID"}
    title = str((paper or {}).get("title") or "")
    words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", title)]
    hits = sum(1 for word in words if word in text)
    if len(words) >= 3 and hits >= 3:
        return {"level": "weak", "reason": f"README 含标题实词 {hits}/{len(words)}"}
    return {"level": "none", "reason": "无标题/ID 关联信号"}


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


def _normalize_candidates(found: Any, code_links: list[str]) -> list[dict[str, Any]]:
    """F4：搜索结果归一为候选清单（论文页链接优先，去重，≤5）。

    只收集、不判定：非 GitHub 命中也保留为候选，来源过滤发生在核验读
    （正式 Reader 拒非 GitHub；测试 Reader 认 fixture）。兼容旧 searcher
    形状 {"repo_url": ...}（单候选，来源 web_search）。
    """
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _push(url: str, source: str) -> None:
        url = (url or "").strip()
        if not url or url in seen or len(candidates) >= 5:
            return
        parsed = parse_github_repo(url)
        seen.add(url)
        candidates.append({
            "repo_url": canonical_repo_url(*parsed) if parsed else url,
            "source": source,
        })

    for url in code_links or []:
        _push(url, "paper-page")
    raw_list: list[Any] = []
    if isinstance(found, dict):
        if isinstance(found.get("candidates"), list):
            raw_list = list(found["candidates"])
        elif found.get("repo_url"):
            raw_list = [{"repo_url": found.get("repo_url")}]
    for item in raw_list:
        if isinstance(item, str):
            _push(item, "web_search")
        else:
            _push(str((item or {}).get("repo_url") or (item or {}).get("url") or ""),
                  "web_search")
    return candidates


async def _pick_verified_candidate(
    candidates: list[dict[str, Any]], paper: dict[str, Any], reader: Any,
) -> tuple[str, str] | None:
    """F4：候选核验取舍 → (repo_url, source)，无确证即 None（调用方询问）。

    - 论文页明确链接＋可达 → 直接取（作者自陈，最强）；
    - 其余候选逐个读＋关联信号：strong → 取；
    - 单个 weak/none 或多个候选 → None（有歧义，问用户，不默认首个）。
    """
    reachable: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for candidate in candidates:
        try:
            meta = await reader.read_repo(candidate["repo_url"])
        except Exception:  # noqa: BLE001 - 单候选失败跳过，不否决全局
            logger.warning("candidate read failed: %s", candidate["repo_url"])
            continue
        if not (meta or {}).get("reachable"):
            continue
        reachable.append((candidate, meta))
    for candidate, _meta in reachable:
        if candidate.get("source") == "paper-page":
            return candidate["repo_url"], "paper-page"
    for candidate, meta in reachable:
        signal = verify_repo_paper_link(str(meta.get("readme") or ""), paper)
        if signal["level"] == "strong":
            return candidate["repo_url"], "verified-strong"
    return None


_DATA_URL_RE = re.compile(r"https?://[^\s\"'<>`]+", re.IGNORECASE)
_DATA_EXTS = (".csv", ".tsv", ".jsonl", ".json", ".zip", ".tar.gz", ".tgz",
              ".parquet", ".h5", ".hdf5", ".pt", ".pth", ".bin", ".txt")


def _extract_data_links(*texts: str) -> list[dict[str, str]]:
    """F4：README/环境文本中的公开数据链接提取（去重，≤10）。

    kind：huggingface/kaggle/github-release/zenodo-doi/url。只提取、不下载；
    许可/大小以文本声明为准（无声明即 unknown，不编造）。
    """
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for text in texts:
        for match in _DATA_URL_RE.finditer(text or ""):
            url = match.group(0).rstrip(".,;)]")
            low = url.lower()
            if url in seen or len(url) > 500:
                continue
            if "github.com" in low and not (
                    "/releases/download" in low or "/raw/" in low
                    or low.endswith(_DATA_EXTS)):
                continue
            if "arxiv.org" in low or "pypi.org" in low:
                continue
            if "huggingface.co" in low:
                kind = "huggingface"
            elif "kaggle.com" in low:
                kind = "kaggle"
            elif "doi.org" in low or "zenodo.org" in low:
                kind = "zenodo-doi"
            elif "releases/download" in low or low.endswith(_DATA_EXTS):
                kind = "github-release"
            else:
                kind = "url"
            seen.add(url)
            found.append({"url": url, "kind": kind})
            if len(found) >= 10:
                return found
    return found


async def _probe_link(url: str, timeout_s: float = 5.0) -> str:
    """F4：链接可用性 HEAD 探测（reachable/unreachable/unknown，不抛）。

    unknown＝探不出（异常/超时/非 2xx-3xx 之外的状态），调用方不得把
    unknown 当失败，也不得当成功。任意 URL 先验目标 IP（内网/回环/
    链路本地/组播/保留一律 unknown，不发包；TOCTOU 残留风险见文档）。
    """
    import httpx

    if not _is_public_http_url(url):
        return "unknown"
    try:
        async with httpx.AsyncClient(timeout=timeout_s,
                                     follow_redirects=True,
                                     max_redirects=_FETCH_MAX_REDIRECTS) as client:
            response = await client.head(url)
            if response.status_code < 400:
                return "reachable"
            if response.status_code in (401, 403):
                return "unreachable"
            return "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _is_public_http_url(url: str) -> bool:
    """F4：SSRF 底线（纯函数，可单测）：只放行可解析到公网 IP 的 http(s)。

    失败（DNS 异常/非 IP/私网段）一律 False。DNS-TOCTOU（解析与连接时
    结果不一致）残留：探测只读 HEAD、无副作用、无凭据，风险接受并记录。
    """
    import ipaddress
    import socket
    from urllib.parse import urlsplit

    try:
        parts = urlsplit(url or "")
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return False
        address = socket.gethostbyname(parts.hostname)
        ip = ipaddress.ip_address(address)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_multicast or ip.is_reserved or ip.is_unspecified)
    except Exception:  # noqa: BLE001 - 解析失败即不放行
        return False


async def collect_data_refs(*texts: str) -> tuple[list[str], list[dict[str, Any]]]:
    """F4：提取＋探测 → (urls, records[{url,kind,availability}])。

    私有/不可达不阻塞：照常返回记录，调用方继续环境准备并指出真正阻塞；
    绝不用合成数据替换（替换须用户明确确认，见 missing_inputs 文案）。
    """
    import asyncio as _asyncio

    links = _extract_data_links(*texts)
    if not links:
        return [], []
    availability = await _asyncio.gather(
        *(_probe_link(item["url"]) for item in links[:6]))
    records: list[dict[str, Any]] = []
    for item, state in zip(links, list(availability) + ["unknown"] * len(links)):
        records.append({"url": item["url"], "kind": item["kind"],
                        "availability": state, "license": "unknown"})
    for item in links[6:]:
        records.append({"url": item["url"], "kind": item["kind"],
                        "availability": "unknown", "license": "unknown"})
    return [item["url"] for item in links], records


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
    repo_source = "direct"
    paper_ref: dict[str, Any] = {}
    scheme = (cleaned_target.split("://", 1)[0].lower()
              if "://" in cleaned_target else "")
    if parse_github_repo(cleaned_target) is not None or (
            scheme == "fixture" and not using_default_reader):
        # GitHub 仓库直达；fixture:// 只被注入的测试 Reader 识别，
        # 不进正式来源白名单（默认 Reader 见下拒绝分支）。
        repo_url = cleaned_target
    elif scheme == "fixture" and using_default_reader:
        return {
            "status": "rejected", "code": "TARGET_UNSUPPORTED",
            "detail": "不支持的实验来源（首版仅支持 GitHub 公开仓库与论文引用）。",
            "proposal": None, "is_supplementary": True,
        }
    else:
        # F4：论文/文本/arXiv/附件输入 → 论文引用 → 候选仓库（论文页明确
        # 链接优先，搜索只产生候选）→ 关联核验 → 取舍，不自动认首个命中。
        paper = parse_paper_ref(cleaned_target)
        if paper["kind"] == "github":
            # 带杂质的 GitHub 文本（如 "看看这个 github.com/a/b"）：已在上
            # 分支直达；到此说明 parse 失败，归入标题流由搜索处理。
            paper = {"kind": "title", "arxiv_id": "", "url": "",
                     "query": cleaned_target}
        if scheme in ("http", "https") and paper["kind"] not in (
                "arxiv_url", "arxiv_id"):
            # 非 GitHub/arXiv 的 http(s) 外链不在首版来源内。
            return {
                "status": "rejected", "code": "TARGET_UNSUPPORTED",
                "detail": "不支持的实验来源（首版仅支持 GitHub 公开仓库与论文引用）。",
                "proposal": None, "is_supplementary": True,
            }
        if paper["kind"] == "github":
            # 带杂质的 GitHub 文本（如 "看看这个 github.com/a/b"）：已在上
            # 分支直达；到此说明 parse 失败，归入标题流由搜索处理。
            paper = {"kind": "title", "arxiv_id": "", "url": "",
                     "query": cleaned_target}
        if paper["kind"] == "attachment":
            paper_ref = {"query": cleaned_target, "arxiv_id": "",
                         "source": "user",
                         "attachment_id": paper.get("attachment_id", ""),
                         "attachment_note": "附件内容解析 defer 到 T4 沙箱；"
                                            "此处只记录引用，不冒充已读。"}
            return _need_input(cleaned_target, [
                "已记录附件引用（T4 沙箱内读取全文）；请再给出该论文对应的 "
                "GitHub 仓库地址，我来固定版本并准备提案。",
            ])
        paper_ref = {"query": paper["query"], "arxiv_id": paper["arxiv_id"],
                     "source": "user"}
        if paper["kind"] in ("arxiv_url", "arxiv_id") and paper["arxiv_id"]:
            paper_ref["url"] = paper["url"]
            code_links = await _fetch_paper_code_links(paper["arxiv_id"])
            meta_info = await _fetch_arxiv_meta(paper["arxiv_id"])
            if meta_info.get("title"):
                paper_ref["title"] = meta_info["title"]
            if meta_info.get("authors"):
                paper_ref["authors"] = meta_info["authors"]
        else:
            code_links = []
            if paper["kind"] == "title":
                paper_ref["title"] = cleaned_target[:200]
        search = searcher if searcher is not None else _default_repo_search
        try:
            found = await search(f"{cleaned_target} github")
        except Exception as error:  # noqa: BLE001
            logger.warning("paper repo search failed: %s", type(error).__name__)
            found = {"repo_url": None}
        candidates = _normalize_candidates(found, code_links)
        if not candidates:
            return _need_input(cleaned_target, [
                f"没有找到与“{cleaned_target[:60]}”关联的公开仓库链接；"
                "请直接给出 GitHub 仓库地址，或上传论文全文，我再准备提案。",
            ])
        picked = await _pick_verified_candidate(
            candidates, paper_ref, active_reader)
        if picked is None:
            listed = "；".join(
                f"{i + 1}. {c['repo_url']}（{c['source']}）"
                for i, c in enumerate(candidates[:3]))
            return _need_input(cleaned_target, [
                f"找到 {len(candidates)} 个候选仓库，均无确证关联（论文页无明确"
                f"链接且 README 无标题/ID 信号）：{listed}。请确认用哪一个"
                "（回复编号或直接给 GitHub 直链），不要默认首个即作者仓库。",
            ])
        repo_url, repo_source = picked
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
    env_files = meta.get("env_files") or {}
    # F4：公开数据提取＋探测（阻塞只指出，不替换；合成须用户确认）。
    data_urls, data_records = await collect_data_refs(
        str(meta.get("readme") or ""),
        *[str(content if isinstance(content, str)
              else (content or {}).get("text", "")) for content in env_files.values()])
    truncated_files = sorted(
        name for name, content in env_files.items()
        if isinstance(content, dict) and content.get("truncated"))
    env_manifest = {
        "read_at_sha": sha,
        "read_at_branch": str(meta.get("default_branch") or ""),
        "env_files_detected": sorted(env_files),
        "truncated_files": truncated_files,
        "data_sources": data_records,
        "repo_source": repo_source,
        "paper": {key: paper_ref.get(key) for key in
                  ("arxiv_id", "title", "authors", "url") if paper_ref.get(key)},
    }
    scope = {
        "objective": final_objective,
        "repo_url": meta["repo_url"],
        "repo_revision": sha,
        "source_refs": [paper_ref.get("query", "")] if paper_ref else [meta["repo_url"]],
        "data_refs": data_urls,
        "network_profile": DEFAULT_NETWORK_PROFILE,
        "resources": dict(DEFAULT_RESOURCES),
        "mode": mode,
        "allow_environment_repair": True,
        "env_manifest": env_manifest,
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
    if mode == "reproduce" and not data_urls:
        missing_inputs.append("未识别公开数据声明（复现需数据：请补充数据集来源或明确确认用合成数据代替；不会默默替换）。")
    notes: list[str] = []
    if not sha:
        notes.append("revision 未固定到 commit（分支 HEAD 在执行时解析，T4 会记录实际 SHA）。")
    else:
        notes.append(f"已固定 {sha[:12]}；README/环境文件均按同 SHA 读取（分段续读见 read_file_at_sha）。")
    if truncated_files:
        notes.append(f"以下文件被截断只读前 {_FILE_CAP} 字节：{', '.join(truncated_files)}；"
                     "未见即未断言不存在，T4 沙箱内按需续读。")
    if env_files:
        notes.append(f"识别到环境声明：{', '.join(sorted(env_files))}（版本不确定处留给沙箱试验，不虚构已配置成功）。")
    else:
        notes.append("未识别环境声明文件（requirements/environment.yml/pyproject 均无）；依赖版本留给沙箱试验确定。")
    if data_records:
        verified = sum(1 for record in data_records if record["availability"] == "reachable")
        notes.append(f"识别到 {len(data_records)} 个公开数据链接（可达 {verified}，其余未知/不可达；"
                     "私有不可得不阻塞环境准备，真正阻塞见 missing_inputs）。")
    if meta.get("readme"):
        notes.append("已读 README（摘要）；全文与数据入口在 T4 沙箱内复核。")
    else:
        notes.append("未读到 README；环境与数据入口留给沙箱试验时确认。")
    if repo_source != "direct":
        notes.append(f"仓库来源：{repo_source}（论文页明确链接/强关联核验，非默认首个命中）。")
    sources = [{"kind": "repo", "ref": meta["repo_url"], "source": repo_source}]
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
            "data_refs": list(data_urls),
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
