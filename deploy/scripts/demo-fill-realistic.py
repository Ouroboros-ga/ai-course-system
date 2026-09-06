# -*- coding: utf-8 -*-
"""修复学情面板数据真实性（v3）。

背景：v2 生成时用了全部 course_outline_nodes 做投影，而 analytics 面板按
course_releases.outline_version_id 只取该版本的 KNOWLEDGE_POINT 节点
（课程2=16 / 课程4=14 / 课程5=7），导致面板显示全部"未开始"、完成率 0%。
同时核心指标依赖的表（题库/答题/提问/Agent 事件）此前为空。

本脚本：
A. 按 release 版本节点重建 student_learning_projections 与
   course_learning_stats_projections（mastery_distribution 用前端契约的中文键
   '掌握'/'未掌握'）；
B. 基于课程知识点标题编造题库（每课程 25-30 题，PUBLISHED）；
C. 生成学生答题记录 question_attempts（参与率/正确率与学生掌握度相关）；
D. 生成提问深度 question_depth_records、Agent 互动 agent_learning_events、
   LLM 调用 agent_llm_diagnostic_records（question_count / interaction_count /
   ai_calls 指标）；
E. 生成 learning_events（趋势 activity）与 cognitive_states 历史版本
   （趋势 mastery 平滑）。

用法：python fill_demo_v3_realistic.py [--seed 20260817]
"""
from __future__ import annotations

import hashlib
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

NOW = datetime.now(timezone.utc)

RELEASES = {
    2: ("cr_17512d65a86641ffbc91feac8664f0f3", "ov_968925ca08a84a4bb7e9f5e86a966908"),
    4: ("cr_0f052b29f30e4a199bceab80e65dfc6d", "ov_036da934d3b2429eabed13d1ae8ea3a7"),
    5: ("cr_d0f072f8ec01460d847ea9887bb2414d", "ov_c840b889226c4dc887a82de8ab34c363"),
}
COURSE_NAME = {2: "汽车工程", 4: "数据结构", 5: "控制系统的数学模型"}
QUESTIONS_PER_COURSE = {2: 30, 4: 26, 5: 24}


def clip(v, lo, hi):
    return max(lo, min(hi, v))


def ng(rng, mu, sigma, lo, hi):
    return clip(rng.gauss(mu, sigma), lo, hi)


def h8(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]


def as_aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def dt_in(rng, start, end):
    span = (end - start).total_seconds()
    return start + timedelta(seconds=rng.uniform(0, span))


# ---------------- 题库模板 ----------------
_TRUE_OPTIONS = {"对": "正确", "错": "错误"}
_SA_POOL = [
    "请简述{title}的核心内容。",
    "结合实例说明{title}在{domain}中的应用。",
    "为什么说{title}是{domain}学习的基础？",
    "请归纳{title}的要点并给出一个应用场景。",
]


def _options_for(question_type, title, rng):
    if question_type == "TRUE_FALSE":
        return {"对": "正确", "错": "错误"}
    if question_type in ("SINGLE_CHOICE", "MULTI_CHOICE"):
        wrong = [
            "与{title}无关的干扰项", "常见易错说法（反向）", "过于绝对化的表述",
        ]
        opts = {
            "A": f"{title}是{title}这一概念的准确表述",
            "B": f"{wrong[0]}",
            "C": f"{wrong[1]}",
            "D": f"{wrong[2]}",
        }
        rng.shuffle(list(opts.keys()))
        return opts
    return {}


def _question_text(qtype, title, domain, rng):
    if qtype == "TRUE_FALSE":
        correct = rng.random() < 0.5
        stem = "（判断正误）" + (title if correct else f"与{title}含义相反的说法")
        return f"{stem}。"
    if qtype == "SINGLE_CHOICE":
        return f"关于“{title}”，下列说法正确的是？"
    if qtype == "MULTI_CHOICE":
        return f"以下关于“{title}”的表述，正确的有（多选）？"
    if qtype == "FILL_BLANK":
        return f"在{domain}中，“{title}”的核心概念可概括为____。"
    return rng.choice(_SA_POOL).format(title=title, domain=domain)


