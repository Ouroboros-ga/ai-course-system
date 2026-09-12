"""学习分析页面三个问题的数据侧修复（课程15「算法」）。

问题与根因：
1. 掌握度趋势只有今天一个点 → cognitive_states.computed_at 全在今天。
2. 答题/提问趋势只有今天一个尖峰 → question_attempts.created_at 全在今天。
3. 「查看矩阵」认知/推荐全 not_available → 8 个大纲节点 knowledge_graph_node_id 为空，
   未映射到知识图谱节点，且无节点级 cognitive_states。

修复（全部幂等，可重复运行）：
- stage=trends  ：把 question_attempts.created_at / question_depth_records.created_at
  / cognitive_states.computed_at 铺到过去 7 天；历史状态 mastery_score 按天做
  渐进缩放（越早越低），形成向上的掌握度趋势；is_latest=True 状态保持原值。
- stage=mapping ：按标题精确匹配，回填 8 个大纲节点的 knowledge_graph_node_id；
  为每个学生已完成的节点生成节点级 cognitive_states（复用其课程级最新状态）；
  最后 refresh_course_stats 重算节点统计（掌握度分布）。

用法：
    python backfill_analytics_issues.py --stage trends --dry-run
    python backfill_analytics_issues.py --stage mapping --dry-run
    python backfill_analytics_issues.py --stage all
"""
from __future__ import annotations

import argparse
import datetime
import os
import random
import sys

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

from app.core.time_utils import utcnow_aware, to_aware  # noqa: E402
from app.models.database import engine  # noqa: E402
from app.models.user_model import User  # noqa: E402
from app.models.question_bank_model import QuestionAttempt  # noqa: E402
from app.models.cognitive_state_model import CognitiveState, QuestionDepthRecord  # noqa: E402
from app.models.course_build_model import CourseRelease  # noqa: E402
from app.models.course_outline_model import CourseOutlineNode  # noqa: E402
from app.models.graph_production_model import CourseKnowledgeNode  # noqa: E402
from app.models.unified_learning_model import StudentLearningProjection, ExposureStatus  # noqa: E402
from app.services.unified_learning_service import (  # noqa: E402
    active_release,
    release_nodes,
    refresh_course_stats,
)

COURSE_ID = 15


def _student_ids() -> list[str]:
    ids = []
    for major in ("0417", "0418"):
        for cls in ("01", "02", "03", "04", "05"):
            for seq in ("01", "02", "03", "04", "05", "06"):
                ids.append(f"{major}25{cls}{seq}")
    return ids


