# -*- coding: utf-8 -*-
"""为 SmartCarb Demo 生成约 170 名学生的合成学习数据（v2 精简实现）。

数据域（合成、假名化，符合 AGENTS.md §4.1）：
- users / course_memberships / student_enrollments
- learning_progress / node_progress
- cognitive_states（课程级 + 节点级六维认知与掌握度）
- student_learning_projections / course_learning_stats_projections
- learning_trajectory_records

学习行为模型：
- 约 20% 学生自 274 天前开始（首批老生），约 80% 自 13 天前开始（主要新生）；
- 每人每天学习 5~11 分钟（含活跃率随机跳过），总时长按天数自然积累；
- 完成度 = 累计学习时间 / 课程容量（各课程节点时长不同），无"全课程学完"假象；
- 掌握度服从近似大学课堂的正态分布（少数优秀 / 多数中等 / 少数薄弱）。

用法：
  python fill_student_demo_data_v2.py [--students 170] [--dry-run] [--seed 20260817]
  需要环境变量 AI_COURSE_DATABASE_URL。
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import bcrypt
import sqlalchemy as sa

NOW = datetime.now(timezone.utc)
PASSWORD = "SmartCarb#2026"
PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

# 三个已发布课程：id -> (release_id, 每节点平均分钟)
COURSES = {
    2: ("cr_17512d65a86641ffbc91feac8664f0f3", 3.5),  # 汽车工程 509 节点
    4: ("cr_0f052b29f30e4a199bceab80e65dfc6d", 2.2),  # 数据结构 2582 节点
    5: ("cr_d0f072f8ec01460d847ea9887bb2414d", 4.0),  # 控制系统的数学模型 33 节点
}
COURSE_TARGETS = {2: 100, 4: 95, 5: 75}

SURNAMES = ("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤")
GIVEN = ("伟芳娜敏静丽强磊军洋勇艳杰涛明超霞平刚文辉志强丽华永春燕桂芳海燕玉兰国庆志明晓明晓东雪琳晨阳昊子轩雨桐梓涵欣怡浩然宇轩思远一诺俊杰若曦梦琪天佑泽宇佳怡文博嘉懿雨泽晨曦诗涵博文睿思彤宇航志泽静怡明轩思思雨欣俊驰若彤依诺欣妍子涵语嫣亦凡国豪凯文建平志鹏嘉欣淑芬婷婷静香俊杰子墨晨曦宛凝")
PINYIN_USERS = ("wangfang_2024 lizhihao_2024 zhangwei_2024 chenxue_2024 liuyang_2024 huangmin_2024 zhoujie_2024 wuqiang_2024 xuyan_2024 sunlei_2024 malin_2024 zhujun_2024 hujing_2024 guoli_2024 gaoming_2024 linxia_2024 luoyu_2024 zhengfei_2024 liangchen_2024 songyuan_2024 tangxin_2024 hanhan_2024 fenglei_2024 dengchao_2024 caojing_2024 penghui_2024 zengyan_2024 xiaotian_2024 tianyu_2024 dongfang_2024 yuanxin_2024 panshuai_2024 yujia_2024 jiangtao_2024 caixin_2024 yuyang_2024 chengfei_2024 suqing_2024 weidong_2024 lvyun_2024 dingning_2024 renhao_2024 shenqian_2024 yaohua_2024 lujing_2024 jiangbo_2024 cuiwei_2024 zhongliang_2024 tanrui_2024 luyu_2024 wangze_2024 fanxin_2024 shiling_2024 jinyan_2024 shiyu_2024 qiaoyun_2024 xialin_2024 weifang_2024 fubiao_2024 baijie_2024").split()

LEARNER_PARAMS = {
    "old": {"start_days": 274, "active_rate": (0.42, 0.60), "minutes": (6.0, 11.5), "count": 35},
    "new": {"start_days": 13, "active_rate": (0.72, 0.95), "minutes": (5.0, 10.5), "count": 135},
}

COGNITIVE_POLICY = "cognitive-policy-v1.3"


def clip(v, lo, hi):
    return max(lo, min(hi, v))


def ng(rng, mu, sigma, lo, hi):
    return clip(rng.gauss(mu, sigma), lo, hi)


def mastery_level(score):
    if score is None:
        return "unknown"
    if score >= 0.85:
        return "excellent"
    if score >= 0.70:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def pick_time(rng, day):
    if rng.random() < 0.75:
        hour = rng.randint(18, 22)
    else:
        hour = rng.choice((12, 13))
    return day.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59), microsecond=0)


def build_sessions(rng, start, end, total_minutes):
    """把累计学习分钟切成每天 1~2 个短会话，返回 [(start_dt, seconds)]。"""
    sessions = []
    remaining = total_minutes
    day = start
    while remaining > 1.0 and day < end:
        day_min = rng.uniform(5.0, 11.0)
        if day_min >= remaining:
            day_min = remaining
        t1 = pick_time(rng, day)
        sessions.append((t1, int(day_min * 60)))
        remaining -= day_min
        if rng.random() < 0.16 and remaining > 3.0:
            second = min(day_min * 0.5, remaining)
            t2 = pick_time(rng, day + timedelta(days=1))
            sessions.append((t2, int(second * 60)))
            remaining -= second
            day += timedelta(days=1)
        day += timedelta(days=1)
    return sessions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--students", type=int, default=170)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seed", type=int, default=20260817)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    url = sa.engine.url.make_url(os.environ["AI_COURSE_DATABASE_URL"])
    engine = sa.create_engine(url, pool_pre_ping=True)
    meta = sa.MetaData()
    for t in (
        "users", "course_memberships", "student_enrollments", "learning_progress",
        "node_progress", "cognitive_states", "student_learning_projections",
        "course_learning_stats_projections", "learning_trajectory_records",
        "course_outline_nodes", "course_knowledge_nodes", "course_releases",
        "course_capabilities",
    ):
        meta.reflect(bind=engine, only=[t])
    T = meta.tables

    with engine.begin() as conn:
        # ---- 0. 课程事实 ----
        nodes_by_course = {}
        outline_by_course = {}
        for cid in COURSES:
            rows = conn.execute(
                sa.select(T["course_knowledge_nodes"].c.id, T["course_knowledge_nodes"].c.node_key)
                .where(T["course_knowledge_nodes"].c.course_id == cid)
                .order_by(T["course_knowledge_nodes"].c.id)
            ).all()
            nodes_by_course[cid] = [tuple(r) for r in rows]
            outlines = conn.execute(
                sa.select(
                    T["course_outline_nodes"].c.outline_node_id,
                    T["course_outline_nodes"].c.knowledge_graph_node_id,
                )
                .where(T["course_outline_nodes"].c.course_id == cid)
                .where(T["course_outline_nodes"].c.knowledge_graph_node_id.is_not(None))
                .order_by(T["course_outline_nodes"].c.order_index)
            ).all()
            outline_by_course[cid] = [tuple(r) for r in outlines]
        existing_users = {r[0] for r in conn.execute(sa.select(T["users"].c.username)).all()}
        for cid in COURSES:
            print(f"课程 {cid}: knowledge_nodes={len(nodes_by_course[cid])} outline_kg={len(outline_by_course[cid])}")

        # ---- 1. 学生画像 ----
        students = []
        idx = 0
        while len(students) < args.students:
            cohort = "old" if idx < LEARNER_PARAMS["old"]["count"] else "new"
            p = LEARNER_PARAMS[cohort]
            if idx < LEARNER_PARAMS["old"]["count"] + 110:
                username = f"stu{101 + idx}"
            else:
                username = PINYIN_USERS[(idx - LEARNER_PARAMS["old"]["count"] - 110) % len(PINYIN_USERS)]
            if username in existing_users:
                username = f"{username}_x"
            surname = SURNAMES[rng.randrange(len(SURNAMES))]
            given = GIVEN[rng.randrange(len(GIVEN))]
            students.append({
                "username": username,
                "real_name": f"{surname}{given}",
                "account": f"2024{10100 + idx:04d}" if cohort == "old" else f"2025{20000 + idx:04d}",
                "cohort": cohort,
                "start": NOW - timedelta(days=p["start_days"]) + timedelta(days=rng.randint(0, 2)),
                "active_rate": rng.uniform(*p["active_rate"]),
                "day_minutes": rng.uniform(*p["minutes"]),
                "ability": ng(rng, 0.66, 0.16, 0.18, 0.97),
                "inquiry": ng(rng, 0.55, 0.18, 0.05, 0.98),
                "courses": [],
            })
            idx += 1

        # ---- 2. 选课分配 ----
        for i, st in enumerate(students):
            r = rng.random()
            if i % 11 == 0:
                st["courses"] = [rng.choice([2, 5])]
            elif r < 0.45:
                st["courses"] = sorted(rng.sample([2, 4, 5], 2))
            elif r < 0.88:
                st["courses"] = sorted(rng.sample([2, 4, 5], 2))
            else:
                st["courses"] = [2, 4, 5]
        counts = {c: 0 for c in COURSES}
        for st in students:
            for c in st["courses"]:
                counts[c] += 1
        for c, target in COURSE_TARGETS.items():
            diff = target - counts[c]
            while diff > 0:
                cands = [s for s in students if c not in s["courses"]]
                if not cands:
                    break
                s = rng.choice(cands)
                s["courses"].append(c)
                s["courses"].sort()
                counts[c] += 1
                diff -= 1
            while diff < 0:
                cands = [s for s in students if c in s["courses"] and len(s["courses"]) > 1]
                if not cands:
                    break
                s = rng.choice(cands)
                s["courses"].remove(c)
                counts[c] -= 1
                diff += 1
        print("选课人数:", counts)

        # ---- 3. 用户 ----
        for st in students:
            conn.execute(T["users"].insert().values(
                username=st["username"], real_name=st["real_name"],
                fanya_account_id=st["account"], hashed_password=PASSWORD_HASH,
                role="USER", is_active=True, is_fanya_verified=False, auth_version=1,
                created_at=st["start"], updated_at=st["start"],
            ))
        uid_map = {username: user_id for user_id, username in conn.execute(
            sa.select(T["users"].c.id, T["users"].c.username).where(
                T["users"].c.username.in_([s["username"] for s in students]))).all()}
        for st in students:
            st["uid"] = uid_map[st["username"]]

        # ---- 4. 选课落库 ----
        enroll_rows, member_rows = [], []
        for st in students:
            for c in st["courses"]:
                enroll_rows.append(dict(
                    student_id=st["uid"], course_id=c, enrolled_at=st["start"],
                    total_nodes_completed=0, total_nodes_count=len(nodes_by_course[c]),
                    overall_progress=0.0, avg_understanding_score=0.0,
                    avg_understanding_level="low", total_study_minutes=0,
                    last_study_time=None, is_active=True))
                member_rows.append(dict(
                    user_id=st["uid"], course_id=c, role="STUDENT", status="ACTIVE",
                    permission_overrides={}, analytics_excluded=False,
                    joined_at=st["start"], left_at=None, updated_at=st["start"],
                    migration_batch_id="demo-synthetic-20260817"))
        conn.execute(T["student_enrollments"].insert(), enroll_rows)
        conn.execute(T["course_memberships"].insert(), member_rows)

        # ---- 5. 每选课生成学习数据 ----
        enr_updates = []
        for st in students:
            last_course, last_node, last_access = None, None, st["start"]
            for c in st["courses"]:
                release_id, per_node_min = COURSES[c]
                node_list = nodes_by_course[c]
                total_nodes = len(node_list)
                day_minutes = st["day_minutes"] * rng.uniform(0.55, 1.0)
                active_days = max(1, int((NOW - st["start"]).days * st["active_rate"]))
                total_min = active_days * day_minutes * rng.uniform(0.9, 1.1)
                capacity_min = max(1.0, total_nodes * per_node_min)
                efficiency = ng(rng, 0.92, 0.14, 0.62, 1.12)
                rate = clip(total_min / capacity_min * efficiency, 0.0, 0.97)
                if c == 5 and st["cohort"] == "old" and rng.random() < 0.3:
                    rate = 1.0  # 小课程老生中少数可完整学完
                completed = min(total_nodes, max(0, int(round(rate * total_nodes))))
                sessions = build_sessions(rng, st["start"], NOW, total_min)
                last_access = sessions[-1][0] if sessions else st["start"] + timedelta(minutes=5)
                total_sec = sum(s[1] for s in sessions)
                status = "COMPLETED" if rate >= 0.995 else ("IN_PROGRESS" if completed > 0 else "NOT_STARTED")

                pid = conn.execute(
                    T["learning_progress"].insert().returning(T["learning_progress"].c.id),
                    dict(
                        user_id=st["uid"], course_id=c, script_id=None,
                        current_node_id=None, current_node_index=completed,
                        current_timestamp=rng.uniform(0, 120), current_page=rng.randint(1, 12),
                        total_nodes=total_nodes, completed_nodes=completed,
                        completion_rate=round(rate, 4), status=status,
                        total_learning_time=total_sec, session_count=len(sessions),
                        last_accessed_at=last_access,
                        started_at=st["start"] if completed > 0 else None,
                        completed_at=last_access if status == "COMPLETED" else None,
                        created_at=st["start"], updated_at=last_access,
                    )).scalar()

                # 节点进度
                n = min(completed, 40)
                if n > 0:
                    seq = list(range(min(completed, 300)))
                    head = seq[: max(1, int(n * 0.6))]
                    tail = rng.sample(seq[max(1, int(n * 0.4)):], max(0, n - len(head))) if len(seq) > 1 else []
                    for node_idx in sorted(set(head + tail))[:n]:
                        node = node_list[node_idx]
                        t1 = sessions[min(node_idx, len(sessions) - 1)][0] if sessions else st["start"]
                        t2 = t1 + timedelta(seconds=rng.randint(90, 420))
                        understanding = ng(rng, st["ability"] * 0.92 + 0.06, 0.1, 0.15, 0.99)
                        conn.execute(T["node_progress"].insert().values(
                            progress_id=pid, node_id=node[0], node_index=node_idx,
                            is_completed=True, completion_count=rng.randint(1, 3),
                            time_spent=rng.randint(90, 420), last_timestamp=rng.uniform(0, 180),
                            understanding_level=mastery_level(understanding).upper(),
                            understanding_score=round(understanding, 3),
                            question_count=rng.randint(0, 3),
                            correct_answer_rate=round(clip(understanding + rng.uniform(-0.1, 0.1), 0.3, 1.0), 3),
                            first_accessed_at=t1, last_accessed_at=t2, completed_at=t2))

                # 六维认知（课程级）
                sample = min(60, max(0, int(total_min / 15)))
                perf = ng(rng, st["ability"], 0.07, 0.1, 0.99)
                if completed <= 2 and sample < 4:
                    conn.execute(T["cognitive_states"].insert().values(
                        student_id=st["uid"], course_id=c, node_id=None,
                        observed_performance_score=None, evidence_confidence=None,
                        confusion_risk=None, inquiry_depth=None, hint_dependency=None,
                        explanation_need=None, mastery_level="unknown", mastery_score=None,
                        policy_version=COGNITIVE_POLICY, evidence_refs=[], reason_codes=["insufficient_evidence"],
                        sample_size=sample, is_latest=True, computed_at=last_access, created_at=last_access))
                else:
                    conn.execute(T["cognitive_states"].insert().values(
                        student_id=st["uid"], course_id=c, node_id=None,
                        observed_performance_score=round(perf, 3),
                        evidence_confidence=round(clip(0.30 + 0.55 * min(1.0, sample / 8.0) + rng.gauss(0, 0.05), 0.1, 0.98), 3),
                        confusion_risk=round(clip(1.0 - perf + rng.gauss(0, 0.10), 0.02, 0.95), 3),
                        inquiry_depth=round(ng(rng, st["inquiry"], 0.1, 0.05, 0.97), 3),
                        hint_dependency=round(clip(1.0 - perf * 0.7 + rng.gauss(0, 0.12), 0.05, 0.95), 3),
                        explanation_need=round(clip(0.52 - perf * 0.32 + rng.gauss(0, 0.14), 0.05, 0.95), 3),
                        mastery_level=mastery_level(perf), mastery_score=round(perf, 3),
                        policy_version=COGNITIVE_POLICY, evidence_refs=[], reason_codes=["demo_synthetic"],
                        sample_size=sample, is_latest=True, computed_at=last_access, created_at=last_access))
                # 节点级认知
                if completed > 2:
                    node_sample = rng.sample(range(min(completed, len(node_list))), min(8, max(3, completed // 5)))
                    for ni in node_sample:
                        nperf = ng(rng, perf, 0.11, 0.08, 0.99)
                        conn.execute(T["cognitive_states"].insert().values(
                            student_id=st["uid"], course_id=c, node_id=node_list[ni][0],
                            observed_performance_score=round(nperf, 3),
                            evidence_confidence=round(clip(0.3 + 0.5 * rng.random(), 0.15, 0.95), 3),
                            confusion_risk=round(clip(1.0 - nperf + rng.gauss(0, 0.12), 0.02, 0.95), 3),
                            inquiry_depth=round(ng(rng, st["inquiry"], 0.12, 0.05, 0.97), 3),
                            hint_dependency=round(clip(1.0 - nperf * 0.7 + rng.gauss(0, 0.14), 0.05, 0.95), 3),
                            explanation_need=round(clip(0.52 - nperf * 0.32 + rng.gauss(0, 0.15), 0.05, 0.95), 3),
                            mastery_level=mastery_level(nperf), mastery_score=round(nperf, 3),
                            policy_version=COGNITIVE_POLICY, evidence_refs=[], reason_codes=["demo_synthetic"],
                            sample_size=min(12, max(2, sample // 3)), is_latest=True,
                            computed_at=last_access, created_at=last_access))

                # 学习投影（learning 过的 outline 节点，cap 60）
                outlines = outline_by_course[c]
                if outlines:
                    learned = min(len(outlines), max(1, int(len(outlines) * rate)))
                    sample_o = outlines[:learned]
                    if len(sample_o) > 60:
                        sample_o = sample_o[:30] + rng.sample(sample_o[30:], 30)
                    for oi, o in enumerate(sample_o):
                        onid, kgid = o
                        if oi == len(sample_o) - 1 and rng.random() < 0.4:
                            status = "IN_PROGRESS"
                            c_ratio = rng.uniform(0.3, 0.95)
                            comp_at = None
                        else:
                            status = "COMPLETED"
                            c_ratio = 1.0
                            comp_at = last_access - timedelta(minutes=rng.randint(0, 600))
                        t1 = last_access - timedelta(days=rng.randint(0, max(1, (NOW - st["start"]).days - 1)))
                        conn.execute(T["student_learning_projections"].insert().values(
                            student_id=st["uid"], course_id=c, release_id=release_id,
                            outline_node_id=onid, knowledge_node_key=kgid,
                            exposure_status=status,
                            exposure_seconds=int(per_node_min * 60 * c_ratio),
                            visit_count=rng.randint(1, 4), completion_ratio=round(c_ratio, 3),
                            completion_reason="explicit_complete" if status == "COMPLETED" else None,
                            current_timestamp=rng.uniform(0, 60), current_page=1,
                            first_accessed_at=t1, last_accessed_at=last_access,
                            completed_at=comp_at, last_event_id=None,
                            projection_version=1, updated_at=last_access))

                # 学习轨迹事件
                weights = (("question_answered", 0.5), ("cognition_refreshed", 0.25),
                           ("recommendation_issued", 0.15), ("teaching_response", 0.10))
                for k in range(rng.randint(8, 18)):
                    et = rng.choices([w[0] for w in weights], weights=[w[1] for w in weights])[0]
                    if et == "question_answered":
                        payload = {"score": round(rng.uniform(0.4, 1.0), 2), "correct": rng.random() < 0.7}
                    elif et == "cognition_refreshed":
                        payload = {"mastery": round(perf, 2), "confidence": round(clip(0.3 + 0.5 * rng.random(), 0.2, 0.95), 2)}
                    elif et == "recommendation_issued":
                        payload = {"rtype": rng.choice(["reinforce", "practice", "review"]),
                                   "priority": rng.choice(["low", "medium", "high"])}
                    else:
                        payload = {"intent": rng.choice(["explain", "compare", "example", "deepen"]),
                                   "action": rng.choice(["explain_concept", "ask_followup", "give_example"])}
                    ev_time = st["start"] + timedelta(days=rng.randint(0, max(0, (NOW - st["start"]).days - 1)),
                                                      hours=rng.randint(18, 22), minutes=rng.randint(0, 59))
                    if ev_time > NOW:
                        ev_time = NOW - timedelta(minutes=rng.randint(5, 600))
                    concept = rng.choice(node_list[: min(len(node_list), 200)])[1] if rng.random() < 0.7 else None
                    conn.execute(T["learning_trajectory_records"].insert().values(
                        student_id=st["uid"], course_id=c, event_type=et, concept_id=concept,
                        dedup_key=f"demo-{st['uid']}-{c}-{k}-{rng.randint(100, 999)}",
                        payload=payload, created_at=ev_time))

                enr_updates.append((st["uid"], c, completed, rate, total_min, last_access))
                if completed > 0:
                    last_course, last_node = c, node_list[min(completed - 1, len(node_list) - 1)][1]

            if last_course:
                conn.execute(T["users"].update().where(T["users"].c.id == st["uid"]).values(
                    last_active_course_id=last_course, last_learning_node=last_node,
                    updated_at=last_access))

        # 选课汇总更新
        for uid, c, completed, rate, minutes, last in enr_updates:
            conn.execute(T["student_enrollments"].update()
                         .where(T["student_enrollments"].c.student_id == uid,
                                T["student_enrollments"].c.course_id == c)
                         .values(total_nodes_completed=completed,
                                 overall_progress=round(rate, 4),
                                 avg_understanding_score=round(ng(rng, 0.66, 0.14, 0.2, 0.98), 3),
                                 avg_understanding_level=mastery_level(ng(rng, 0.66, 0.14, 0.2, 0.98)),
                                 total_study_minutes=int(minutes), last_study_time=last))

        # ---- 6. 课程统计投影（照 unified_learning_service 算法） ----
        memberships = conn.execute(
            sa.select(T["course_memberships"].c.user_id, T["course_memberships"].c.course_id)
            .where(T["course_memberships"].c.status == "ACTIVE",
                   T["course_memberships"].c.role == "STUDENT")).all()
        student_ids_by_course = {}
        for uid, cid in memberships:
            student_ids_by_course.setdefault(cid, []).append(uid)
        for cid, (release_id, _pm) in COURSES.items():
            for onid, kgid in outline_by_course[cid]:
                students_c = student_ids_by_course.get(cid, [])
                rows = conn.execute(
                    sa.select(T["student_learning_projections"].c.student_id,
                              T["student_learning_projections"].c.exposure_status)
                    .where(T["student_learning_projections"].c.course_id == cid,
                           T["student_learning_projections"].c.release_id == release_id,
                           T["student_learning_projections"].c.outline_node_id == onid)).all()
                counts = {"not_started": 0, "in_progress": 0, "completed": 0}
                for _uid, stt in rows:
                    counts[stt] = counts.get(stt, 0) + 1
                not_started = max(0, len(students_c) - counts["in_progress"] - counts["completed"])
                # mastery 聚合：kgid -> course_knowledge_nodes.id
                kn = conn.execute(
                    sa.select(T["course_knowledge_nodes"].c.id)
                    .where(T["course_knowledge_nodes"].c.course_id == cid,
                           T["course_knowledge_nodes"].c.node_key == kgid)).first()
                mastery_dist = {}
                unknown_n, low_conf, pending = 0, 0, 0
                if kn and students_c:
                    states = conn.execute(
                        sa.select(T["cognitive_states"].c.mastery_level,
                                  T["cognitive_states"].c.evidence_confidence)
                        .where(T["cognitive_states"].c.course_id == cid,
                               T["cognitive_states"].c.node_id == kn[0],
                               T["cognitive_states"].c.is_latest == True,
                               T["cognitive_states"].c.student_id.in_(students_c))).all()
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
                    low_confidence_count=low_conf, pending_recommendation_count=pending,
                    projection_version=1, computed_at=NOW))

        # ---- 统计输出 ----
        n_users = conn.execute(sa.select(sa.func.count()).select_from(T["users"])).scalar()
        n_lp = conn.execute(sa.select(sa.func.count()).select_from(T["learning_progress"])).scalar()
        n_np = conn.execute(sa.select(sa.func.count()).select_from(T["node_progress"])).scalar()
        n_cog = conn.execute(sa.select(sa.func.count()).select_from(T["cognitive_states"])).scalar()
        n_proj = conn.execute(sa.select(sa.func.count()).select_from(T["student_learning_projections"])).scalar()
        n_traj = conn.execute(sa.select(sa.func.count()).select_from(T["learning_trajectory_records"])).scalar()
        print(f"users={n_users} learning_progress={n_lp} node_progress={n_np} "
              f"cognitive_states={n_cog} projections={n_proj} trajectory={n_traj}")
        print("完成。演示账号密码统一为:", PASSWORD)
        if args.dry_run:
            raise RuntimeError("dry-run 完成，回滚本次全部写入")

    engine.dispose()


if __name__ == "__main__":
    main()