def _answer_for(qtype, rng):
    if qtype == "TRUE_FALSE":
        return "对" if rng.random() < 0.5 else "错"
    if qtype == "SINGLE_CHOICE":
        return rng.choice(["A", "B", "C", "D"])
    if qtype == "MULTI_CHOICE":
        return rng.choice(["A,B", "A,C", "A,D", "B,C", "A,B,C", "B,C,D"])
    if qtype == "FILL_BLANK":
        return "（定义与性质要点）"
    return "（要点：定义、性质、应用）"


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
        "course_outline_nodes", "course_knowledge_nodes", "course_memberships",
        "learning_progress", "cognitive_states", "student_learning_projections",
        "course_learning_stats_projections", "question_bank_items",
        "question_attempts", "question_depth_records", "agent_learning_events",
        "agent_llm_diagnostic_records", "learning_events", "users",
    ):
        meta.reflect(bind=engine, only=[t])
    T = meta.tables

    with engine.begin() as conn:
        # ============ 0. 课程事实 ============
        release_nodes = {}
        for cid, (rel, ov) in RELEASES.items():
            outs = conn.execute(
                sa.select(T["course_outline_nodes"].c.outline_node_id,
                          T["course_outline_nodes"].c.title)
                .where(T["course_outline_nodes"].c.outline_version_id == ov,
                       T["course_outline_nodes"].c.node_type == "KNOWLEDGE_POINT")
                .order_by(T["course_outline_nodes"].c.order_index)
            ).all()
            kns = conn.execute(
                sa.select(T["course_knowledge_nodes"].c.id,
                          T["course_knowledge_nodes"].c.node_key,
                          T["course_knowledge_nodes"].c.title)
                .where(T["course_knowledge_nodes"].c.course_id == cid)
            ).all()
            kn_by_title = {}
            for kid, kkey, ktitle in kns:
                kn_by_title.setdefault(ktitle, (kid, kkey))
            mapped = []
            for onid, otitle in outs:
                if otitle in kn_by_title:
                    kid, kkey = kn_by_title[otitle]
                    mapped.append({"onid": onid, "title": otitle, "kn_id": kid, "kkey": kkey})
            release_nodes[cid] = mapped
            print(f"课程 {cid}: release KNOWLEDGE_POINT={len(outs)} 匹配={len(mapped)}")

        memberships = conn.execute(
            sa.select(T["course_memberships"].c.user_id, T["course_memberships"].c.course_id)
            .where(T["course_memberships"].c.status == "ACTIVE",
                   T["course_memberships"].c.role == "STUDENT")
        ).all()
        per_course = {}
        for uid, cid in memberships:
            per_course.setdefault(cid, []).append(uid)
        for cid in RELEASES:
            print(f"课程 {cid}: 学生 {len(per_course.get(cid, []))} 人")

        # ============ A. 重建 projections + stats ============
        for cid, (rel, _ov) in RELEASES.items():
            conn.execute(T["student_learning_projections"].delete().where(
                T["student_learning_projections"].c.course_id == cid,
                T["student_learning_projections"].c.release_id == rel))
            conn.execute(T["course_learning_stats_projections"].delete().where(
                T["course_learning_stats_projections"].c.course_id == cid,
                T["course_learning_stats_projections"].c.release_id == rel))
            # 清掉 v2 生成的节点级认知（node_id 非空），统一按 release 节点重建
            conn.execute(T["cognitive_states"].delete().where(
                T["cognitive_states"].c.course_id == cid,
                T["cognitive_states"].c.node_id.is_not(None)))
        proj_n = 0
        node_cog_n = 0
        for uid, cid in memberships:
            if cid not in RELEASES:
                continue
            rel, _ov = RELEASES[cid]
            nodes = release_nodes[cid]
            if not nodes:
                continue
            lp = conn.execute(
                sa.select(T["learning_progress"].c.completion_rate,
                          T["learning_progress"].c.last_accessed_at,
                          T["learning_progress"].c.started_at)
                .where(T["learning_progress"].c.user_id == uid,
                       T["learning_progress"].c.course_id == cid)
            ).first()
            if lp is None:
                continue
            rate, last, started = lp
            rate = rate or 0.0
            last = as_aware(last)
            started = as_aware(started) if started else None
            # 课程级掌握度（决定节点级认知基准）
            cg = conn.execute(
                sa.select(T["cognitive_states"].c.mastery_score)
                .where(T["cognitive_states"].c.student_id == uid,
                       T["cognitive_states"].c.course_id == cid,
                       T["cognitive_states"].c.node_id.is_(None),
                       T["cognitive_states"].c.is_latest == True)
            ).first()
            base_ms = cg[0] if cg and cg[0] is not None else 0.5
            # 节点级认知：每 release 知识点一条（掌握度围绕课程级波动，像真实课堂）
            for nd in nodes:
                nms = ng(rng, base_ms, 0.10, 0.08, 0.99)
                conn.execute(T["cognitive_states"].insert().values(
                    student_id=uid, course_id=cid, node_id=nd["kn_id"],
                    observed_performance_score=round(ng(rng, nms, 0.06, 0.08, 0.99), 3),
                    evidence_confidence=round(clip(0.30 + 0.5 * rng.random(), 0.15, 0.95), 3),
                    confusion_risk=round(clip(1.0 - nms + rng.gauss(0, 0.12), 0.02, 0.95), 3),
                    inquiry_depth=round(ng(rng, 0.55, 0.18, 0.05, 0.97), 3),
                    hint_dependency=round(clip(1.0 - nms * 0.7 + rng.gauss(0, 0.14), 0.05, 0.95), 3),
                    explanation_need=round(clip(0.52 - nms * 0.32 + rng.gauss(0, 0.15), 0.05, 0.95), 3),
                    mastery_level="excellent" if nms >= 0.85 else ("high" if nms >= 0.70 else ("medium" if nms >= 0.45 else "low")),
                    mastery_score=round(nms, 3),
                    policy_version="cognitive-policy-v1.3", evidence_refs=[], reason_codes=["demo_synthetic"],
                    sample_size=rng.randint(3, 18), is_latest=True,
                    computed_at=last, created_at=last))
                node_cog_n += 1
            learned = max(0, min(len(nodes), int(round(len(nodes) * rate))))
            if learned == 0 and rate > 0.02:
                learned = 1
            for oi, nd in enumerate(nodes[:learned]):
                if oi == learned - 1 and rng.random() < 0.35:
                    status = "IN_PROGRESS"
                    c_ratio = rng.uniform(0.3, 0.95)
                    comp_at = None
                else:
                    status = "COMPLETED"
                    c_ratio = 1.0
                    comp_at = (last - timedelta(minutes=rng.randint(0, 600)))
                days_back = max(1, (NOW - (started or last)).days - 1)
                t1 = last - timedelta(days=rng.randint(0, days_back))
                conn.execute(T["student_learning_projections"].insert().values(
                    student_id=uid, course_id=cid, release_id=rel,
                    outline_node_id=nd["onid"], knowledge_node_key=nd["kkey"],
                    exposure_status=status,
                    exposure_seconds=int(rng.uniform(150, 420) * c_ratio),
                    visit_count=rng.randint(1, 4),
                    completion_ratio=round(c_ratio, 3),
                    completion_reason="explicit_complete" if status == "COMPLETED" else None,
                    current_timestamp=rng.uniform(0, 60), current_page=1,
                    first_accessed_at=t1, last_accessed_at=last,
                    completed_at=comp_at, last_event_id=None,
                    projection_version=1, updated_at=last))
                proj_n += 1
        print(f"A. projections 重建 {proj_n} 条；节点级认知 {node_cog_n} 条")

        stats_n = 0
        for cid, (rel, _ov) in RELEASES.items():
            students_c = per_course.get(cid, [])
            for nd in release_nodes[cid]:
                rows = conn.execute(
                    sa.select(T["student_learning_projections"].c.exposure_status)
                    .where(T["student_learning_projections"].c.course_id == cid,
                           T["student_learning_projections"].c.release_id == rel,
                           T["student_learning_projections"].c.outline_node_id == nd["onid"])
                ).all()
                counts = {"IN_PROGRESS": 0, "COMPLETED": 0}
                for (stt,) in rows:
                    counts[stt] = counts.get(stt, 0) + 1
                not_started = max(0, len(students_c) - counts["IN_PROGRESS"] - counts["COMPLETED"])
                mastered = 0
                low_conf = 0
                unknown_n = 0
                if students_c:
                    states = conn.execute(
                        sa.select(T["cognitive_states"].c.mastery_level,
                                  T["cognitive_states"].c.evidence_confidence)
                        .where(T["cognitive_states"].c.course_id == cid,
                               T["cognitive_states"].c.node_id == nd["kn_id"],
                               T["cognitive_states"].c.is_latest == True,
                               T["cognitive_states"].c.student_id.in_(students_c))
                    ).all()
                    for lv, conf in states:
                        lv = lv or "unknown"
                        if lv in ("excellent", "high"):
                            mastered += 1
                        elif lv == "unknown":
                            unknown_n += 1
                        if conf is None or conf < 0.5:
                            low_conf += 1
                    unknown_n += max(0, len(students_c) - len(states))
                conn.execute(T["course_learning_stats_projections"].insert().values(
                    course_id=cid, release_id=rel, outline_node_id=nd["onid"],
                    student_count=len(students_c), not_started_count=not_started,
                    in_progress_count=counts["IN_PROGRESS"], completed_count=counts["COMPLETED"],
                    mastery_distribution={"掌握": mastered, "未掌握": len(students_c) - mastered},
                    unknown_mastery_count=unknown_n,
                    low_confidence_count=low_conf, pending_recommendation_count=0,
                    projection_version=1, computed_at=NOW))
                stats_n += 1
        print(f"A. stats 重建 {stats_n} 条")

        # ============ B. 题库 ============
        q_types_pool = ["SINGLE_CHOICE"] * 12 + ["TRUE_FALSE"] * 6 + ["MULTI_CHOICE"] * 4 + \
                       ["FILL_BLANK"] * 3 + ["SHORT_ANSWER"] * 3
        qb_n = 0
        for cid, n_q in QUESTIONS_PER_COURSE.items():
            nodes = release_nodes[cid]
            domain = COURSE_NAME[cid]
            for i in range(n_q):
                nd = nodes[i % len(nodes)]
                qtype = rng.choice(q_types_pool)
                qtext = _question_text(qtype, nd["title"], domain, rng)
                answer = _answer_for(qtype, rng)
                created = dt_in(rng, NOW - timedelta(days=60), NOW - timedelta(days=3))
                conn.execute(T["question_bank_items"].insert().values(
                    question_text=qtext, answer=answer,
                    options=_options_for(qtype, nd["title"], rng),
                    similar_questions=[], question_type=qtype,
                    difficulty=rng.choice(["EASY", "MEDIUM", "HARD"]),
                    category=domain, match_mode="exact", rule_status="NONE",
                    course_id=cid, knowledge_node_ids=[nd["kn_id"]],
                    prerequisite_node_ids=[], status="PUBLISHED", version=1,
                    prev_version_id=None, is_latest=True, import_batch_id=None,
                    source_row_index=None, generated_by="teacher_manual",
                    generation_metadata={}, created_by=1,
                    created_at=created, updated_at=created,
                    published_at=created, published_by=1))
                qb_n += 1
        print(f"B. 题库 {qb_n} 道")

        # ============ C. 答题记录 ============
        q_by_course = {}
        for cid in RELEASES:
            qs = conn.execute(
                sa.select(T["question_bank_items"].c.id, T["question_bank_items"].c.question_type)
                .where(T["question_bank_items"].c.course_id == cid,
                       T["question_bank_items"].c.status == "PUBLISHED")
            ).all()
            q_by_course[cid] = [tuple(r) for r in qs]
        att_n = 0
        # 学生课程级掌握度
        mastery_by_sc = {}
        for uid, cid in memberships:
            if cid not in RELEASES:
                continue
            ms = conn.execute(
                sa.select(T["cognitive_states"].c.mastery_score)
                .where(T["cognitive_states"].c.student_id == uid,
                       T["cognitive_states"].c.course_id == cid,
                       T["cognitive_states"].c.node_id.is_(None),
                       T["cognitive_states"].c.is_latest == True)
            ).first()
            mastery_by_sc[(uid, cid)] = (ms[0] if ms and ms[0] is not None else 0.5)
        for cid, qs in q_by_course.items():
            students_c = per_course.get(cid, [])
            participants = rng.sample(students_c, int(len(students_c) * rng.uniform(0.65, 0.85)))
            for uid in participants:
                ms = mastery_by_sc.get((uid, cid), 0.5)
                n_att = rng.randint(3, 12)
                for _ in range(n_att):
                    qid, qtype = rng.choice(qs)
                    p_correct = clip(0.30 + 0.55 * ms + rng.gauss(0, 0.12), 0.12, 0.98)
                    correct = rng.random() < p_correct
                    if qtype == "TRUE_FALSE":
                        s_answer = rng.choice(["对", "错"])
                    elif qtype == "SINGLE_CHOICE":
                        s_answer = rng.choice(["A", "B", "C", "D"])
                    elif qtype == "MULTI_CHOICE":
                        s_answer = rng.choice(["A,B", "A,C", "B,C", "A,B,C", "A,C,D"])
                    else:
                        s_answer = "（学生作答内容）"
                    created = dt_in(rng, NOW - timedelta(days=30), NOW - timedelta(minutes=30))
                    conn.execute(T["question_attempts"].insert().values(
                        question_id=qid, course_id=cid, student_id=uid,
                        source_event_id=f"demo-att-{uuid.uuid4().hex}",
                        measurement_role="scored_performance", question_version=1,
                        question_content_hash=h8(f"{qid}-{uid}"),
                        student_answer=s_answer, is_correct=correct,
                        score=1.0 if correct else 0.0,
                        cognitive_context={"mastery": round(ms, 3)},
                        judged_by="auto", judge_feedback="",
                        created_at=created, judged_at=created + timedelta(seconds=rng.randint(1, 5))))
                    att_n += 1
        print(f"C. 答题记录 {att_n} 条")

        # ============ D. 提问深度 / Agent 互动 / LLM 调用 ============
        depth_n = 0
        for uid, cid in memberships:
            if cid not in RELEASES:
                continue
            for _ in range(rng.randint(1, 3)):
                ds = ng(rng, 0.55, 0.18, 0.2, 0.95)
                label = "recall" if ds < 0.4 else ("apply" if ds < 0.7 else "analyze")
                conn.execute(T["question_depth_records"].insert().values(
                    student_id=uid, course_id=cid, node_id=None,
                    depth_score=round(ds, 3), depth_label=label,
                    trace_id=f"trc-{uuid.uuid4().hex[:16]}", source="teaching_agent",
                    created_at=dt_in(rng, NOW - timedelta(days=30), NOW - timedelta(minutes=30))))
                depth_n += 1
        print(f"D. 提问深度 {depth_n} 条")

        agent_ev_n = 0
        for uid, cid in memberships:
            if cid not in RELEASES:
                continue
            for _ in range(rng.randint(2, 6)):
                conn.execute(T["agent_learning_events"].insert().values(
                    trace_id=f"trc-{uuid.uuid4().hex[:16]}", student_id=uid, course_id=cid,
                    session_id=f"ses-{uuid.uuid4().hex[:12]}",
                    event_type="teaching_agent_response",
                    event_data="{}", data_policy_version="agent-log-minimization/1",
                    migration_batch_id="demo-synthetic-20260817",
                    created_at=dt_in(rng, NOW - timedelta(days=30), NOW - timedelta(minutes=30))))
                agent_ev_n += 1
        print(f"D. Agent 互动事件 {agent_ev_n} 条")

        llm_n = 0
        for cid in RELEASES:
            for _ in range(rng.randint(120, 260)):
                fr = rng.choices(["stop", "length", "error"], weights=[0.9, 0.05, 0.05])[0]
                conn.execute(T["agent_llm_diagnostic_records"].insert().values(
                    diagnostic_id=f"diag-{uuid.uuid4().hex[:20]}",
                    run_id=f"run-{uuid.uuid4().hex[:12]}",
                    trace_id=f"trc-{uuid.uuid4().hex[:16]}",
                    course_id=cid, agent_type="teaching", stage="teaching_response",
                    node="teaching_agent", purpose="teaching_answer",
                    prompt_version="teaching-v1.3", schema_name="teaching_v1",
                    model="deepseek-v4-flash", attempt=1, repaired=False,
                    finish_reason=fr, input_tokens=rng.randint(200, 1200),
                    output_tokens=rng.randint(80, 900),
                    input_chars=rng.randint(300, 3000), output_chars=rng.randint(100, 2500),
                    response_hash=h8(str(rng.random())), truncated=False,
                    response_format_requested=False, response_format_fallback=False,
                    validation_errors=0, usage_metadata={},
                    latency_ms=rng.uniform(800, 16000),
                    created_at=dt_in(rng, NOW - timedelta(days=30), NOW - timedelta(minutes=30))))
                llm_n += 1
        print(f"D. LLM 调用 {llm_n} 条")

        # ============ E. learning_events（趋势 activity） ============
        ev_n = 0
        ev_types = ["NODE_OPENED", "MEDIA_PROGRESS", "EXPLICIT_COMPLETE"]
        for uid, cid in memberships:
            if cid not in RELEASES:
                continue
            rel, _ov = RELEASES[cid]
            nodes = release_nodes[cid]
            if not nodes:
                continue
            for _ in range(rng.randint(3, 10)):
                nd = rng.choice(nodes)
                et = rng.choice(ev_types)
                occurred = dt_in(rng, NOW - timedelta(days=30), NOW - timedelta(minutes=30))
                conn.execute(T["learning_events"].insert().values(
                    event_id=f"le_{uuid.uuid4().hex}", idempotency_key=f"demo-{uid}-{cid}-{uuid.uuid4().hex[:10]}",
                    student_id=uid, course_id=cid, release_id=rel,
                    outline_node_id=nd["onid"], knowledge_node_key=nd["kkey"],
                    event_type=et, occurred_at=occurred,
                    payload={"demo": True}, source="learn_page",
                    schema_version=1, created_at=occurred))
                ev_n += 1
        print(f"E. learning_events {ev_n} 条")

        # ============ F. cognitive_states 历史版本（趋势 mastery 平滑） ============
        hist_n = 0
        base_states = conn.execute(
            sa.select(T["cognitive_states"].c.student_id, T["cognitive_states"].c.course_id,
                      T["cognitive_states"].c.mastery_score,
                      T["cognitive_states"].c.observed_performance_score,
                      T["cognitive_states"].c.evidence_confidence,
                      T["cognitive_states"].c.confusion_risk,
                      T["cognitive_states"].c.inquiry_depth,
                      T["cognitive_states"].c.hint_dependency,
                      T["cognitive_states"].c.explanation_need)
            .where(T["cognitive_states"].c.node_id.is_(None),
                   T["cognitive_states"].c.is_latest == True,
                   T["cognitive_states"].c.mastery_score.is_not(None))
        ).all()
        for uid, cid, ms, perf, conf, cr, iq, hd, en in base_states:
            n_hist = rng.randint(5, 10)
            for _ in range(n_hist):
                day = NOW - timedelta(days=rng.randint(1, 29), hours=rng.randint(0, 23))
                drift = ng(rng, 0.0, 0.05, -0.15, 0.15)
                conn.execute(T["cognitive_states"].insert().values(
                    student_id=uid, course_id=cid, node_id=None,
                    observed_performance_score=round(clip(perf + drift, 0.1, 0.99), 3),
                    evidence_confidence=round(clip(conf + rng.gauss(0, 0.05), 0.1, 0.98), 3),
                    confusion_risk=round(clip(cr + rng.gauss(0, 0.06), 0.02, 0.95), 3),
                    inquiry_depth=round(clip(iq + rng.gauss(0, 0.06), 0.05, 0.97), 3),
                    hint_dependency=round(clip(hd + rng.gauss(0, 0.06), 0.05, 0.95), 3),
                    explanation_need=round(clip(en + rng.gauss(0, 0.06), 0.05, 0.95), 3),
                    mastery_level="medium" if ms else "unknown",
                    mastery_score=round(clip(ms + drift, 0.05, 0.99), 3),
                    policy_version="cognitive-policy-v1.3", evidence_refs=[], reason_codes=["demo_history"],
                    sample_size=max(1, int(ms * 30)), is_latest=False,
                    computed_at=day, created_at=day))
                hist_n += 1
        print(f"F. 认知历史 {hist_n} 条")

        print("== 完成 ==")

    engine.dispose()


if __name__ == "__main__":
    main()
