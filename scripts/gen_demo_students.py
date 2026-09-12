"""Demo 数据生成 · 阶段2-7：学生账号 / 选课 / 学习进度 / 答题 / AI 问答 / 六维重算

与 gen_demo_question_bank.py 配套，在服务器 backend 环境运行。

- 学号规则：专业(0417/0418) + 级(25) + 班(01-05) + 序号(01-06) = 10 位，共 60 人
- 学习进度 / 答题正确率 / 提示依赖 / 提问深度 均按正态分布（Box-Muller）生成
- AI 问答：真实调用 DeepSeek（llm_client.simple_chat）生成回答；提问深度用
  确定性规则标定（概念解释/应用/误区三类），记录来源 teaching_agent
- 全部为合成数据（假名），符合 AGENTS.md §4.1.2

用法（分阶段，可重跑、幂等）：
    python gen_demo_students.py --stage accounts   # 建账号 + 选课
    python gen_demo_students.py --stage progress   # 学习进度
    python gen_demo_students.py --stage attempts   # 答题记录
    python gen_demo_students.py --stage qa         # AI 问答 + 六维重算
"""
from __future__ import annotations

import argparse
import asyncio
import math
import os
import random
import sys

# ---------------------------------------------------------------- 环境注入（与后端服务一致）
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
            os.environ[key.strip()] = value.strip().strip('"').strip("'")

BACKEND_DIR = "/opt/smartcarb/current/backend"
sys.path.insert(0, BACKEND_DIR)

from sqlmodel import Session, select  # noqa: E402

from app.core.security import get_password_hash  # noqa: E402
from app.models.database import engine  # noqa: E402
from app.models.user_model import User, UserRole  # noqa: E402
from app.models.course_model import StudentEnrollment  # noqa: E402
from app.models.progress_model import LearningProgress, NodeProgress  # noqa: E402
from app.models.question_bank_model import (  # noqa: E402
    QuestionAttempt,
    QuestionBankItem,
    QuestionStatus,
)
from app.models.cognitive_state_model import QuestionDepthRecord  # noqa: E402
from app.services.cognitive_service import (  # noqa: E402
    compute_cognitive_state,
    record_question_depth,
)
from app.common.llm_client import llm_client  # noqa: E402

COURSE_ID = 15
DEFAULT_PASSWORD = "SmartCarb#2026"

# 合成假名（与任何真实人员无关）
SURNAMES = "李王张刘陈杨赵黄周吴徐孙马朱胡郭何林罗郑梁谢宋唐许韩冯邓曹彭"
GIVEN = "雨桐欣怡子涵浩然宇轩梓睿思远嘉懿若汐沐宸晨曦语嫣俊杰文博佳琪"

# 正态分布用（Box-Muller，带截断）
def _normal(mu: float, sigma: float, lo: float, hi: float) -> float:
    u1 = random.random()
    u2 = random.random()
    z = math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)
    v = mu + z * sigma
    return max(lo, min(hi, v))


def _student_ids() -> list[str]:
    ids = []
    for major in ("0417", "0418"):
        for cls in ("01", "02", "03", "04", "05"):
            for seq in ("01", "02", "03", "04", "05", "06"):
                ids.append(f"{major}25{cls}{seq}")
    return ids


def _fake_name() -> str:
    return random.choice(SURNAMES) + "".join(random.choice(GIVEN) for _ in range(2))


