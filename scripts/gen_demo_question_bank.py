"""Demo 数据生成 · 阶段1：AI 出题建题库（解决"题库为 0"硬卡点）

在服务器 /opt/smartcarb/current/backend 环境下运行，复用项目自己的
question_generation_llm.generate_question_sync（真实 LLM，DeepSeek），
直接落 QuestionBankItem(status=published)。

设计要点：
- **幂等**：已覆盖的知识节点会跳过，可安全重跑；
- **容错**：单次 LLM 失败只跳过该节点，不中断整批；
- **脱敏**：只读取 env 文件用于注入环境变量，不打印任何密钥；
- **合规**：题目为 AI 生成并标记 ai_constrained，符合 AGENTS.md §4.1.5
  （外部生成内容标记来源、不冒充课程证据）。

用法（服务器）：
    /opt/smartcarb/shared/venvs/backend-py312/bin/python \
        /tmp/gen_demo_question_bank.py --target 130
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time

# ---------------------------------------------------------------- 环境注入
# 必须与 smartcarb-backend.service 的 EnvironmentFile 顺序一致，
# 否则数据库配置缺失会回退到 SQLite（服务器上实际是 PostgreSQL）。
ENV_FILES = [
    "/opt/smartcarb/shared/env/backend.env",
    "/opt/smartcarb/shared/env/database.env",
    "/opt/smartcarb/shared/env/runtime-paths.env",
]
for _env_file in ENV_FILES:
    if not os.path.exists(_env_file):
        continue
    with open(_env_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            # 直接覆盖，与 systemd 的"后者覆盖前者"语义保持一致
            os.environ[key.strip()] = value.strip().strip('"').strip("'")

BACKEND_DIR = "/opt/smartcarb/current/backend"
sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.models.database import engine  # noqa: E402
from app.models.question_bank_model import (  # noqa: E402
    QuestionBankItem,
    QuestionDifficulty,
    QuestionStatus,
    QuestionType,
)
from app.models.graph_production_model import CourseKnowledgeNode  # noqa: E402
from app.services.question_generation_llm import generate_question_sync  # noqa: E402

COURSE_ID = 15  # 课程「算法」：173 知识节点 + 已发布版本
DIFFICULTY_POOL = (
    [QuestionDifficulty.EASY] * 3
    + [QuestionDifficulty.MEDIUM] * 5
    + [QuestionDifficulty.HARD] * 2
)


def load_node_ids(session: Session, course_id: int) -> list[int]:
    """知识节点 ID 列表（ORM 查询，避免手写 SQL 的枚举大小写陷阱）。"""
    rows = session.exec(
        select(CourseKnowledgeNode.id)
        .where(CourseKnowledgeNode.course_id == course_id)
        .order_by(CourseKnowledgeNode.id)
    ).all()
    return [int(r) for r in rows]


def covered_node_ids(session: Session, course_id: int) -> set[int]:
    """已出题的节点（用于幂等跳过）。

    注意：status 在库里是 PG 原生 enum 且存的是**大写**标签，
    因此必须用 ORM 比较（交给 SQLAlchemy 处理），不能写 status='published'。
    """
    rows = session.exec(
        select(QuestionBankItem.knowledge_node_ids).where(
            QuestionBankItem.course_id == course_id,
            QuestionBankItem.status == QuestionStatus.PUBLISHED,
        )
    ).all()
    covered: set[int] = set()
    import json

    for raw in rows:
        try:
            ids = raw if isinstance(raw, list) else json.loads(raw or "[]")
            covered.update(int(i) for i in ids)
        except Exception:
            continue
    return covered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=130, help="目标题目数")
    parser.add_argument("--course-id", type=int, default=COURSE_ID)
    args = parser.parse_args()

    random.seed(20260908)
    ok = fail = skip = 0

    # 自检：确认连的是 PostgreSQL 而不是回退 SQLite（不打印完整 DSN，避免泄露口令）
    try:
        dialect = engine.url.get_backend_name()
    except Exception:
        dialect = "unknown"
    print(f"[info] 数据库方言: {dialect}")
    if dialect != "postgresql":
        print("[error] 未连接到 PostgreSQL，请检查 database.env 加载是否正确")
        return 1

    with Session(engine) as session:
        nodes = load_node_ids(session, args.course_id)
        done = covered_node_ids(session, args.course_id)
        pending = [n for n in nodes if n not in done]

        print(f"[info] 课程 {args.course_id} 知识节点 {len(nodes)} 个，"
              f"已覆盖 {len(done)} 个，待出题 {len(pending)} 个，目标 {args.target} 题")

        for idx, node_id in enumerate(pending, start=1):
            if ok >= args.target:
                print(f"[info] 已达目标 {args.target} 题，停止")
                break

            difficulty = random.choice(DIFFICULTY_POOL)
            try:
                gen = generate_question_sync(
                    session,
                    course_id=args.course_id,
                    node_id=node_id,
                    purpose="diagnose",
                    difficulty=difficulty.value,
                    cognitive_snapshot=None,
                    six_dimensions=None,
                    reason_codes=["demo_data_seed"],
                    question_signals=None,
                )
            except Exception as exc:  # 单次失败不中断
                fail += 1
                print(f"[warn] node={node_id} 出题异常: {type(exc).__name__}")
                continue

            question_text = (gen or {}).get("question_text") or ""
            if not question_text or len(question_text) < 8:
                skip += 1
                print(f"[warn] node={node_id} 题目为空/过短，跳过（LLM 可能不可用）")
                continue

            item = QuestionBankItem(
                question_text=question_text,
                answer=(gen or {}).get("answer") or "",
                options=(gen or {}).get("options") or {},
                question_type=QuestionType.SHORT_ANSWER,
                difficulty=difficulty,
                category=(gen or {}).get("category") or "",
                course_id=args.course_id,
                knowledge_node_ids=[node_id],
                status=QuestionStatus.PUBLISHED,
                generated_by="ai_constrained",
                generation_metadata={
                    "demo_seed": True,
                    "confidence": (gen or {}).get("confidence"),
                    "reason_codes": (gen or {}).get("reason_codes") or [],
                    "source": (gen or {}).get("source"),
                },
            )
            session.add(item)
            session.commit()
            ok += 1

            if idx % 10 == 0 or ok % 10 == 0:
                print(f"[progress] 已处理 {idx}/{len(pending)}，成功 {ok}，失败 {fail}，跳过 {skip}")
            time.sleep(0.2)  # 温和限速，避免打爆 LLM 端点

    print(f"[done] 新增题目 {ok} 条；失败 {fail}；跳过 {skip}")
    if ok == 0 and (fail or skip):
        print("[error] 未产出任何题目，请检查 LLM_API_KEY 是否配置、端点是否可达")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
