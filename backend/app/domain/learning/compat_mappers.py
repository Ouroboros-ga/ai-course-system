"""
Existing-data compatibility mappers.

Maps current progress, quiz, chat, and jump data into LearningEvent shape.
These are READ-ONLY mappers that inspect existing data structures without
modifying them. They produce new LearningEvent objects suitable for feeding
into the event store or evidence aggregator.

Version: 1.0
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .event import EventType, LearningEvent


# =========================================================================
# Progress data mappers
# =========================================================================


def map_progress_to_events(
    progress_data: Dict[str, Any],
    student_id: int,
    course_id: int,
    base_sequence: int = 0,
) -> List[LearningEvent]:
    """Map existing LearningProgress/NodeProgress data to LearningEvents.

    Parameters
    ----------
    progress_data : dict
        Dict containing progress info. Expected keys:
        - ``completion_rate`` (float)
        - ``status`` (str, e.g. ``in_progress``, ``completed``)
        - ``nodes`` (list of dicts with ``id``, ``is_completed``,
          ``first_accessed_at``, ``completed_at``)
    student_id : int
        The student user ID.
    course_id : int
        The course ID.
    base_sequence : int
        Starting sequence number for generated events.

    Returns
    -------
    list of LearningEvent
    """
    events: List[LearningEvent] = []
    seq = base_sequence

    # Course-level events
    status = progress_data.get("status", "")
    if status == "completed":
        events.append(
            LearningEvent(
                event_type=EventType.COURSE_COMPLETED,
                student_id=student_id,
                course_id=course_id,
                sequence_number=seq,
                metadata={
                    "completion_rate": progress_data.get("completion_rate", 0.0),
                },
                source="compat_mapper:progress",
            )
        )
        seq += 1

    # Node-level events
    nodes = progress_data.get("nodes", [])
    for node in nodes:
        node_id = node.get("id")
        if node_id is None:
            continue

        is_completed = node.get("is_completed", False)

        events.append(
            LearningEvent(
                event_type=EventType.NODE_ACCESSED,
                student_id=student_id,
                course_id=course_id,
                node_id=node_id,
                sequence_number=seq,
                metadata={
                    "first_accessed_at": node.get("first_accessed_at"),
                    "node_index": node.get("index"),
                    "node_title": node.get("title"),
                },
                source="compat_mapper:progress",
            )
        )
        seq += 1

        if is_completed:
            events.append(
                LearningEvent(
                    event_type=EventType.NODE_COMPLETED,
                    student_id=student_id,
                    course_id=course_id,
                    node_id=node_id,
                    sequence_number=seq,
                    metadata={
                        "completed_at": node.get("completed_at"),
                    },
                    source="compat_mapper:progress",
                )
            )
            seq += 1

    return events


# =========================================================================
# Quiz data mappers
# =========================================================================


def map_quiz_to_events(
    quiz_data: Dict[str, Any],
    student_id: int,
    course_id: int,
    base_sequence: int = 0,
) -> List[LearningEvent]:
    """Map existing quiz data to LearningEvents.

    Parameters
    ----------
    quiz_data : dict
        Dict containing quiz info. Expected keys:
        - ``quiz_id`` (str or int)
        - ``node_id`` (int, optional)
        - ``question`` (str)
        - ``student_answer`` (str)
        - ``correct_answer`` (str)
        - ``is_correct`` (bool)
    student_id : int
        The student user ID.
    course_id : int
        The course ID.
    base_sequence : int
        Starting sequence number.

    Returns
    -------
    list of LearningEvent
    """
    events: List[LearningEvent] = []
    seq = base_sequence

    events.append(
        LearningEvent(
            event_type=EventType.QUIZ_ANSWERED,
            student_id=student_id,
            course_id=course_id,
            node_id=quiz_data.get("node_id"),
            sequence_number=seq,
            metadata={
                "quiz_id": str(quiz_data.get("quiz_id", "")),
                "question": quiz_data.get("question", ""),
                "student_answer": quiz_data.get("student_answer", ""),
                "correct_answer": quiz_data.get("correct_answer", ""),
                "is_correct": quiz_data.get("is_correct", False),
            },
            source="compat_mapper:quiz",
        )
    )
    seq += 1

    is_correct = quiz_data.get("is_correct", False)
    events.append(
        LearningEvent(
            event_type=EventType.QUIZ_CORRECT if is_correct else EventType.QUIZ_INCORRECT,
            student_id=student_id,
            course_id=course_id,
            node_id=quiz_data.get("node_id"),
            sequence_number=seq,
            metadata={
                "quiz_id": str(quiz_data.get("quiz_id", "")),
            },
            source="compat_mapper:quiz",
        )
    )

    return events


# =========================================================================
# Chat/QA data mappers
# =========================================================================


def map_chat_to_events(
    chat_data: Dict[str, Any],
    student_id: int,
    course_id: int,
    base_sequence: int = 0,
) -> List[LearningEvent]:
    """Map existing chat/QA message data to LearningEvents.

    Parameters
    ----------
    chat_data : dict
        Dict containing chat message info. Expected keys:
        - ``message_id`` (str or int)
        - ``node_id`` (int, optional)
        - ``question`` (str)
        - ``answer`` (str, optional)
        - ``created_at`` (str, optional)
    student_id : int
        The student user ID.
    course_id : int
        The course ID.
    base_sequence : int
        Starting sequence number.

    Returns
    -------
    list of LearningEvent
    """
    events: List[LearningEvent] = []
    seq = base_sequence

    events.append(
        LearningEvent(
            event_type=EventType.QUESTION_ASKED,
            student_id=student_id,
            course_id=course_id,
            node_id=chat_data.get("node_id"),
            sequence_number=seq,
            metadata={
                "message_id": str(chat_data.get("message_id", "")),
                "question": chat_data.get("question", ""),
            },
            source="compat_mapper:chat",
        )
    )
    seq += 1

    if chat_data.get("answer"):
        events.append(
            LearningEvent(
                event_type=EventType.ANSWER_RECEIVED,
                student_id=student_id,
                course_id=course_id,
                node_id=chat_data.get("node_id"),
                sequence_number=seq,
                metadata={
                    "message_id": str(chat_data.get("message_id", "")),
                    "answer_preview": chat_data["answer"][:200],
                },
                source="compat_mapper:chat",
            )
        )

    return events


# =========================================================================
# Prerequisite jump data mappers
# =========================================================================


def map_jump_to_events(
    jump_data: Dict[str, Any],
    student_id: int,
    course_id: int,
    base_sequence: int = 0,
) -> List[LearningEvent]:
    """Map existing LearningJumpHistory data to LearningEvents.

    Parameters
    ----------
    jump_data : dict
        Dict containing jump history info. Expected keys:
        - ``jump_id`` (int)
        - ``from_node_id`` (int)
        - ``to_node_id`` (int)
        - ``trigger_type`` (str)
        - ``trigger_question`` (str, optional)
        - ``gap_description`` (str, optional)
        - ``is_returned`` (bool)
    student_id : int
        The student user ID.
    course_id : int
        The course ID.
    base_sequence : int
        Starting sequence number.

    Returns
    -------
    list of LearningEvent
    """
    events: List[LearningEvent] = []
    seq = base_sequence

    # Gap detected
    events.append(
        LearningEvent(
            event_type=EventType.PREREQ_GAP_DETECTED,
            student_id=student_id,
            course_id=course_id,
            node_id=jump_data.get("from_node_id"),
            sequence_number=seq,
            metadata={
                "jump_id": jump_data.get("jump_id"),
                "target_node_id": jump_data.get("to_node_id"),
                "trigger_type": jump_data.get("trigger_type", ""),
                "trigger_question": jump_data.get("trigger_question", ""),
                "gap_description": jump_data.get("gap_description", ""),
            },
            source="compat_mapper:prerequisite",
        )
    )
    seq += 1

    # Jump started
    events.append(
        LearningEvent(
            event_type=EventType.PREREQ_JUMP_STARTED,
            student_id=student_id,
            course_id=course_id,
            node_id=jump_data.get("to_node_id"),
            sequence_number=seq,
            metadata={
                "jump_id": jump_data.get("jump_id"),
                "from_node_id": jump_data.get("from_node_id"),
                "trigger_type": jump_data.get("trigger_type", ""),
            },
            source="compat_mapper:prerequisite",
        )
    )
    seq += 1

    # Returned
    if jump_data.get("is_returned", False):
        events.append(
            LearningEvent(
                event_type=EventType.PREREQ_JUMP_RETURNED,
                student_id=student_id,
                course_id=course_id,
                node_id=jump_data.get("from_node_id"),
                sequence_number=seq,
                metadata={
                    "jump_id": jump_data.get("jump_id"),
                    "review_node_id": jump_data.get("to_node_id"),
                },
                source="compat_mapper:prerequisite",
            )
        )

    return events


# =========================================================================
# Convenience mapper
# =========================================================================


class ExistingDataMapper:
    """Convenience class for mapping existing data to LearningEvents.

    Usage::

        mapper = ExistingDataMapper(student_id=42, course_id=101)
        events = mapper.map_all(
            progress_data=progress_dict,
            quiz_data_list=[quiz1_dict, quiz2_dict],
            chat_data_list=[chat1_dict],
            jump_data_list=[jump1_dict],
        )
    """

    def __init__(self, student_id: int, course_id: int):
        self.student_id = student_id
        self.course_id = course_id

    def map_all(
        self,
        progress_data: Optional[Dict[str, Any]] = None,
        quiz_data_list: Optional[List[Dict[str, Any]]] = None,
        chat_data_list: Optional[List[Dict[str, Any]]] = None,
        jump_data_list: Optional[List[Dict[str, Any]]] = None,
    ) -> List[LearningEvent]:
        """Map all provided data sources into a single ordered event list."""
        all_events: List[LearningEvent] = []
        seq = 0

        if progress_data:
            events = map_progress_to_events(
                progress_data, self.student_id, self.course_id, base_sequence=seq
            )
            all_events.extend(events)
            seq += len(events)

        if quiz_data_list:
            for qd in quiz_data_list:
                events = map_quiz_to_events(
                    qd, self.student_id, self.course_id, base_sequence=seq
                )
                all_events.extend(events)
                seq += len(events)

        if chat_data_list:
            for cd in chat_data_list:
                events = map_chat_to_events(
                    cd, self.student_id, self.course_id, base_sequence=seq
                )
                all_events.extend(events)
                seq += len(events)

        if jump_data_list:
            for jd in jump_data_list:
                events = map_jump_to_events(
                    jd, self.student_id, self.course_id, base_sequence=seq
                )
                all_events.extend(events)
                seq += len(events)

        return all_events
