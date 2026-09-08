"""CR6 上线前只读预检（corpus-preflight 的 Python 核心）。

服务器端入口是 ``deploy/scripts/corpus-preflight.sh``（读取受信任 env 后
调用本模块）；本模块也可直接运行，便于在已配置部署环境的主机上复查：

    python backend/scripts/corpus_preflight.py [--json]

输出单个 JSON 对象，字段名按计划 §CR6：

    schema_head / source_manifest / model_ready / model_fingerprint /
    dimension / model / fts / active_release / resource_margin /
    mutation_count / errors / warnings / ok

只读保证：数据库经**只读引擎**访问（SQLite ``mode=ro``；PostgreSQL
``default_transaction_read_only=on``），写语句会直接报错，不靠调用方自律；
其余检查只有文件 stat/读取与 loopback 健康探测。**不创建目录、不写数据库、
不调用回答模型、不下载模型**。``mutation_count`` 恒为 0，但它只是自报值——
验收测试用运行前后的数据库文件哈希 + 全表行数对比从外部证明没有写入
（见 ``backend/tests/discipline/test_corpus_preflight.py``）。

退出码：0=无阻断错误；2=存在阻断错误（``errors`` 非空）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import sys
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import urlparse

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

REPO_ROOT = BACKEND_ROOT.parent

PREFLIGHT_VERSION = "corpus-preflight/1"

DEFAULT_SOURCES_PATH = REPO_ROOT / "knowledge_data" / "corpus" / "rag" / "sources.json"
DEFAULT_MODEL_CONFIG_PATH = REPO_ROOT / "knowledge_data" / "corpus" / "rag" / "config.json"

#: 模型目录必须存在的文件（HF 布局；权重文件任一即可）。
MODEL_REQUIRED_FILES = ("config.json", "tokenizer.json", "tokenizer_config.json")
MODEL_WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin", "model.onnx")

#: 模型配置 JSON 的字段映射（与 serve_corpus_embedding.load_model_config 同口径）。
MODEL_CONFIG_FIELDS = {
    "model_id": "id",
    "revision": "revision",
    "files_hash": "files_hash",
    "tokenizer": "tokenizer",
    "pooling": "pooling",
    "prefixes": "prefixes",
    "dimension": "dimension",
    "max_length": "max_length",
}

_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", ""}


def _env(environ: Mapping[str, str], name: str, default: str = "") -> str:
    return str(environ.get(name) or default).strip()


def _settings_attr(name: str, default: Any = "") -> Any:
    """读 Settings 字段；无配置环境（或缺依赖）返回默认值，不抛错。"""
    try:
        from app.core.config import settings

        return getattr(settings, name, default)
    except Exception:  # noqa: BLE001 - 预检不因配置模块不可用而崩溃
        return default


def _resolve(environ: Mapping[str, str], env_name: str, setting_name: str,
             default: str = "") -> str:
    value = _env(environ, env_name)
    if value:
        return value
    value = str(_settings_attr(setting_name, "") or "").strip()
    return value or default


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _readonly_engine():
    """只读引擎：预检在结构上写不了库（不是靠调用方自律）。

    - SQLite：``mode=ro`` URI 连接（不经过应用引擎的 WAL PRAGMA 监听器）；
    - PostgreSQL：``default_transaction_read_only=on``，任何写语句直接报错。
    """
    import sqlite3

    from sqlalchemy import create_engine

    from app.models.database import DATABASE_URL

    if DATABASE_URL.startswith("sqlite"):
        path = DATABASE_URL.split(":///", 1)[-1]

        def _connect():
            return sqlite3.connect(f"file:{path}?mode=ro", uri=True,
                                   check_same_thread=False)

        return create_engine("sqlite://", creator=_connect)
    return create_engine(
        DATABASE_URL,
        connect_args={"options": "-c default_transaction_read_only=on"})


# ---------------------------------------------------------------------------
# 各检查段
# ---------------------------------------------------------------------------


def _check_schema_head(environ: Mapping[str, str],
                       errors: list[dict], warnings: list[dict]) -> dict:
    """Alembic 版本链：数据库当前 revision 必须命中唯一 head。"""
    result: dict[str, Any] = {"current": "", "heads": [], "ok": False}
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        script = ScriptDirectory.from_config(
            Config(str(BACKEND_ROOT / "alembic.ini")))
        result["heads"] = sorted(script.get_heads())
    except Exception as exc:  # noqa: BLE001 - 脚本目录不可读即阻断
        errors.append({"code": "SCHEMA_HEADS_UNREADABLE",
                       "detail": f"{type(exc).__name__}: {exc}"})
        return result
    if len(result["heads"]) != 1:
        errors.append({"code": "SCHEMA_MULTIPLE_HEADS",
                       "detail": f"alembic heads={result['heads']}（必须唯一）"})
        return result
    try:
        from sqlalchemy import text

        with _readonly_engine().connect() as conn:
            row = conn.execute(text("SELECT version_num FROM alembic_version")
                               ).fetchone()
        result["current"] = str(row[0]) if row else ""
    except Exception as exc:  # noqa: BLE001 - 数据库不可读即阻断
        errors.append({"code": "SCHEMA_UNAVAILABLE",
                       "detail": f"{type(exc).__name__}: {exc}"})
        return result
    result["ok"] = result["current"] == result["heads"][0]
    if not result["ok"]:
        errors.append({
            "code": "SCHEMA_HEAD_MISMATCH",
            "detail": f"库 revision={result['current']} ！= head="
                      f"{result['heads'][0]}（先 alembic upgrade head）",
        })
    return result


def _check_source_manifest(environ: Mapping[str, str],
                           errors: list[dict],
                           warnings: list[dict]) -> dict:
    """来源登记清单：文件可读、集合与部署源目录可用性如实统计。"""
    path = Path(_resolve(environ, "DISCIPLINE_SOURCE_MANIFEST", "",
                         str(DEFAULT_SOURCES_PATH)))
    result: dict[str, Any] = {
        "path": str(path), "sha256": "", "sets": [], "sources": 0,
        "source_root": _resolve(environ, "DISCIPLINE_SOURCE_ROOT",
                                "DISCIPLINE_SOURCE_ROOT"),
        "files_available": 0, "files_missing": 0, "ok": False,
    }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 清单不可读即阻断
        errors.append({"code": "SOURCE_MANIFEST_UNREADABLE",
                       "detail": f"{path}: {type(exc).__name__}: {exc}"})
        return result
    result["sha256"] = _sha256_file(path)
    sources = data.get("sources") if isinstance(data, dict) else None
    sets = data.get("sets") if isinstance(data, dict) else None
    result["sources"] = len(sources or [])
    result["sets"] = sorted((sets or {}).keys())
    if not sources or not sets:
        errors.append({"code": "SOURCE_MANIFEST_INVALID",
                       "detail": "sources/sets 为空"})
        return result
    root_value = result["source_root"]
    if not root_value:
        warnings.append({"code": "SOURCE_ROOT_UNSET",
                         "detail": "DISCIPLINE_SOURCE_ROOT 未配置，无法核对源文件"})
        result["ok"] = True
        return result
    root = Path(root_value)
    for item in sources:
        file_name = str((item or {}).get("file") or "")
        if file_name and (root / file_name).is_file():
            result["files_available"] += 1
        else:
            result["files_missing"] += 1
    result["ok"] = result["files_missing"] == 0
    if not result["ok"]:
        warnings.append({
            "code": "SOURCE_FILES_MISSING",
            "detail": f"{result['files_missing']} 个登记文件在 {root} 不存在",
        })
    return result


def _load_model_config(path: Path) -> dict[str, Any]:
    """模型配置 JSON → 指纹字段（缺字段保留空值，由调用方判定未冻结）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    model = data.get("model") if isinstance(data, dict) else None
    if not isinstance(model, dict):
        raise ValueError("配置缺少 model 节")
    return {key: model.get(src) for key, src in MODEL_CONFIG_FIELDS.items()}


