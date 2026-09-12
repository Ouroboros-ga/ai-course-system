"""学习分析管道回填 · 课程15「算法」60 名 Demo 学生

根因：学习分析界面（/facade/course/15/analytics）读取的是
CourseMembership + StudentLearningProjection + CourseLearningStatsProjection，
而此前只造了 StudentEnrollment + NodeProgress + cognitive_states（六维认知管道），
两条管道互不相通 → 教师界面只看到 2 个老学员。

本脚本复用真实服务函数 record_event / refresh_course_stats，保证与系统正常
学习行为产出的数据完全一致，并顺带填充 LearningEvent（7 日趋势图用）。

- 每个学生按已有 LearningProgress 的整体完成率 r（正态 N(0.60,0.15)）映射到
  8 个大纲知识点：完成前 done_n 个（前缀完成，模拟"越靠后越多人掉队"），
  第 done_n+1 个标 IN_PROGRESS，其余未开始（无投影行）。
- 事件时间分散在过去 7 天（每生一个"活跃日"），趋势图可见。
- 幂等：membership 按 (user_id,course_id) 跳过；投影事件按 idempotency_key 去重；
  stats 由 refresh_course_stats upsert。

用法：
    python backfill_learning_analytics.py --dry-run   # 只打印计划
    python backfill_learning_analytics.py             # 实际写入
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

from app.core.time_utils import utcnow_aware  # noqa: E402
from app.models.database import engine  # noqa: E402
from app.models.user_model import User  # noqa: E402
from app.models.progress_model import LearningProgress  # noqa: E402
from app.models.access_control_model import (  # noqa: E402
    CourseMembership,
    CourseRole,
    MembershipStatus,
)
from app.models.unified_learning_model import LearningEventType  # noqa: E402
from app.services.unified_learning_service import (  # noqa: E402
    active_release,
    record_event,
    refresh_course_stats,
    release_nodes,
)

COURSE_ID = 15
SOURCE = "demo_backfill"


def _student_ids() -> list[str]:
    ids = []
    for major in ("0417", "0418"):
        for cls in ("01", "02", "03", "04", "05"):
            for seq in ("01", "02", "03", "04", "05", "06"):
                ids.append(f"{major}25{cls}{seq}")
    return ids


def _event_time(now, day_offset: int, minute: int) -> datetime.datetime:
    day = (now - datetime.timedelta(days=day_offset)).replace(hour=9, minute=0, second=0, microsecond=0)
    t = day + datetime.timedelta(minutes=minute)
    # 服务器为 UTC，当前若早于当天 09:00，则当天学习事件须回退到过去，避免 OCCURRED_AT_IN_FUTURE
    if t >= now:
        t = now - datetime.timedelta(minutes=5)
    return t


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--seed", type=int, default=20260908)
    args = parser.parse_args()
    random.seed(args.seed)

    ids = _student_ids()
    now = utcnow_aware()

    with Session(engine) as s:
        release = active_release(s, COURSE_ID)
        if release is None:
            print("[error] 课程15无活跃发布")
            return 1
        nodes = release_nodes(s, release)
        if not nodes:
            print("[error] 活跃发布无知识点大纲节点")
            return 1
        users = {u.username: u.id for u in s.exec(select(User).where(User.username.in_(ids))).all()}
        missing = [sid for sid in ids if sid not in users]
        if missing:
            print(f"[warn] 缺少账号 {len(missing)} 个：{missing[:5]}... 先跑 gen_demo_students.py --stage accounts")
        lps = {
            lp.user_id: lp
            for lp in s.exec(select(LearningProgress).where(LearningProgress.course_id == COURSE_ID)).all()
        }
        # 现有 membership 快照（幂等判断）
        existing_memberships = {
            m.user_id
            for m in s.exec(select(CourseMembership).where(CourseMembership.course_id == COURSE_ID)).all()
        }

        print(f"[info] release_id={release.release_id}  大纲知识点数={len(nodes)}")
        for i, n in enumerate(nodes):
            print(f"  [{i}] {n.outline_node_id}  {n.title}")

        # 计算每个学生的 done_n（基于已有 LearningProgress 完成率）
        plan = []  # (sid, uid, done_n, day_offset)
        for sid in ids:
            uid = users.get(sid)
            if uid is None:
                continue
            lp = lps.get(uid)
            if lp is None or lp.total_nodes <= 0:
                ratio = 0.0
            else:
                ratio = lp.completed_nodes / lp.total_nodes
            done_n = int(round(ratio * len(nodes)))
            done_n = max(0, min(len(nodes), done_n))
            day_offset = random.randint(0, 6)
            plan.append((sid, uid, done_n, day_offset))

        print(f"\n[info] 计划：{len(plan)} 名学生（membership 需新建 {sum(1 for p in plan if p[1] not in existing_memberships)} 人）")
        # 分布预览
        dist = {}
        for _, _, done_n, _ in plan:
            dist[done_n] = dist.get(done_n, 0) + 1
        print(f"[info] 完成知识点数分布：{dict(sorted(dist.items()))}")

        if args.dry_run:
            print("\n[dry-run] 未写入任何数据")
            return 0

        # ---- 1) CourseMembership
        new_mem = 0
        for sid, uid, done_n, day_offset in plan:
            if uid in existing_memberships:
                continue
            s.add(CourseMembership(
                user_id=uid,
                course_id=COURSE_ID,
                role=CourseRole.STUDENT,
                status=MembershipStatus.ACTIVE,
                permission_overrides={},
                analytics_excluded=False,
                joined_at=_event_time(now, day_offset, 0),
            ))
            existing_memberships.add(uid)
            new_mem += 1
        s.commit()
        print(f"[done] CourseMembership 新建 {new_mem} 人")

        # ---- 2) 投影事件（NODE_OPENED + 完成/进行中）
        open_events = 0
        prog_events = 0
        complete_events = 0
        for sid, uid, done_n, day_offset in plan:
            for i, node in enumerate(nodes):
                if i < done_n:
                    # 完成：先打开，后显式完成（时间相差 ~20 分钟）
                    record_event(
                        s, student_id=uid, course_id=COURSE_ID, release_id=release.release_id,
                        outline_node_id=node.outline_node_id, event_type=LearningEventType.NODE_OPENED,
                        idempotency_key=f"demo_analytics_{sid}_{node.outline_node_id}_open",
                        payload={}, occurred_at=_event_time(now, day_offset, 10 + i), source=SOURCE,
                    )
                    open_events += 1
                    record_event(
                        s, student_id=uid, course_id=COURSE_ID, release_id=release.release_id,
                        outline_node_id=node.outline_node_id, event_type=LearningEventType.EXPLICIT_COMPLETE,
                        idempotency_key=f"demo_analytics_{sid}_{node.outline_node_id}_complete",
                        payload={"action": "complete"}, occurred_at=_event_time(now, day_offset, 30 + i * 3), source=SOURCE,
                    )
                    complete_events += 1
                elif i == done_n and done_n < len(nodes):
                    # 进行中：打开 + 观看到一半
                    record_event(
                        s, student_id=uid, course_id=COURSE_ID, release_id=release.release_id,
                        outline_node_id=node.outline_node_id, event_type=LearningEventType.NODE_OPENED,
                        idempotency_key=f"demo_analytics_{sid}_{node.outline_node_id}_open",
                        payload={}, occurred_at=_event_time(now, day_offset, 10 + i), source=SOURCE,
                    )
                    open_events += 1
                    record_event(
                        s, student_id=uid, course_id=COURSE_ID, release_id=release.release_id,
                        outline_node_id=node.outline_node_id, event_type=LearningEventType.MEDIA_PROGRESS,
                        idempotency_key=f"demo_analytics_{sid}_{node.outline_node_id}_progress",
                        payload={"completion_ratio": 0.5, "time_spent_delta": 120, "current_timestamp": 0.5},
                        occurred_at=_event_time(now, day_offset, 25 + i * 3), source=SOURCE,
                    )
                    prog_events += 1
                # else: 未开始，无投影行
            if open_events % 200 == 0:
                s.commit()
                print(f"  ... 已处理 {open_events} 条打开事件", flush=True)
        s.commit()
        print(f"[done] 投影事件：NODE_OPENED={open_events}，EXPLICIT_COMPLETE={complete_events}，MEDIA_PROGRESS={prog_events}")

        # ---- 3) 汇总统计
        refresh_course_stats(s, course_id=COURSE_ID, release_id=release.release_id)
        s.commit()
        print("[done] CourseLearningStatsProjection 已刷新（8 节点）")

    print("\n[完成] 学习分析管道回填结束")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
