"""泛雅·超星 AI 开放 API 参考兼容包。

This package is deliberately optional. ``app.main`` discovers it at runtime;
removing this directory disables only the compatibility endpoints.
"""

from .router import router

__all__ = ["router"]
