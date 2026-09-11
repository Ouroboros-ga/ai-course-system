"""判题 Provider 实现。

**约定（ADR-0001 决定 3）：Judge0 的 HTTP 细节只允许出现在本目录内。**
业务层（``domain/oj/**`` 与 ``services/**``）只应见到归一化后的
``RunVerdict`` / ``SandboxResult``，不认识 Judge0 的 status id、token 与 payload 形状。

当前只有一个实现：

- ``judge0.py`` —— Judge0 CE 客户端（原 ``app/services/sandbox_client.py``，
  PR-02 迁入）。是 Judge0 的**唯一出口**。

未来若要换评测后端（ADR-0001 决定 3 的延伸），在此并列新增实现，
上层 Submission / Activity 不用改。
"""

from __future__ import annotations

__all__ = ["judge0"]