def _past(now, day_offset: int, hour: int, minute: int) -> datetime.datetime:
    """day_offset 天前的 hour:minute，保证 <= now。"""
    day = (now - datetime.timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if day > now:
        day = now - datetime.timedelta(minutes=5)
    return day


def _level(score: float) -> str:
    if score >= 0.8:
        return "advanced"
    if score >= 0.6:
        return "proficient"
    if score >= 0.4:
        return "developing"
    return "beginner"


def _spread_trends(dry_run: bool) -> None:
    """把今天的集中数据铺到过去 7 天。"""
    now = utcnow_aware()
    ids = _student_ids()
    rng = random.Random(20260908)

    with Session(engine) as s:
        users = {u.username: u.id for u in s.exec(select(User).where(User.username.in_(ids))).all()}
        demo_uids = list(users.values())

        # ---- 1) question_attempts：每人尝试铺到其"活跃日"
        attempts = s.exec(select(QuestionAttempt).where(QuestionAttempt.course_id == COURSE_ID, QuestionAttempt.student_id.in_(demo_uids))).all()
        # 每生一个活跃日（近7天，均匀）
        active_day = {uid: rng.randint(0, 6) for uid in demo_uids}
        for a in attempts:
            d = active_day.get(a.student_id, rng.randint(0, 6))
            a.created_at = _past(now, d, rng.randint(8, 20), rng.randint(0, 59))
        print(f"[trends] question_attempts 铺开 {len(attempts)} 条")

        # ---- 2) question_depth_records（提问，趋势外但保持时间一致）
        qds = s.exec(select(QuestionDepthRecord).where(QuestionDepthRecord.course_id == COURSE_ID, QuestionDepthRecord.student_id.in_(demo_uids))).all()
        for q in qds:
            d = active_day.get(q.student_id, rng.randint(0, 6))
            q.created_at = _past(now, d, rng.randint(8, 20), rng.randint(0, 59))
        print(f"[trends] question_depth_records 铺开 {len(qds)} 条")

        # ---- 3) cognitive_states：历史状态铺到更早的日子并渐进缩放，latest 保持原值
        states = s.exec(select(CognitiveState).where(CognitiveState.course_id == COURSE_ID, CognitiveState.student_id.in_(demo_uids))).all()
        # 每生最新状态的满分基准
        latest_by_student = {}
        for st in states:
            if st.is_latest and st.mastery_score is not None:
                latest_by_student[st.student_id] = st
        scaled = 0
        for st in states:
            if st.mastery_score is None:
                continue
            if st.is_latest:
                st.computed_at = _past(now, 0, rng.randint(9, 18), rng.randint(0, 59))
                continue
            # 历史状态：放到过去 1..6 天，越早 mastery 越低（向上趋势）
            d = rng.randint(1, 6)
            factor = 0.50 + 0.50 * ((6 - d) / 5.0)  # d=1→1.0, d=6→0.5
            base = latest_by_student.get(st.student_id)
            if base is not None:
                st.mastery_score = round(base.mastery_score * factor, 4)
                st.mastery_level = _level(st.mastery_score)
            st.computed_at = _past(now, d, rng.randint(9, 20), rng.randint(0, 59))
            scaled += 1
        print(f"[trends] cognitive_states：latest 保持原值，历史状态渐进缩放 {scaled} 条")

        if dry_run:
            print("[dry-run] 未提交")
            s.rollback()
            return
        s.commit()
        print("[trends] 已提交")


def _map_and_nodes(dry_run: bool) -> None:
    """大纲节点映射 + 节点级认知 + 重算统计。"""
    now = utcnow_aware()
    ids = _student_ids()
    rng = random.Random(20260908)

    with Session(engine) as s:
        release = active_release(s, COURSE_ID)
        if release is None:
            print("[error] 无活跃发布")
            return
        nodes = release_nodes(s, release)
        kg_nodes = s.exec(select(CourseKnowledgeNode).where(CourseKnowledgeNode.course_id == COURSE_ID)).all()
        kg_by_title = {n.title: n for n in kg_nodes}

        # ---- 1) 映射大纲节点 → 知识图谱节点（按标题精确匹配）
        mapped = 0
        unmapped = []
        for node in nodes:
            if node.knowledge_graph_node_id:
                mapped += 1
                continue
            kg = kg_by_title.get(node.title)
            if kg is None:
                unmapped.append(node.title)
                continue
            node.knowledge_graph_node_id = kg.node_key
            mapped += 1
        print(f"[mapping] 大纲节点映射：{mapped} 个已映射，未匹配 {unmapped or '无'}")

        # ---- 2) 节点级 cognitive_states（为已完成节点生成）
        users = {u.username: u.id for u in s.exec(select(User).where(User.username.in_(ids))).all()}
        demo_uids = list(users.values())
        # 每生最新课程级状态
        latest = {}
        for st in s.exec(select(CognitiveState).where(CognitiveState.course_id == COURSE_ID, CognitiveState.student_id.in_(demo_uids), CognitiveState.node_id.is_(None), CognitiveState.is_latest == True)).all():
            latest[st.student_id] = st
        # outline_node_id -> knowledge node id
        on_id_to_kg = {}
        for node in nodes:
            kg = kg_by_title.get(node.title)
            if kg is not None:
                on_id_to_kg[node.outline_node_id] = kg.id

        projections = s.exec(select(StudentLearningProjection).where(
            StudentLearningProjection.course_id == COURSE_ID,
            StudentLearningProjection.release_id == release.release_id,
            StudentLearningProjection.student_id.in_(demo_uids),
        )).all()
        # 已有节点级状态（幂等判断）
        existing = set()
        for st in s.exec(select(CognitiveState).where(CognitiveState.course_id == COURSE_ID, CognitiveState.node_id.is_not(None), CognitiveState.student_id.in_(demo_uids))).all():
            existing.add((st.student_id, st.node_id))

        created = 0
        for p in projections:
            if p.exposure_status != ExposureStatus.COMPLETED:
                continue
            kg_id = on_id_to_kg.get(p.outline_node_id)
            if kg_id is None:
                continue
            if (p.student_id, kg_id) in existing:
                continue
            base = latest.get(p.student_id)
            if base is None:
                continue
            score = round(max(0.1, min(1.0, (base.mastery_score or 0.6) * rng.uniform(0.9, 1.08))), 4)
            s.add(CognitiveState(
                student_id=p.student_id,
                course_id=COURSE_ID,
                node_id=kg_id,
                observed_performance_score=base.observed_performance_score,
                evidence_confidence=base.evidence_confidence,
                confusion_risk=base.confusion_risk,
                inquiry_depth=base.inquiry_depth,
                hint_dependency=base.hint_dependency,
                explanation_need=base.explanation_need,
                mastery_level=_level(score),
                mastery_score=None,  # 不写 mastery_score，避免污染课程级掌握度趋势
                evidence_refs=base.evidence_refs or [],
                reason_codes=[],
                sample_size=base.sample_size or 0,
                is_latest=True,
                computed_at=now,
            ))
            existing.add((p.student_id, kg_id))
            created += 1
        print(f"[mapping] 节点级 cognitive_states 新建 {created} 条")

        # ---- 2b) 幂等校正：已存在的 demo 节点级状态也置空 mastery_score
        node_states = s.exec(select(CognitiveState).where(
            CognitiveState.course_id == COURSE_ID,
            CognitiveState.node_id.is_not(None),
            CognitiveState.student_id.in_(demo_uids),
            CognitiveState.mastery_score.is_not(None),
        )).all()
        for ns in node_states:
            ns.mastery_score = None
        if node_states:
            print(f"[mapping] 校正既有节点级状态 mastery_score=None：{len(node_states)} 条")

        if dry_run:
            print("[dry-run] 未提交")
            s.rollback()
            return
        s.commit()

        # ---- 3) 重算统计（掌握度分布等）
        refresh_course_stats(s, course_id=COURSE_ID, release_id=release.release_id)
        s.commit()
        print("[mapping] 已提交并重算统计")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["trends", "mapping", "all"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.stage in ("trends", "all"):
        _spread_trends(args.dry_run)
    if args.stage in ("mapping", "all"):
        _map_and_nodes(args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