def _probe_embedding_service(url: str, timeout: float = 5.0) -> dict:
    """loopback 健康探测（只读 GET /health）；失败如实返回错误码。"""
    import httpx

    body = httpx.get(url.rstrip("/") + "/health", timeout=timeout).json()
    return {"ready": bool(body.get("ready")),
            "model_fingerprint": str(body.get("model_fingerprint") or ""),
            "dimension": int(body.get("dimension") or 0)}


def _check_model(environ: Mapping[str, str], errors: list[dict],
                 warnings: list[dict]) -> tuple[dict, dict]:
    """模型：目录文件、冻结配置、指纹与维度（服务优先，配置兜底）。"""
    from app.platform.knowledge.corpus_embedding import (
        model_fingerprint_for,
        validate_model_config,
    )

    config_path = Path(_resolve(environ, "CORPUS_EMBEDDING_MODEL_CONFIG", "",
                                str(DEFAULT_MODEL_CONFIG_PATH)))
    model_dir = _resolve(environ, "CORPUS_EMBEDDING_MODEL_PATH",
                         "CORPUS_EMBEDDING_MODEL_PATH")
    url = _resolve(environ, "CORPUS_EMBEDDING_URL", "CORPUS_EMBEDDING_URL")

    model: dict[str, Any] = {"config_path": str(config_path),
                             "config_status": "", "path": model_dir,
                             "missing_files": [], "weight_file": "",
                             "source": "", "service_url": url}
    info: dict[str, Any] = {"model_ready": False, "model_fingerprint": "",
                            "dimension": 0}

    declared: dict[str, Any] = {}
    try:
        declared = _load_model_config(config_path)
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        model["config_status"] = str(raw.get("status") or "")
    except Exception as exc:  # noqa: BLE001 - 配置不可读即阻断
        errors.append({"code": "MODEL_CONFIG_UNREADABLE",
                       "detail": f"{config_path}: {type(exc).__name__}: {exc}"})

    if model_dir:
        root = Path(model_dir)
        model["missing_files"] = [
            name for name in MODEL_REQUIRED_FILES if not (root / name).is_file()]
        weight = next((name for name in MODEL_WEIGHT_FILES
                       if (root / name).is_file()), "")
        model["weight_file"] = weight
        if not weight:
            model["missing_files"].append("|".join(MODEL_WEIGHT_FILES))
        if model["missing_files"]:
            errors.append({
                "code": "MODEL_FILES_MISSING",
                "detail": f"{root} 缺少 {model['missing_files']}",
            })
    elif not url:
        errors.append({"code": "MODEL_UNAVAILABLE",
                       "detail": "CORPUS_EMBEDDING_MODEL_PATH 与 "
                                 "CORPUS_EMBEDDING_URL 均未配置"})

    config_fp = ""
    if declared:
        try:
            validate_model_config(declared)
        except Exception as exc:  # noqa: BLE001 - 声明与实现不一致即阻断
            errors.append({"code": "MODEL_CONFIG_INVALID",
                           "detail": f"{type(exc).__name__}: {exc}"})
        try:
            config_fp = model_fingerprint_for(declared)
            info["dimension"] = int(declared.get("dimension") or 0)
        except Exception as exc:  # noqa: BLE001 - 未冻结即阻断（不补默认值）
            errors.append({"code": "MODEL_CONFIG_UNFROZEN",
                           "detail": f"{type(exc).__name__}: {exc}"})

    service_fp = ""
    if url:
        host = urlparse(url).hostname or ""
        if host not in _LOOPBACK_HOSTS and not host.startswith("127."):
            errors.append({
                "code": "EMBEDDING_URL_NOT_LOOPBACK",
                "detail": f"{url} 非 loopback（模型服务只允许本机）",
            })
        try:
            health = _probe_embedding_service(url)
            service_fp = health["model_fingerprint"]
            if health["dimension"]:
                info["dimension"] = health["dimension"]
            if not health["ready"]:
                errors.append({"code": "MODEL_SERVICE_NOT_READY",
                               "detail": f"{url}/health ready=false"})
            model["source"] = "service"
        except Exception as exc:  # noqa: BLE001 - 服务不可达即阻断
            errors.append({"code": "MODEL_SERVICE_UNAVAILABLE",
                           "detail": f"{url}: {type(exc).__name__}: {exc}"})

    if service_fp and config_fp and service_fp != config_fp:
        errors.append({
            "code": "MODEL_FINGERPRINT_MISMATCH",
            "detail": f"服务 {service_fp} ！= 配置 {config_fp}（拒绝混算）",
        })
    info["model_fingerprint"] = service_fp or config_fp
    if not model["source"]:
        model["source"] = "config" if config_fp else ""

    blocking = {"MODEL_CONFIG_UNREADABLE", "MODEL_CONFIG_UNFROZEN",
                "MODEL_CONFIG_INVALID",
                "MODEL_FILES_MISSING", "MODEL_UNAVAILABLE",
                "MODEL_SERVICE_UNAVAILABLE", "MODEL_SERVICE_NOT_READY",
                "MODEL_FINGERPRINT_MISMATCH", "EMBEDDING_URL_NOT_LOOPBACK"}
    info["model_ready"] = bool(info["model_fingerprint"]) and not any(
        err["code"] in blocking for err in errors)
    return model, info


