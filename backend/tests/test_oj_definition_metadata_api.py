"""PR-09 端到端：实验定义的难度 / 标签（`difficulty` / `tags`）经 API 落库与回显。

**为什么单开一个文件而不加进 `test_experiments.py`**：那个文件正被另一条线
（学生工作台 F3-B）改着（未提交 +90 行），往里追加会让「谁的 hunk」更难切。
本文件只覆盖 PR-09 新增的两列，边界清晰。

覆盖：
- create 缺省 → 落 `medium` + 空标签；
- create 显式给值 → 归一化后落库（含大小写 / 空白 / 去重）；
- create 非法值 → **422，不落库**（域层抛错不兜底的策略在 API 层的体现）；
- update 不传该字段 → **不动原值**（PATCH 语义，别把没传当默认值覆盖）；
- update 传空标签 → **清空**（与"不传"必须可区分）；
- 响应体形态 → `difficulty` 是字符串、`tags` 是数组（前端不用判 null）。

迁移本身的执行由 `tests/test_alembic_migration.py` + `conftest.py::test_engine`
（跑 `alembic upgrade head`）保证 —— 本文件通过即等于这两列真的建出来了。
"""
from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session as SqlSession, select

from app.core.security import create_access_token
from app.models.access_control_model import CourseCapability
from app.models.course_model import Course, CourseStatus
from app.models.experiment_model import ExperimentDefinition
from app.models.user_model import User
from app.services.course_access_service import establish_course_access_baseline


EXPERIMENTS = "/api/v1/experiments"


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "username": user.username,
        "role": user.role.value,
        "school_id": user.school_id or "test-school",
    })


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _course_with_capabilities(session: SqlSession, teacher_id: int) -> Course:
    course = Course(
        fanya_course_id=f"pr09-{uuid.uuid4().hex[:8]}",
        fanya_course_name="PR-09 Course",
        title="PR-09 Course",
        teacher_id=teacher_id,
        status=CourseStatus.PUBLISHED,
    )
    session.add(course)
    session.commit()
    session.refresh(course)

    # 注意：`establish_course_access_baseline` **已经**建了 CourseCapability
    # （`course_access_service.py:201-205`）。这里必须 upsert 而不是再 add 一行 ——
    # 否则撞 `UNIQUE constraint failed: course_capabilities.course_id`。
    establish_course_access_baseline(session, course.id, teacher_id)
    session.commit()

    capability = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course.id)
    ).one()
    capability.experiment = True
    capability.coding_sandbox = True
    session.add(capability)
    session.commit()
    return course


def _create_definition(client, token: str, course_id: int, **overrides) -> dict:
    payload = {
        "title": "二分查找实验",
        "description": "实现二分查找",
        "language_whitelist": ["python3"],
        "knowledge_node_ids": [],
        "max_attempts": 3,
        "cooldown_minutes": 0,
    }
    payload.update(overrides)
    resp = client.post(
        f"{EXPERIMENTS}/course/{course_id}/definitions",
        json=payload,
        headers=_auth(token),
    )
    return resp


@pytest.fixture
def pr09_course(session, teacher_user):
    return _course_with_capabilities(session, teacher_user.id)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


