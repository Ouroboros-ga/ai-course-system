"""只读诊断：课程15学习分析页面的三个问题（掌握度趋势/答题提问趋势/学生下钻矩阵）。"""
from __future__ import annotations

import os
import sys
from datetime import timedelta

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

from sqlalchemy import func  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.core.time_utils import utcnow_aware, to_aware  # noqa: E402
from app.models.database import engine  # noqa: E402
from app.models.cognitive_state_model import CognitiveState, QuestionDepthRecord  # noqa: E402
from app.models.question_bank_model import QuestionAttempt  # noqa: E402
from app.models.unified_learning_model import LearningEvent  # noqa: E402
from app.models.user_model import User  # noqa: E402
from app.services.unified_learning_service import course_trend_and_metrics, student_context  # noqa: E402

COURSE_ID = 15


def _day(dt):
    return to_aware(dt).strftime("%m-%d %H:%M")


with Session(engine) as s:
    now = utcnow_aware()
    print("now(utc) =", now.isoformat(), "| now(beijing) =", (now + timedelta(hours=8)).isoformat())

    print("\n=== 1. cognitive_states 时间与掌握度 ===")
    states = s.exec(select(CognitiveState).where(CognitiveState.course_id == COURSE_ID)).all()
    print(f"  总记录={len(states)}  mastery_score 非空={sum(1 for st in states if st.mastery_score is not None)}")
    with_score = [st for st in states if st.mastery_score is not None]
    if with_score:
        cmin = min(to_aware(st.computed_at) for st in with_score)
        cmax = max(to_aware(st.computed_at) for st in with_score)
        print(f"  computed_at 范围: {cmin.isoformat()} ~ {cmax.isoformat()}")
        # 按天分布（近8天）
        per_day = {}
        for st in with_score:
            d = to_aware(st.computed_at).strftime("%m-%d")
            per_day[d] = per_day.get(d, 0) + 1
        print(f"  按天分布(computed_at): {dict(sorted(per_day.items()))}")
    # 最新一条样例
    sample = s.exec(select(CognitiveState).where(CognitiveState.course_id == COURSE_ID, CognitiveState.mastery_score != None).order_by(CognitiveState.computed_at.desc())).first()
    if sample:
        print(f"  样例: student={sample.student_id} mastery_score={sample.mastery_score} level={sample.mastery_level} computed_at={_day(sample.computed_at)}")

    print("\n=== 2. question_attempts 时间 ===")
    attempts = s.exec(select(QuestionAttempt).where(QuestionAttempt.course_id == COURSE_ID)).all()
    print(f"  总数={len(attempts)}")
    if attempts:
        amin = min(to_aware(a.created_at) for a in attempts)
        amax = max(to_aware(a.created_at) for a in attempts)
        print(f"  created_at 范围: {amin.isoformat()} ~ {amax.isoformat()}")
        per_day = {}
        for a in attempts:
            d = to_aware(a.created_at).strftime("%m-%d")
            per_day[d] = per_day.get(d, 0) + 1
        print(f"  按天分布(created_at): {dict(sorted(per_day.items()))}")

    print("\n=== 3. question_depth_records(提问) 时间 ===")
    qds = s.exec(select(QuestionDepthRecord).where(QuestionDepthRecord.course_id == COURSE_ID)).all()
    print(f"  总数={len(qds)}")
    if qds:
        per_day = {}
        for q in qds:
            if q.created_at:
                d = to_aware(q.created_at).strftime("%m-%d")
                per_day[d] = per_day.get(d, 0) + 1
        print(f"  按天分布(created_at): {dict(sorted(per_day.items()))}")

    print("\n=== 4. learning_events 时间（活跃度趋势）===")
    evs = s.exec(select(LearningEvent).where(LearningEvent.course_id == COURSE_ID)).all()
    print(f"  总数={len(evs)}")
    if evs:
        per_day = {}
        for e in evs:
            d = to_aware(e.occurred_at).strftime("%m-%d")
            per_day[d] = per_day.get(d, 0) + 1
        print(f"  按天分布(occurred_at): {dict(sorted(per_day.items()))}")

    print("\n=== 5. 重构的 trend 返回 ===")
    trend = course_trend_and_metrics(s, course_id=COURSE_ID, days=7)
    t = trend["trend"]
    print("  dates    =", t["dates"])
    print("  mastery  =", t["mastery"])
    print("  activity =", t["activity"])
    print("  questioning =", t["questioning"])
    cm = trend["core_metrics"]
    print("  core_metrics =", {k: cm[k] for k in ("ai_calls", "ai_success_rate", "question_count", "interaction_count", "answer_count", "answer_accuracy", "active_students")})

    print("\n=== 6. 学生下钻 student_context（demo 学生 231）===")
    ctx = student_context(s, student_id=231, course_id=COURSE_ID)
    print(f"  release_id={ctx['release_id']}  total={ctx['total']}  completed={ctx['completed']}  rate={ctx['completion_rate']}")
    for it in ctx["items"][:3]:
        print(f"    {it['outline_node_id'][:12]}  {it['title'][:16]}  learning.status={it['learning']['status']}  ratio={it['learning']['completion_ratio']}  knowledge_node_key={it['knowledge_node_key']}")
