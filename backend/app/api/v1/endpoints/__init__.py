# app/api/v1/endpoints/__init__.py
"""
API v1 端点模块
导出所有具体的接口路由对象
"""

from . import user
# from . import smart_course
# from . import qa
# from . import progress
# from . import common
# from . import platform

__all__ = [
    "user",
    # "smart_course",
    # "qa",
    # "progress",
    # "common",
    # "platform"
]