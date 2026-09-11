"""提交语义子域（Attempt / Run）。

PR-01 只落地 ``RunType``。Attempt / Run 的拆分（拆 ``experiment_service.py``）
在 PR-04；学生侧 façade（题库 / 我的提交 / 提交详情）在 PR-10。
"""

from __future__ import annotations

__all__ = ["run_types"]
