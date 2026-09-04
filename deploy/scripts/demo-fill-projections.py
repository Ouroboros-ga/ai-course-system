# -*- coding: utf-8 -*-
"""为已填充的 Demo 学生补生成学习投影与课程统计投影（增量脚本）。

背景：主脚本 fill_student_demo_data_v2.py 生成时发现课程 outline 的
knowledge_graph_node_id 全部为 NULL，导致 projections/stats 无法生成。
本脚本改用 outline 标题与 course_knowledge_nodes 标题精确匹配建立关联
（匹配率：课程2=63/64、课程4=28/28、课程5=21/21），为现有学生补齐
student_learning_projections 与 course_learning_stats_projections。

用法：
  python fill_projections_only.py [--seed 20260817]
"""
from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

NOW = None  # 从 DB 现网时间取，避免与已生成数据时点不一致

COURSES = {
    2: "cr_17512d65a86641ffbc91feac8664f0f3",
    4: "cr_0f052b29f30e4a199bceab80e65dfc6d",
    5: "cr_d0f072f8ec01460d847ea9887bb2414d",
}


def clip(v, lo, hi):
    return max(lo, min(hi, v))


def as_aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260817)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    url = sa.engine.url.make_url(os.environ["AI_COURSE_DATABASE_URL"])
    engine = sa.create_engine(url, pool_pre_ping=True)
    meta = sa.MetaData()
    for t in (
        "course_outline_nodes", "course_knowledge_nodes",
        "course_memberships", "learning_progress",
        "cognitive_states", "student_learning_projections",
        "course_learning_stats_projections",
    ):
        meta.reflect(bind=engine, only=[t])
    T = meta.tables

    with engine.begin() as conn:
        now = datetime.now(timezone.utc)

        # ---- outline ↔ knowledge node 映射（title 精确匹配） ----
        outline_map = {}
        for cid in COURSES:
            out = conn.execute(
                sa.select(T["course_outline_nodes"].c.outline_node_id,
                          T["course_outline_nodes"].c.title)
                .where(T["course_outline_nodes"].c.course_id == cid,
                       T["course_outline_nodes"].c.node_type == "KNOWLEDGE_POINT")
                .order_by(T["course_outline_nodes"].c.order_index)
            ).all()
            kn = conn.execute(
                sa.select(T["course_knowledge_nodes"].c.id,
                          T["course_knowledge_nodes"].c.node_key,
                          T["course_knowledge_nodes"].c.title)
                .where(T["course_knowledge_nodes"].c.course_id == cid)
            ).all()
            kn_by_title = {}
            for kid, kkey, ktitle in kn:
                kn_by_title.setdefault(ktitle, (kid, kkey))
            mapped = []
            for onid, otitle in out:
                if otitle in kn_by_title:
                    kid, kkey = kn_by_title[otitle]
                    mapped.append((onid, kkey, kid))
            outline_map[cid] = mapped
            print(f"课程 {cid}: outline KNOWLEDGE_POINT 匹配 {len(mapped)} 个")

        # ---- 学生（STUDENT/ACTIVE） ----
        memberships = conn.execute(
            sa.select(T["course_memberships"].c.user_id, T["course_memberships"].c.course_id)
            .where(T["course_memberships"].c.status == "ACTIVE",
                   T["course_memberships"].c.role == "STUDENT")
        ).all()
        per_course = {}
        for uid, cid in memberships:
            per_course.setdefault(cid, []).append(uid)
        for cid in COURSES:
            print(f"课程 {cid}: 学生 {len(per_course.get(cid, []))} 人")

        # ---- 学习投影 ----
        proj_count = 0
        for uid, cid in memberships:
            lp = conn.execute(
                sa.select(T["learning_progress"].c.completed_nodes,
                          T["learning_progress"].c.completion_rate,
                          T["learning_progress"].c.last_accessed_at,
                          T["learning_progress"].c.started_at)
                .where(T["learning_progress"].c.user_id == uid,
                       T["learning_progress"].c.course_id == cid)
            ).first()
            if lp is None:
                continue
            completed, rate, last, started = lp
            release_id = COURSES[cid]
            outlines = outline_map[cid]
            if not outlines:
                continue
            rate = rate or 0.0
            learned = max(1, min(len(outlines), int(round(len(outlines) * rate))))
            if completed <= 0:
                learned = 0
            sample_o = outlines[:learned]
            if len(sample_o) > 60:
                sample_o = sample_o[:30] + rng.sample(sample_o[30:], 30)
            for oi, (onid, kkey, _kid) in enumerate(sample_o):
                if oi == len(sample_o) - 1 and rng.random() < 0.4:
                    status = "IN_PROGRESS"
                    c_ratio = rng.uniform(0.3, 0.95)
                    comp_at = None
                else:
                    status = "COMPLETED"
                    c_ratio = 1.0
                    comp_at = last - timedelta(minutes=rng.randint(0, 600))
                days_back = max(1, (now - as_aware(started or last)).days - 1)
                t1 = last - timedelta(days=rng.randint(0, days_back))
                conn.execute(T["student_learning_projections"].insert().values(
                    student_id=uid, course_id=cid, release_id=release_id,
                    outline_node_id=onid, knowledge_node_key=kkey,
                    exposure_status=status,
                    exposure_seconds=int(240 * c_ratio),
                    visit_count=rng.randint(1, 4),
                    completion_ratio=round(c_ratio, 3),
                    completion_reason="explicit_complete" if status == "COMPLETED" else None,
                    current_timestamp=rng.uniform(0, 60), current_page=1,
                    first_accessed_at=t1, last_accessed_at=last,
                    completed_at=comp_at, last_event_id=None,
                    projection_version=1, updated_at=last,
                ))
                proj_count += 1
        print(f"projections 新增 {proj_count} 条")

        # ---- 课程统计投影 ----
        # 旧 demo 统计投影（早期 2 名学生时代）与当前 release 重复，先清掉再按现网重算
        for cid, release_id in COURSES.items():
            conn.execute(T["course_learning_stats_projections"].delete().where(
                T["course_learning_stats_projections"].c.course_id == cid,
                T["course_learning_stats_projections"].c.release_id == release_id))
        stat_count = 0
        for cid, release_id in COURSES.items():
            students_c = per_course.get(cid, [])
            for onid, _kkey, kid in outline_map[cid]:
                rows = conn.execute(
                    sa.select(T["student_learning_projections"].c.exposure_status)
                    .where(T["student_learning_projections"].c.course_id == cid,
                           T["student_learning_projections"].c.release_id == release_id,
                           T["student_learning_projections"].c.outline_node_id == onid)
                ).all()
                counts = {"in_progress": 0, "completed": 0}
                for (stt,) in rows:
                    counts[stt] = counts.get(stt, 0) + 1
                not_started = max(0, len(students_c) - counts["in_progress"] - counts["completed"])
                mastery_dist = {}
                unknown_n, low_conf = 0, 0
                if students_c:
                    states = conn.execute(
                        sa.select(T["cognitive_states"].c.mastery_level,
                                  T["cognitive_states"].c.evidence_confidence)
                        .where(T["cognitive_states"].c.course_id == cid,
                               T["cognitive_states"].c.node_id == kid,
                               T["cognitive_states"].c.is_latest == True,
                               T["cognitive_states"].c.student_id.in_(students_c))
                    ).all()
                    for lv, conf in states:
                        lv = lv or "unknown"
                        mastery_dist[lv] = mastery_dist.get(lv, 0) + 1
                        if lv == "unknown":
                            unknown_n += 1
                        if conf is None or conf < 0.5:
                            low_conf += 1
                    unknown_n += max(0, len(students_c) - sum(mastery_dist.values()))
                conn.execute(T["course_learning_stats_projections"].insert().values(
                    course_id=cid, release_id=release_id, outline_node_id=onid,
                    student_count=len(students_c), not_started_count=not_started,
                    in_progress_count=counts["in_progress"], completed_count=counts["completed"],
                    mastery_distribution=mastery_dist, unknown_mastery_count=unknown_n,
                    low_confidence_count=low_conf, pending_recommendation_count=0,
                    projection_version=1, computed_at=now,
                ))
                stat_count += 1
        print(f"stats projections 新增 {stat_count} 条")

    engine.dispose()


if __name__ == "__main__":
    main()
