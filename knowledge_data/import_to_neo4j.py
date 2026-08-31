#!/usr/bin/env python3
"""CS 学科知识库 → 知识图谱导入计划（挑战杯 XH-202620）。

诚实边界：本脚本**不连接任何 Neo4j**，只做两件事：
1. 复用 validate.py 做 schema 与引用完整性校验（硬门，失败即退出 1）；
2. 打印可落地的导入计划：节点统计与标准 Cypher 语句模板，
   供后续 R2 阶段接线到课程知识图谱（CourseKnowledgeNode / GraphRelation）时使用。

    python knowledge_data/import_to_neo4j.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import json

from validate import validate

NODE_LABEL = "CSKnowledgeNode"
REL_LABEL = "CSKnowledgeRelation"

NODE_FILES = (
    "data_structures.json", "algorithms.json", "os.json", "net.json", "db.json",
    "se.json", "ml.json", "compiler.json", "arch.json", "discrete.json", "graphics.json",
)


def _main() -> int:
    errors = validate()
    if errors:
        print("导入计划中止：知识库校验未通过", file=sys.stderr)
        return 1

    here = Path(__file__).resolve().parent
    nodes = []
    for filename in NODE_FILES:
        with (here / filename).open("r", encoding="utf-8") as fh:
            nodes.extend(json.load(fh).get("nodes", []))

    print(f"=== 导入计划（未执行，仅预览）===")
    print(f"节点数: {len(nodes)}，关系数见 relations.json")
    print()
    print("-- 节点 Cypher 模板（循环执行）：")
    print(f"MERGE (n:{NODE_LABEL} {{id: $id}}) "
          f"SET n.name = $name, n.node_type = $node_type, n.course = $course")
    print()
    print("-- 关系 Cypher 模板（循环执行）：")
    print(f"MATCH (a:{NODE_LABEL} {{id: $from}}), (b:{NODE_LABEL} {{id: $to}}) "
          f"MERGE (a)-[r:{REL_LABEL} {{type: $relation_type}}]->(b) "
          f"SET r.note = $note")
    print()
    print("注：Neo4j 导入未接线；R2 将接入 CourseKnowledgeNode/GraphRelation 生产链路。")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