class TestCreateDefinitionMetadata:
    def test_defaults_to_medium_and_empty_tags(self, client, session, teacher_user, pr09_course):
        """不传两个字段 → medium + []（`None` 是"没填"不是"填错"）。"""
        resp = _create_definition(client, _token(teacher_user), pr09_course.id)
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]

        assert data["difficulty"] == "medium"
        assert data["tags"] == []

        row = session.exec(
            select(ExperimentDefinition).where(
                ExperimentDefinition.experiment_id == data["experiment_id"]
            )
        ).one()
        assert row.difficulty == "medium"
        assert list(row.tags or []) == []

    @pytest.mark.parametrize("given,expected", [
        ("easy", "easy"),
        ("HARD", "hard"),
        ("  Medium  ", "medium"),
    ])
    def test_difficulty_normalized_before_persist(
        self, client, session, teacher_user, pr09_course, given, expected
    ):
        """大小写与首尾空白在**落库前**就被吃掉 —— 库里不应出现 `HARD`。"""
        resp = _create_definition(
            client, _token(teacher_user), pr09_course.id, difficulty=given
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["difficulty"] == expected

        row = session.exec(
            select(ExperimentDefinition).where(
                ExperimentDefinition.experiment_id == data["experiment_id"]
            )
        ).one()
        assert row.difficulty == expected

    def test_tags_normalized_and_deduplicated(self, client, session, teacher_user, pr09_course):
        """去空白 / 丢空串 / 大小写不敏感去重且保序（留首次拼写）。"""
        resp = _create_definition(
            client, _token(teacher_user), pr09_course.id,
            tags=["  二分  ", "", "DP", "dp", "   "],
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["tags"] == ["二分", "DP"]

    def test_invalid_difficulty_rejected_and_not_persisted(
        self, client, session, teacher_user, pr09_course
    ):
        """非法难度 → 4xx，且**不产生行**。

        域层刻意不兜底（`normalize_difficulty` 抛 ValueError），
        这里确认服务层把它翻成了客户端错误而不是 500 或静默存 medium。
        """
        before = len(session.exec(select(ExperimentDefinition)).all())
        resp = _create_definition(
            client, _token(teacher_user), pr09_course.id, difficulty="impossible"
        )
        session.expire_all()
        after = len(session.exec(select(ExperimentDefinition)).all())

        assert resp.status_code in (400, 422), resp.text
        assert after == before, "非法难度竟然落库了"
        assert "impossible" not in resp.text or "难度" in resp.text

    def test_numeric_difficulty_rejected(self, client, teacher_user, pr09_course):
        """1–5 整数是 `knowledge.py` 那套旧口径，本域**不接受**。"""
        resp = _create_definition(
            client, _token(teacher_user), pr09_course.id, difficulty=3
        )
        assert resp.status_code in (400, 422), resp.text

    def test_too_many_tags_rejected(self, client, teacher_user, pr09_course):
        resp = _create_definition(
            client, _token(teacher_user), pr09_course.id,
            tags=[f"tag{i}" for i in range(25)],
        )
        assert resp.status_code in (400, 422), resp.text


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdateDefinitionMetadata:
    def _make(self, client, token: str, course_id: int, **overrides) -> dict:
        resp = _create_definition(client, token, course_id, **overrides)
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]

    def test_omitted_fields_are_untouched(self, client, session, teacher_user, pr09_course):
        """**PATCH 语义**：不传 `difficulty` / `tags` 就不许动它们。

        这是最容易写错的地方 —— 若把 `None` 当成"设成默认值"，
        教师改个标题就会把难度重置回 medium、标签被清空。
        """
        token = _token(teacher_user)
        created = self._make(client, token, pr09_course.id, difficulty="hard", tags=["图论"])

        resp = client.put(
            f"{EXPERIMENTS}/course/{pr09_course.id}/definitions/{created['experiment_id']}",
            json={"title": "改个标题"},
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]

        assert data["title"] == "改个标题"
        assert data["difficulty"] == "hard", "改标题把难度重置了"
        assert data["tags"] == ["图论"], "改标题把标签清空了"

    def test_difficulty_updated(self, client, teacher_user, pr09_course):
        token = _token(teacher_user)
        created = self._make(client, token, pr09_course.id, difficulty="easy")

        resp = client.put(
            f"{EXPERIMENTS}/course/{pr09_course.id}/definitions/{created['experiment_id']}",
            json={"difficulty": "HARD"},
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["difficulty"] == "hard"

    def test_empty_tags_clears_them(self, client, teacher_user, pr09_course):
        """`[]` 必须与"不传"可区分：前者是清空，后者是别动。"""
        token = _token(teacher_user)
        created = self._make(client, token, pr09_course.id, tags=["a", "b"])

        resp = client.put(
            f"{EXPERIMENTS}/course/{pr09_course.id}/definitions/{created['experiment_id']}",
            json={"tags": []},
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["tags"] == []

    def test_invalid_difficulty_on_update_rejected(
        self, client, session, teacher_user, pr09_course
    ):
        token = _token(teacher_user)
        created = self._make(client, token, pr09_course.id, difficulty="hard")

        resp = client.put(
            f"{EXPERIMENTS}/course/{pr09_course.id}/definitions/{created['experiment_id']}",
            json={"difficulty": "nope"},
            headers=_auth(token),
        )
        assert resp.status_code in (400, 422), resp.text

        session.expire_all()
        row = session.exec(
            select(ExperimentDefinition).where(
                ExperimentDefinition.experiment_id == created["experiment_id"]
            )
        ).one()
        assert row.difficulty == "hard", "非法更新把原值改坏了"


# ---------------------------------------------------------------------------
# 响应体形态（前端契约）
# ---------------------------------------------------------------------------


class TestDefinitionMetadataResponseShape:
    def test_list_and_detail_carry_both_fields(self, client, teacher_user, pr09_course):
        """列表与详情都要带，且类型稳定。

        前端题库页按难度分组、按标签筛，所以 `difficulty` 必须是**字符串**
        （不是 null）、`tags` 必须是**数组**（不是 null / 不是 JSON 字符串）。
        """
        token = _token(teacher_user)
        created = _create_definition(
            client, token, pr09_course.id, difficulty="easy", tags=["排序"]
        ).json()["data"]

        detail = client.get(
            f"{EXPERIMENTS}/course/{pr09_course.id}/definitions/{created['experiment_id']}",
            headers=_auth(token),
        )
        assert detail.status_code == 200, detail.text
        d = detail.json()["data"]
        assert isinstance(d["difficulty"], str) and d["difficulty"]
        assert isinstance(d["tags"], list)

        listing = client.get(
            f"{EXPERIMENTS}/course/{pr09_course.id}/definitions",
            headers=_auth(token),
        )
        assert listing.status_code == 200, listing.text
        items = listing.json()["data"]["items"]
        target = next(
            item for item in items if item["experiment_id"] == created["experiment_id"]
        )
        assert target["difficulty"] == "easy"
        assert target["tags"] == ["排序"]

    def test_historic_null_tags_serialize_as_empty_list(
        self, client, session, teacher_user, pr09_course
    ):
        """迁移前插入的历史行 `tags` 是 SQL NULL → 响应体须给 `[]`。

        直接改 ORM 行模拟历史数据（真实场景是 `20260911_1600` 迁移之前的行），
        确认序列化层的 `or []` 兜底真的生效 —— 否则前端会拿到 `null`。
        """
        token = _token(teacher_user)
        created = _create_definition(client, token, pr09_course.id).json()["data"]

        row = session.exec(
            select(ExperimentDefinition).where(
                ExperimentDefinition.experiment_id == created["experiment_id"]
            )
        ).one()
        row.tags = None
        session.add(row)
        session.commit()

        resp = client.get(
            f"{EXPERIMENTS}/course/{pr09_course.id}/definitions/{created['experiment_id']}",
            headers=_auth(token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["tags"] == []