def _check_fts(environ: Mapping[str, str], release_object_key: str,
               errors: list[dict]) -> dict:
    """FTS 根目录：存在性、可写性、文件计数、当前版本对象是否落盘。"""
    from app.services.discipline_knowledge import corpus_index as index_svc

    root = index_svc.resolve_fts_root(_env(environ, "DISCIPLINE_FTS_ROOT") or None)
    result: dict[str, Any] = {
        "root": str(root), "exists": root.is_dir(),
        "writable": os.access(root, os.W_OK) if root.is_dir() else False,
        "files": 0, "release_object_key": release_object_key,
        "release_object_present": False, "ok": False,
    }
    if not result["exists"]:
        errors.append({"code": "FTS_ROOT_MISSING",
                       "detail": f"{root} 不存在（不得由预检创建）"})
        return result
    result["files"] = sum(1 for _ in root.rglob("*.sqlite3"))
    if release_object_key:
        result["release_object_present"] = (
            (root / release_object_key).is_file())
    result["ok"] = result["writable"]
    if not result["writable"]:
        errors.append({"code": "FTS_ROOT_NOT_WRITABLE",
                       "detail": f"{root} 不可写"})
    return result


def _check_active_release(environ: Mapping[str, str],
                          errors: list[dict]) -> dict:
    """当前发布指针与版本视图（无指针不是错误：上线前为空是正常态）。"""
    from app.services.discipline_knowledge import corpus_index as index_svc

    result: dict[str, Any] = {
        "release_id": "", "revision": 0, "status": "", "members": 0,
        "embedded": 0, "fts_object_key": "", "ok": False,
    }
    try:
        from sqlmodel import Session

        with Session(_readonly_engine()) as session:
            head = index_svc.read_head(session)
            result["revision"] = int(head.get("revision") or 0)
            if not head.get("release_id"):
                result["ok"] = True  # 尚未发布：如实报空，不算阻断
                return result
            view = index_svc.get_release(session, head["release_id"])
            counts = dict(view.get("counts") or {})
            result.update({
                "release_id": view["release_id"], "status": view["status"],
                "members": view["members"], "embedded": view["embedded"],
                "fts_object_key": counts.get("fts_object_key") or "",
            })
    except Exception as exc:  # noqa: BLE001 - 指针不可读即阻断
        errors.append({"code": "ACTIVE_RELEASE_UNAVAILABLE",
                       "detail": f"{type(exc).__name__}: {exc}"})
        return result
    result["ok"] = result["status"] == "ready"
    if not result["ok"]:
        errors.append({"code": "ACTIVE_RELEASE_NOT_READY",
                       "detail": f"{result['release_id']} status="
                                 f"{result['status']}"})
    return result


