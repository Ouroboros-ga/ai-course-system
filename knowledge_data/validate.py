#!/usr/bin/env python3
"""CS 学科垂类知识库校验脚本（挑战杯 XH-202620）。

校验 knowledge_data/ 下的学科知识 JSON：
1. schema_version 必须为 cs-knowledge/1.0；
2. 每个节点：id 全局唯一、name 非空、node_type 在允许集合内、
   definition 非空、source 含 title；
3. 每条关系：relation_type 在允许集合内，from/to 都能解析到某文件的节点；
4. 输出节点/关系统计。

纯标准库实现，不依赖任何第三方包，不写任何状态：
    python knowledge_data/validate.py
退出码：0 全部通过；1 存在错误（并打印每条错误）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCHEMA_VERSION = "cs-knowledge/1.0"

# 对齐 backend/app/domain/education_graph/enums.py::RelationType 语义子集
ALLOWED_RELATION_TYPES = {
    "prerequisite_of",
    "uses",
    "defines",
    "contrasts_with",
    "related_to",
    "supported_by",
    "contains",
    "part_of",
    "derives_from",
    "has_example",
    "tests",
    "causes",
    "appears_on",
    "explains",
    "uses_formula",
}

# 对齐 backend/app/domain/education_graph/enums.py::NodeType 语义子集
ALLOWED_NODE_TYPES = {
    "concept",
    "definition",
    "formula",
    "theorem",
    "method",
    "skill",
    "example",
    "exercise",
    "misconception",
    "learning_objective",
    "knowledge_point",
    "course",
    "chapter",
    "section",
    "page",
    "source_block",
}

NODE_FILES = ["data_structures.json", "algorithms.json", "os.json", "net.json", "db.json", "se.json", "ml.json", "compiler.json", "arch.json", "discrete.json", "graphics.json"]
RELATION_FILES = ["relations.json"]


def _load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate() -> list[str]:
    errors: list[str] = []
    here = Path(__file__).resolve().parent

    nodes: dict[str, dict] = {}  # id -> node
    node_sources: dict[str, str] = {}  # id -> 所属文件

    for filename in NODE_FILES:
        path = here / filename
        if not path.exists():
            errors.append(f"缺少节点文件: {filename}")
            continue
        data = _load(path)
        if data.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"{filename}: schema_version 应为 {SCHEMA_VERSION}")
        course = data.get("course", "")
        for idx, node in enumerate(data.get("nodes", [])):
            node_id = node.get("id", "")
            if not node_id:
                errors.append(f"{filename}[{idx}]: 缺少 id")
                continue
            if node_id in nodes:
                errors.append(f"{filename}: 节点 id 重复: {node_id}（首次出现在 {node_sources[node_id]}）")
            nodes[node_id] = node
            node_sources[node_id] = f"{filename}（课程: {course}）"
            if not node.get("name"):
                errors.append(f"{filename}: 节点 {node_id} 缺少 name")
            if node.get("node_type") not in ALLOWED_NODE_TYPES:
                errors.append(f"{filename}: 节点 {node_id} 的 node_type 非法: {node.get('node_type')!r}")
            if not node.get("definition"):
                errors.append(f"{filename}: 节点 {node_id} 缺少 definition")
            source = node.get("source") or {}
            if not source.get("title"):
                errors.append(f"{filename}: 节点 {node_id} 缺少 source.title（内容可追溯要求）")

    relation_count = 0
    for filename in RELATION_FILES:
        path = here / filename
        if not path.exists():
            errors.append(f"缺少关系文件: {filename}")
            continue
        data = _load(path)
        if data.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"{filename}: schema_version 应为 {SCHEMA_VERSION}")
        for idx, rel in enumerate(data.get("relations", [])):
            relation_count += 1
            rtype = rel.get("relation_type", "")
            if rtype not in ALLOWED_RELATION_TYPES:
                errors.append(f"{filename}[{idx}]: relation_type 非法: {rtype!r}")
            for endpoint in ("from", "to"):
                value = rel.get(endpoint, "")
                if value not in nodes:
                    errors.append(f"{filename}[{idx}]: {endpoint}={value!r} 找不到对应节点（可用 id: {sorted(nodes)[:5]}...）")

    if not errors:
        print(f"[OK] 节点 {len(nodes)} 个，关系 {relation_count} 条")
        by_file: dict[str, int] = {}
        for nid, fname in node_sources.items():
            by_file[fname.split("（")[0]] = by_file.get(fname.split("（")[0], 0) + 1
        for fname, count in sorted(by_file.items()):
            print(f"     {fname}: {count} 个节点")
        print("     relations.json: %d 条关系" % relation_count)
        print("校验通过：schema 合法、id 全局唯一、关系端点可解析、来源可追溯。")
    else:
        for err in errors:
            print(f"[ERROR] {err}", file=sys.stderr)
        print(f"校验失败：共 {len(errors)} 个错误", file=sys.stderr)
    return errors


if __name__ == "__main__":
    errors = validate()
    sys.exit(1 if errors else 0)
