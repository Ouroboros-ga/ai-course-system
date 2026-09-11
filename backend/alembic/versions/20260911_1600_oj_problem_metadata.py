"""OJ PR-09：experiment_definitions 增加 difficulty / tags（题目元数据）。

Revision ID: oj20260911v2
Revises: oj20260911v1
Create Date: 2026-09-11
Batch: oj_problem_metadata_v1

背景
----
题库页需要按难度筛、按标签检索，而 ``ExperimentDefinition`` 既无 ``difficulty``
也无 ``tags``（``docs/architecture/oj-current-state.md`` 记为真缺口）。
``visibility`` / ``origin`` / ``owner_student_id`` / ``expires_at`` 早已存在，
自练题的挂点是留好的，缺的只是这两个描述性字段。

取值口径
--------
``difficulty`` 用 **三档字符串**（``easy`` / ``medium`` / ``hard``），与
``QuestionDifficulty``（``models/question_bank_model.py``）取值集一致 ——
理由与取舍写在 ``app/domain/oj/problems/metadata.py`` 的模块 docstring 里，
**不在这里重复**。服务端校验走该域模块的 ``normalize_difficulty``。

为什么用 ``String(16)`` 而不是 PG 原生 enum
------------------------------------------
``experiment_runs.outcome`` 那个原生 enum 已经在 PR-01 制造过一次静默回填坑
（见 ``20260911_1400_oj_run_semantics.py`` 的说明）。难度取值将来若要扩档
（比如加 ``challenge``），原生 enum 需要 ``ALTER TYPE`` 且不能在事务里回滚；
字符串列 + 域层校验的组合对本题这种「描述性、非判定性」字段更划算。
PR-01 给 ``run_state`` / ``run_type`` 选 ``String(32)`` 也是同一取向。

回填说明
--------
``difficulty`` 带 ``server_default='medium'``，**全部历史行一次性落到 medium**。
这是**保守默认而非推导值**：仓库里没有任何可用来推断既有题目难度的信号
（没有 pass 率统计、没有用时分布、没有人工标注）。与其按标题长度之类的
代理指标猜一个"看起来更聪明"的值，不如统一 medium 并让教师后续修正 ——
猜错会污染题库筛选，且难以回溯哪些是猜的。

``tags`` 回填为空数组：``sa.JSON()`` 列的 ``NULL`` 与 ``[]`` 在 Python 侧
都能被 ``normalize_tags`` 吃下（``None`` → ``[]``），但显式写成 ``[]``
可以让前端少一次 ``null`` 判断。旧的 ``NULL`` 行不会被改写 —— 加列后
新行才走 ``default_factory=list``，历史行的 NULL 由序列化层兜底。

幂等
----
加列 / 建索引均带 ``_has_column`` / ``_has_index`` 守卫。重复执行安全。

回退
----
``downgrade`` 删索引与两列。两列都是**新增的描述性元数据**，没有任何既有
逻辑读它（本 PR 未改任何读写路径的响应体），因此回退无损。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "oj20260911v2"
down_revision = "oj20260911v1"
branch_labels = None
depends_on = None

BATCH_ID = "oj_problem_metadata_v1"
BATCH_NAME = "OJ：experiment_definitions 增加难度与标签（difficulty / tags）"
BATCH_ROLLBACK_NOTES = (
    "Drops experiment_definitions.difficulty and experiment_definitions.tags. "
    "difficulty carried only the conservative server default 'medium' for every "
    "historical row (no signal existed to derive a better value), and tags was "
    "left empty, so the downgrade loses no teacher-authored information."
)

_TABLE = "experiment_definitions"
_INDEX_DIFFICULTY = "ix_experiment_definitions_difficulty"

#: 历史行统一落到的默认难度。**与域层 ``DEFAULT_DIFFICULTY`` 必须一致** ——
#: 迁移文件不 import 应用代码（alembic 版本可能早于/晚于应用版本），
#: 一致性由 ``tests/test_oj_problem_metadata.py`` 的字面量断言守住。
_DEFAULT_DIFFICULTY = "medium"


def _has_column(table: str, column: str) -> bool:
    return column in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _has_index(table: str, index: str) -> bool:
    return index in {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _record_batch(status: str, applied_rows: int = 0) -> None:
    """Upsert the business migration ledger inside the Alembic transaction."""
    bind = op.get_bind()
    if "schema_migration_records" not in set(sa.inspect(bind).get_table_names()):
        return
    existing = bind.execute(
        sa.text("SELECT id FROM schema_migration_records WHERE batch_id = :batch_id"),
        {"batch_id": BATCH_ID},
    ).first()
    values = {
        "batch_id": BATCH_ID,
        "name": BATCH_NAME,
        "status": status,
        "rollback_notes": BATCH_ROLLBACK_NOTES,
        "preflight_ok": True,
        "applied_rows": applied_rows,
    }
    if existing is None:
        bind.execute(
            sa.text(
                "INSERT INTO schema_migration_records "
                "(batch_id, name, applied_at, status, rollback_notes, "
                "preflight_ok, applied_rows, created_at) "
                "VALUES (:batch_id, :name, CURRENT_TIMESTAMP, :status, "
                ":rollback_notes, :preflight_ok, :applied_rows, CURRENT_TIMESTAMP)"
            ),
            values,
        )
        return
    bind.execute(
        sa.text(
            "UPDATE schema_migration_records "
            "SET name = :name, applied_at = CURRENT_TIMESTAMP, status = :status, "
            "rollback_notes = :rollback_notes, preflight_ok = :preflight_ok, "
            "applied_rows = :applied_rows "
            "WHERE batch_id = :batch_id"
        ),
        values,
    )


def upgrade() -> None:
    # 先记账「加列前已有多少行」，这才是 server_default 真正影响的规模。
    # 放在 add_column 之后数 difficulty='medium' 会把**加列后新插入**的
    # medium 行也算进来，数字随执行时机漂移，失去台账意义。
    pre_existing = 0
    if not _has_column(_TABLE, "difficulty"):
        pre_existing = int(
            op.get_bind().execute(sa.text(f"SELECT COUNT(*) FROM {_TABLE}")).scalar() or 0
        )

    if not _has_column(_TABLE, "difficulty"):
        op.add_column(
            _TABLE,
            sa.Column(
                "difficulty",
                sa.String(length=16),
                nullable=False,
                server_default=_DEFAULT_DIFFICULTY,
            ),
        )
    if not _has_column(_TABLE, "tags"):
        op.add_column(
            _TABLE,
            sa.Column("tags", sa.JSON(), nullable=True),
        )

    if not _has_index(_TABLE, _INDEX_DIFFICULTY):
        op.create_index(
            op.f(_INDEX_DIFFICULTY), _TABLE, ["difficulty"], unique=False
        )

    _record_batch("applied", applied_rows=pre_existing)


def downgrade() -> None:
    """删索引与两列。

    守卫而非 ``try/except pass``：与 PR-01 迁移同一取向 —— 盲吞异常会掩盖
    真正的方言/权限错误，而守卫能明确表达「本来就没有就跳过」。
    SQLite 不支持原生 DROP COLUMN，走 batch 模式；PG 同语法兼容。
    """
    if _has_index(_TABLE, _INDEX_DIFFICULTY):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_index(_INDEX_DIFFICULTY)
    for column in ("tags", "difficulty"):
        if _has_column(_TABLE, column):
            with op.batch_alter_table(_TABLE) as batch:
                batch.drop_column(column)
    _record_batch("rolled_back")