def _memory_available_mb() -> Optional[float]:
    try:
        import psutil

        return round(psutil.virtual_memory().available / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001 - 无 psutil 时退 /proc
        pass
    try:
        for line in Path("/proc/meminfo").read_text(
                encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return round(int(line.split()[1]) / 1024.0, 1)
    except Exception:  # noqa: BLE001 - 平台不支持即未知
        pass
    return None


def _check_resources(environ: Mapping[str, str], fts_root: Path) -> dict:
    """资源余量：CPU/内存/磁盘/端口占用（全部只读探测）。"""
    url = _resolve(environ, "CORPUS_EMBEDDING_URL", "CORPUS_EMBEDDING_URL")
    parsed = urlparse(url) if url else None
    host = (parsed.hostname if parsed and parsed.hostname else "127.0.0.1")
    port = int(parsed.port) if parsed and parsed.port else 8310
    listening = False
    try:
        with socket.create_connection((host, port), timeout=1.0):
            listening = True
    except OSError:
        listening = False
    disk_anchor = fts_root if fts_root.is_dir() else REPO_ROOT
    free = shutil.disk_usage(disk_anchor).free
    return {
        "cpu_count": os.cpu_count() or 0,
        "memory_available_mb": _memory_available_mb(),
        "disk_free_mb": round(free / (1024 * 1024), 1),
        "disk_anchor": str(disk_anchor),
        "embedding_host": host, "embedding_port": port,
        "embedding_port_listening": listening,
    }


def _check_repo() -> dict:
    """已部署代码版本（只读 git 探测；非仓库环境如实报空）。"""
    import subprocess

    def _git(*args: str) -> str:
        try:
            out = subprocess.run(
                ["git", "-C", str(REPO_ROOT), *args], check=False,
                capture_output=True, text=True, timeout=10)
            return out.stdout.strip() if out.returncode == 0 else ""
        except Exception:  # noqa: BLE001 - 无 git 即未知
            return ""

    return {"commit": _git("rev-parse", "HEAD"),
            "short": _git("rev-parse", "--short", "HEAD"),
            "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "root": str(REPO_ROOT)}


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def run(env: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """执行全部只读检查并返回报告（不打印、不退出）。"""
    environ: dict[str, str] = dict(os.environ)
    if env:
        environ.update({str(k): str(v) for k, v in env.items()})

    errors: list[dict] = []
    warnings: list[dict] = []

    schema_head = _check_schema_head(environ, errors, warnings)
    source_manifest = _check_source_manifest(environ, errors, warnings)
    model, model_info = _check_model(environ, errors, warnings)
    active_release = _check_active_release(environ, errors)
    fts = _check_fts(environ, active_release["fts_object_key"], errors)
    resource_margin = _check_resources(environ, Path(fts["root"]))

    return {
        "preflight_version": PREFLIGHT_VERSION,
        "repo": _check_repo(),
        "schema_head": schema_head,
        "source_manifest": source_manifest,
        "model_ready": model_info["model_ready"],
        "model_fingerprint": model_info["model_fingerprint"],
        "dimension": model_info["dimension"],
        "model": model,
        "fts": fts,
        "active_release": active_release,
        "resource_margin": resource_margin,
        "mutation_count": 0,
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="CR6 语料 RAG 上线只读预检（不写库/不建目录/不调模型）")
    parser.add_argument("--json", action="store_true",
                        help="输出 JSON（默认即 JSON，保留兼容）")
    args = parser.parse_args(argv)

    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=False))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
