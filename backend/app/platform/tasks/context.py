from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskType(str, Enum):
    """Known long-running task families for internal compatibility mapping."""

    DOCUMENT_PARSE = "document_parse"
    SCRIPT_GENERATION = "script_generation"
    PPT_GENERATION = "ppt_generation"
    TTS_NODE = "tts_node"
    TTS_BATCH = "tts_batch"
    DIGITAL_HUMAN_VIDEO = "digital_human_video"
    VOICE_CLONE = "voice_clone"
    PLATFORM_SYNC = "platform_sync"
    REMOTE_VIDEO = "remote_video"


@dataclass
class TaskContext:
    task_id: str | int | None = None
    task_type: TaskType | str | None = None
    user_id: int | None = None
    course_id: int | None = None
    node_id: int | None = None
    provider: str | None = None
    input_summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
