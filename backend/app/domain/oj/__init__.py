"""OJ 域（bounded context）。

把仓库里以 ``experiment_*`` 命名的课程编程实验域，正式定义为 OJ 域。
**不新建第二套 problem / submission 表**，见
``docs/adr/ADR-0001-oj-domain-consolidation.md``。

目录约定：``backend/app/domain/oj/``（与 ``domain/`` 下既有
education_graph / knowledge_bundle / learning / safety / student_memory 并列）。
不新增 ``backend/app/modules/``——那会成为仓库第三套目录约定。

子域：

- ``judging/``：判题语义（状态 / 判定分离）、Judge0 出口收拢、编排
- ``submissions/``：Attempt / Run 语义
- ``problems/``：题目与版本
- ``intelligence/``：诊断 / 提示 / 讲解（CodeNexus 差异化能力）
- ``activities/``：作业 / 比赛 / 考试（真正新增）
- ``scoreboard/``：排名（真正新增）
- ``analytics/``：OJ 事实聚合（真正新增）
"""

from __future__ import annotations

__all__ = ["judging", "submissions"]