# ---------------------------------------------------------------- 阶段2：账号 + 选课
def stage_accounts() -> None:
    ids = _student_ids()
    with Session(engine) as session:
        for sid in ids:
            exists = session.exec(select(User).where(User.username == sid)).first()
            if exists:
                continue
            user = User(
                username=sid,
                real_name=_fake_name(),
                hashed_password=get_password_hash(DEFAULT_PASSWORD),
                school_id=sid,
                role=UserRole.USER,
                is_active=True,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            # 选课
            session.add(
                StudentEnrollment(
                    student_id=user.id,
                    course_id=COURSE_ID,
                    total_nodes_count=173,
                )
            )
            session.commit()
    print(f"[done] 账号+选课：{len(ids)} 人（幂等，已存在则跳过）")


# ---------------------------------------------------------------- 阶段4：学习进度
def stage_progress() -> None:
    ids = _student_ids()
    node_ids = _all_node_ids()
    created = 0
    with Session(engine) as session:
        users = {u.username: u.id for u in session.exec(select(User).where(User.username.in_(ids))).all()}
        for sid in ids:
            uid = users.get(sid)
            if uid is None:
                continue
            # 每人已有学习进度则跳过
            lp = session.exec(
                select(LearningProgress).where(LearningProgress.user_id == uid, LearningProgress.course_id == COURSE_ID)
            ).first()
            if lp is not None:
                continue
            ratio = _normal(0.60, 0.15, 0.15, 0.98)
            done_n = max(1, int(round(len(node_ids) * ratio)))
            done = random.sample(node_ids, done_n)
            lp = LearningProgress(
                user_id=uid,
                course_id=COURSE_ID,
                total_nodes=len(node_ids),
                completed_nodes=done_n,
            )
            session.add(lp)
            session.commit()
            session.refresh(lp)
            for i, nid in enumerate(done):
                # time_spent 正态，均值 520s，多数 >300s 以触发置信度加成
                spent = int(_normal(520, 220, 60, 1800))
                session.add(
                    NodeProgress(
                        progress_id=lp.id,
                        node_id=nid,
                        node_index=i,
                        is_completed=True,
                        completion_count=1,
                        time_spent=spent,
                    )
                )
            session.commit()
            created += 1
        # 回填选课进度字段
        for sid in ids:
            uid = users.get(sid)
            enr = session.exec(select(StudentEnrollment).where(StudentEnrollment.student_id == uid, StudentEnrollment.course_id == COURSE_ID)).first()
            if enr is None:
                continue
            enr.total_nodes_count = len(node_ids)
            if enr.total_nodes_completed == 0:
                lp = session.exec(select(LearningProgress).where(LearningProgress.user_id == uid, LearningProgress.course_id == COURSE_ID)).first()
                if lp is not None:
                    enr.total_nodes_completed = lp.completed_nodes
                    enr.overall_progress = round(lp.completed_nodes / max(1, len(node_ids)) * 100, 1)
        session.commit()
    print(f"[done] 学习进度：{created} 人")


# ---------------------------------------------------------------- 阶段5：答题记录
def stage_attempts() -> None:
    ids = _student_ids()
    with Session(engine) as session:
        users = {u.username: u.id for u in session.exec(select(User).where(User.username.in_(ids))).all()}
        qids = session.exec(
            select(QuestionBankItem.id).where(
                QuestionBankItem.course_id == COURSE_ID,
                QuestionBankItem.status == QuestionStatus.PUBLISHED,
            )
        ).all()
        qids = [int(q) for q in qids]
        if not qids:
            print("[error] 题库为空，先跑 gen_demo_question_bank.py")
            return
        created = 0
        for sid in ids:
            uid = users.get(sid)
            # 已有答题记录则跳过
            cnt = session.exec(select(QuestionAttempt).where(QuestionAttempt.student_id == uid, QuestionAttempt.course_id == COURSE_ID)).first()
            if cnt is not None:
                continue
            n_attempt = int(_normal(10, 2.5, 6, 14))
            p_correct = _normal(0.70, 0.12, 0.35, 0.98)
            picked = random.sample(qids, min(n_attempt, len(qids)))
            for j, qid in enumerate(picked):
                correct = random.random() < p_correct
                score = round(_normal(0.9, 0.06, 0.8, 1.0), 3) if correct else round(_normal(0.25, 0.15, 0.0, 0.5), 3)
                session.add(
                    QuestionAttempt(
                        question_id=qid,
                        course_id=COURSE_ID,
                        student_id=uid,
                        source_event_id=f"demo_seed_{sid}_{j}",
                        measurement_role="scored_performance",
                        student_answer="(合成作答)",
                        is_correct=correct,
                        score=score,
                        judged_by="auto",
                    )
                )
            session.commit()
            created += 1
    print(f"[done] 答题记录：{created} 人（每人 6-14 条，正确率正态）")


# ---------------------------------------------------------------- 阶段6：AI 问答 + 六维重算
_QA_TEMPLATES = [
    ("recall", 0.45, "请用通俗语言解释“{t}”这个知识点。"),
    ("apply", 0.75, "“{t}”在解决实际问题时通常怎么应用？举一个例子。"),
    ("analyze", 0.60, "初学者理解“{t}”最常见的误区是什么？为什么？"),
]


def stage_qa() -> None:
    ids = _student_ids()
    # 幂等：清理历史 demo 深度记录，避免重跑时重复追加（只删 trace_id 带 demo 前缀的）
    from sqlalchemy import text as _text
    with Session(engine) as s0:
        s0.execute(_text("delete from question_depth_records where trace_id like 'demo_qa_%'"))
        s0.commit()

    with Session(engine) as session:
        users = {u.username: u.id for u in session.exec(select(User).where(User.username.in_(ids))).all()}
        titles = _node_titles(session)
        if not titles:
            print("[error] 无知识节点标题")
            return

        def _one_student(uid: int, sid: str) -> None:
            # 每人 2-4 个问题
            n_q = random.randint(2, 4)
            for _ in range(n_q):
                label, depth, tpl = random.choice(_QA_TEMPLATES)
                topic = random.choice(titles)
                question = tpl.format(t=topic)
                try:
                    answer = asyncio.run(
                        asyncio.wait_for(
                            llm_client.simple_chat(
                                f"你是计算机课程助教。请用 100 字以内简洁回答学生问题：{question}"
                            ),
                            timeout=40,
                        )
                    )
                except Exception:
                    answer = ""
                with Session(engine) as s2:
                    record_question_depth(
                        s2,
                        student_id=uid,
                        course_id=COURSE_ID,
                        node_id=None,
                        depth_score=depth,
                        depth_label=label,
                        trace_id=f"demo_qa_{sid}",
                        source="teaching_agent",
                    )
                    # 提问即认知证据：立即重算六维（与教学 Agent 行为一致）
                    compute_cognitive_state(s2, student_id=uid, course_id=COURSE_ID, node_id=None)
                print(f"  [{sid}] 问答 depth={depth}({label}) 回答{len(answer)}字", flush=True)
                import time as _t
                _t.sleep(0.5)  # 温和限速，避免 DeepSeek 限流

        for sid in ids:
            uid = users.get(sid)
            if uid is None:
                continue
            _one_student(uid, sid)
    print("[done] AI 问答 + 六维重算完成")


# ---------------------------------------------------------------- 辅助
def _all_node_ids() -> list[int]:
    from app.models.graph_production_model import CourseKnowledgeNode
    with Session(engine) as session:
        return [
            int(r)
            for r in session.exec(
                select(CourseKnowledgeNode.id).where(CourseKnowledgeNode.course_id == COURSE_ID).order_by(CourseKnowledgeNode.id)
            ).all()
        ]


def _node_titles(session: Session) -> list[str]:
    from sqlalchemy import text
    rows = session.execute(
        text("select title from course_knowledge_nodes where course_id = :cid order by id limit 60"),
        {"cid": COURSE_ID},
    ).all()
    return [str(r[0]) for r in rows if r[0]]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=["accounts", "progress", "attempts", "qa", "all"])
    args = parser.parse_args()

    random.seed(20260908)

    dialect = engine.url.get_backend_name()
    print(f"[info] 数据库方言: {dialect}")
    if dialect != "postgresql":
        print("[error] 未连接 PostgreSQL")
        return 1

    if args.stage in ("accounts", "all"):
        stage_accounts()
    if args.stage in ("progress", "all"):
        stage_progress()
    if args.stage in ("attempts", "all"):
        stage_attempts()
    if args.stage in ("qa", "all"):
        stage_qa()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
