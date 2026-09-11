"""OJ 题目侧服务：实验定义（ExperimentDefinitionService）与版本（ExperimentVersionService）。

从 `experiment_service.py` 拆出（OJ 整改 PR-03，ADR-0001 决定 ①②）：
`experiment_service.py` 曾以 2300+ 行承载全部 OJ 语义，按 bounded context
拆分后每个文件只讲一个故事 —— 本文件只讲「题目与版本」。

拆分约定（沿用 PR-02 的教训，**不留 shim**）：
- 单例 `definition_service` / `version_service` 随类迁到本文件，
  其余调用方**直接从本模块导入**；
- 共享门卫 `_require_formal_experiment_capabilities` 一并迁入
  （attempt/run 拆分后同样从这里导入，避免门卫再搬一次家）；
- `_validated_difficulty` / `_validated_tags` 是定义服务的专属适配
  （域层 `normalize_difficulty`/`normalize_tags` → HTTP 422），随类迁移。
"""
from __future__ import annotations

from __future__ import annotations
from typing import (
    Any,
    Optional,
)
from sqlalchemy import (
    case,
)
from sqlmodel import Session, func, select
from app.core.exceptions import (
    reject_capability_disabled,
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.core.time_utils import (
    utcnow_aware,
)
from app.models.access_control_model import (
    CourseCapability,
)
from app.models.experiment_model import (
    ExperimentDefinition,
    ExperimentPublishStatus,
    ExperimentTestCase,
    ExperimentVersion,
)
from app.domain.oj.judging.providers.judge0 import (
    ALLOWED_LANGUAGES,
    SandboxResourceLimits,
    SubmissionStatus,
    sandbox_client,
)
from app.domain.oj.problems.metadata import normalize_difficulty, normalize_tags



def _require_formal_experiment_capabilities(session: Session, *, course_id: int) -> None:
    """Keep publication, attempts, previews, and runs behind both switches."""
    capability = session.exec(
        select(CourseCapability).where(CourseCapability.course_id == course_id)
    ).first()
    if capability is None or not capability.experiment or not capability.coding_sandbox:
        reject_capability_disabled("The course has not enabled formal code experiments.")

def _validated_difficulty(value: Optional[str]) -> str:
    """规范化难度；非法取值转成 422 而不是 500。

    `normalize_difficulty` 对非法值**抛错不兜底**是刻意的（见其 docstring）：
    教师显式填错必须让他知道。这里只负责把异常翻译成 API 层的校验失败。
    """
    try:
        return normalize_difficulty(value)
    except ValueError as exc:
        reject_validation_failed(str(exc))
        raise  # 不可达：reject_validation_failed 必定抛 HTTPException。仅为类型收敛。

def _validated_tags(values: Optional[list[str]]) -> list[str]:
    """规范化标签；空 `None` → 空列表（"没填"），非法则 422。

    注意 `None` 与 `[]` 在这里**同义**（都得到 `[]`）—— 需要区分二者的是
    `update_definition` 的调用点，那里已在 `if tags is not None` 处判过。
    """
    try:
        return normalize_tags(values)
    except ValueError as exc:
        reject_validation_failed(str(exc))
        raise

class ExperimentDefinitionService:
    """教师管理课程实验定义"""

    def create_definition(
        self,
        session: Session,
        *,
        course_id: int,
        title: str,
        description: str = "",
        language_whitelist: Optional[list[str]] = None,
        knowledge_node_ids: Optional[list[int]] = None,
        difficulty: Optional[str] = None,
        tags: Optional[list[str]] = None,
        max_attempts: int = 3,
        cooldown_minutes: int = 30,
        created_by: int,
    ) -> ExperimentDefinition:
        # 校验语言白名单
        whitelist = list(language_whitelist or [])
        invalid = [lang for lang in whitelist if lang not in ALLOWED_LANGUAGES]
        if invalid:
            reject_validation_failed(f"不支持的语言: {invalid}")

        definition = ExperimentDefinition(
            course_id=course_id,
            title=title,
            description=description,
            language_whitelist=whitelist,
            knowledge_node_ids=list(knowledge_node_ids or []),
            difficulty=_validated_difficulty(difficulty),
            tags=_validated_tags(tags),
            max_attempts=max_attempts,
            cooldown_minutes=cooldown_minutes,
            publish_status=ExperimentPublishStatus.DRAFT,
            created_by=created_by,
        )
        session.add(definition)
        session.flush()
        return definition

    def get_definition(
        self,
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
    ) -> ExperimentDefinition:
        definition = session.exec(
            select(ExperimentDefinition).where(
                ExperimentDefinition.experiment_id == experiment_id,
                ExperimentDefinition.course_id == course_id,
            )
        ).first()
        if definition is None:
            reject_resource_not_found(f"实验 {experiment_id} 不存在")
        return definition

    def list_definitions(
        self,
        session: Session,
        *,
        course_id: int,
        publish_status: Optional[ExperimentPublishStatus] = None,
    ) -> list[ExperimentDefinition]:
        stmt = select(ExperimentDefinition).where(
            ExperimentDefinition.course_id == course_id,
            ExperimentDefinition.visibility == "course_catalog",
        )
        if publish_status is not None:
            stmt = stmt.where(ExperimentDefinition.publish_status == publish_status)
        stmt = stmt.order_by(ExperimentDefinition.created_at.desc())
        return list(session.exec(stmt).all())

    def update_definition(
        self,
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        language_whitelist: Optional[list[str]] = None,
        difficulty: Optional[str] = None,
        tags: Optional[list[str]] = None,
        max_attempts: Optional[int] = None,
        cooldown_minutes: Optional[int] = None,
    ) -> ExperimentDefinition:
        definition = self.get_definition(session, course_id=course_id, experiment_id=experiment_id)
        if language_whitelist is not None:
            invalid = [lang for lang in language_whitelist if lang not in ALLOWED_LANGUAGES]
            if invalid:
                reject_validation_failed(f"不支持的语言: {invalid}")
            definition.language_whitelist = list(language_whitelist)
        if title is not None:
            definition.title = title
        if description is not None:
            definition.description = description
        if difficulty is not None:
            definition.difficulty = _validated_difficulty(difficulty)
        if tags is not None:
            definition.tags = _validated_tags(tags)
        if max_attempts is not None:
            definition.max_attempts = max_attempts
        if cooldown_minutes is not None:
            definition.cooldown_minutes = cooldown_minutes
        definition.updated_at = utcnow_aware()
        session.add(definition)
        session.flush()
        return definition

    def publish_definition(
        self,
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
    ) -> ExperimentDefinition:
        definition = self.get_definition(session, course_id=course_id, experiment_id=experiment_id)
        ExperimentPublishValidator().validate_existing(session, definition=definition)
        if not definition.default_version_id:
            reject_state_conflict("实验缺少激活版本，无法发布")
        definition.publish_status = ExperimentPublishStatus.PUBLISHED
        definition.updated_at = utcnow_aware()
        session.add(definition)
        session.flush()
        # 延迟导入：ExperimentLabProjectionService 同时被 attempt/run 终结流程使用
        # （留在 experiment_service），模块级导入会成环；PR-04 拆 attempt/run 时收口。
        from app.services.experiment_service import ExperimentLabProjectionService

        ExperimentLabProjectionService().ensure_projection(
            session,
            course_id=definition.course_id,
            experiment_id=definition.experiment_id,
        )
        return definition

    def archive_definition(
        self,
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
    ) -> ExperimentDefinition:
        definition = self.get_definition(session, course_id=course_id, experiment_id=experiment_id)
        definition.publish_status = ExperimentPublishStatus.ARCHIVED
        definition.archived_at = utcnow_aware()
        definition.updated_at = utcnow_aware()
        session.add(definition)
        session.flush()
        return definition

class ExperimentVersionService:
    """实验版本与测试用例管理"""

    def create_version(
        self,
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
        label: str = "",
        cpu_time_limit: int = 5,
        memory_limit: int = 128_000,
        wall_time_limit: int = 10,
        max_processes: int = 30,
        max_file_size: int = 1024,
        passing_score: float = 1.0,
        writes_formal_evidence: bool = True,
        starter_code: Optional[dict] = None,
        created_by: int,
        test_cases: Optional[list[dict]] = None,
        activate: bool = True,
    ) -> ExperimentVersion:
        if passing_score != 1.0:
            reject_validation_failed("Formal programming experiments require passing_score=1.0")
        # 起始代码只做形状消毒：键值转 str、单语言截断 20k（对齐单次提交上限），
        # 此处不编译不执行；是否允许的语言由 definition 白名单在提交时校验。
        clean_starter: dict[str, str] = {}
        if isinstance(starter_code, dict):
            for lang, code in starter_code.items():
                if not isinstance(lang, str) or not lang.strip():
                    continue
                clean_starter[lang.strip()] = str(code or "")[:20_000]
        if not test_cases:
            reject_validation_failed("An experiment version requires at least one test case")
        total_weight = sum(float(case.get("weight", 1.0)) for case in test_cases)
        if abs(total_weight - 1.0) > 1e-9:
            reject_validation_failed("Experiment test case weights must total 1.0")
        # 验证实验存在
        definition_service.get_definition(
            session, course_id=course_id, experiment_id=experiment_id,
        )

        # 计算版本号
        max_version = session.exec(
            select(func.max(ExperimentVersion.version_number)).where(
                ExperimentVersion.experiment_id == experiment_id,
            )
        ).one() or 0
        version_number = int(max_version) + 1

        version = ExperimentVersion(
            experiment_id=experiment_id,
            course_id=course_id,
            version_number=version_number,
            label=label or f"v{version_number}",
            cpu_time_limit=cpu_time_limit,
            memory_limit=memory_limit,
            wall_time_limit=wall_time_limit,
            max_processes=max_processes,
            max_file_size=max_file_size,
            enable_network=False,  # 始终关闭
            passing_score=passing_score,
            writes_formal_evidence=writes_formal_evidence,
            starter_code=clean_starter,
            is_active=False,
            created_by=created_by,
        )
        session.add(version)
        session.flush()

        # 写入测试用例
        for case_data in (test_cases or []):
            case = ExperimentTestCase(
                version_id=version.version_id,
                course_id=course_id,
                case_name=case_data.get("case_name", ""),
                stdin=case_data.get("stdin", ""),
                expected_stdout=case_data.get("expected_stdout", ""),
                is_hidden=bool(case_data.get("is_hidden", False)),
                weight=float(case_data.get("weight", 1.0)),
                time_limit_override=case_data.get("time_limit_override"),
            )
            session.add(case)

        session.flush()
        return version

    def get_version(
        self,
        session: Session,
        *,
        course_id: int,
        version_id: str,
    ) -> ExperimentVersion:
        version = session.exec(
            select(ExperimentVersion).where(
                ExperimentVersion.version_id == version_id,
                ExperimentVersion.course_id == course_id,
            )
        ).first()
        if version is None:
            reject_resource_not_found(f"实验版本 {version_id} 不存在")
        return version

    def list_versions(
        self,
        session: Session,
        *,
        course_id: int,
        experiment_id: str,
    ) -> list[ExperimentVersion]:
        return list(session.exec(
            select(ExperimentVersion).where(
                ExperimentVersion.experiment_id == experiment_id,
                ExperimentVersion.course_id == course_id,
            ).order_by(ExperimentVersion.version_number.desc())
        ).all())

    def list_test_cases(
        self,
        session: Session,
        *,
        course_id: int,
        version_id: str,
        include_hidden: bool = True,
    ) -> list[ExperimentTestCase]:
        stmt = select(ExperimentTestCase).where(
            ExperimentTestCase.version_id == version_id,
            ExperimentTestCase.course_id == course_id,
        )
        if not include_hidden:
            stmt = stmt.where(ExperimentTestCase.is_hidden == False)  # noqa: E712
        return list(session.exec(stmt).all())

    def activate_version(
        self,
        session: Session,
        *,
        course_id: int,
        version_id: str,
    ) -> ExperimentVersion:
        return self._activate_version(session, course_id=course_id, version_id=version_id)

    def _activate_version(
        self,
        session: Session,
        *,
        course_id: int,
        version_id: str,
    ) -> ExperimentVersion:
        version = self.get_version(session, course_id=course_id, version_id=version_id)
        if not version.is_locked or version.reference_preview_verified_at is None:
            reject_state_conflict("Only a locked version with a verified reference preview may become active")

        # 失活同实验其他版本
        other_versions = session.exec(
            select(ExperimentVersion).where(
                ExperimentVersion.experiment_id == version.experiment_id,
                ExperimentVersion.course_id == course_id,
                ExperimentVersion.is_active == True,  # noqa: E712
                ExperimentVersion.version_id != version_id,
            )
        ).all()
        for other in other_versions:
            other.is_active = False
            session.add(other)

        version.is_active = True
        session.add(version)

        # 更新实验定义的 default_version_id
        definition = session.exec(
            select(ExperimentDefinition).where(
                ExperimentDefinition.experiment_id == version.experiment_id,
                ExperimentDefinition.course_id == course_id,
            )
        ).first()
        if definition is not None:
            definition.default_version_id = version.version_id
            definition.updated_at = utcnow_aware()
            session.add(definition)

        session.flush()
        return version

    def lock_version(
        self,
        session: Session,
        *,
        course_id: int,
        version_id: str,
        locked: bool = True,
    ) -> ExperimentVersion:
        version = self.get_version(session, course_id=course_id, version_id=version_id)
        if locked and version.reference_preview_verified_at is None:
            reject_state_conflict("Reference solution preview has not verified all test cases")
        version.is_locked = locked
        session.add(version)
        session.flush()
        if locked:
            # Locking is the deliberate handoff from the editable test set to
            # the version students may receive.  Creation itself never changes
            # a published experiment's default version.
            return self._activate_version(session, course_id=course_id, version_id=version_id)
        return version

    def preview_reference_solution(
        self,
        session: Session,
        *,
        course_id: int,
        version_id: str,
        language: str,
        source_code: str,
    ) -> dict[str, Any]:
        """Verify a transient teacher reference solution against every case.

        The source stays in request memory only.  No run/artifact/agent record
        is created because those stores are student-product data and must not
        receive teacher answers or hidden inputs.
        """
        _require_formal_experiment_capabilities(session, course_id=course_id)
        version = self.get_version(session, course_id=course_id, version_id=version_id)
        definition = definition_service.get_definition(
            session, course_id=course_id, experiment_id=version.experiment_id,
        )
        if language not in definition.language_whitelist:
            reject_validation_failed("参考解语言不在实验白名单中")
        if not sandbox_client.health_check():
            reject_state_conflict("Judge0 健康检查未通过，无法预览参考解")
        cases = self.list_test_cases(session, course_id=course_id, version_id=version_id)
        if not cases:
            reject_validation_failed("参考解预览需要至少一个测试用例")
        limits = SandboxResourceLimits(
            cpu_time_limit=version.cpu_time_limit,
            memory_limit=version.memory_limit,
            wall_time_limit=version.wall_time_limit,
            max_processes=version.max_processes,
            max_file_size=version.max_file_size,
            enable_network=False,
        )
        passed_count = 0
        for case in cases:
            result = sandbox_client.submit_code(
                source_code=source_code,
                language=language,
                stdin=case.stdin,
                expected_output=case.expected_stdout,
                limits=limits,
            )
            if result.status == SubmissionStatus.ACCEPTED:
                passed_count += 1
        accepted = passed_count == len(cases)
        if accepted:
            version.reference_preview_verified_at = utcnow_aware()
            session.add(version)
            session.flush()
        return {
            "version_id": version.version_id,
            "accepted": accepted,
            "passed_count": passed_count,
            "total_count": len(cases),
        }

definition_service = ExperimentDefinitionService()

version_service = ExperimentVersionService()


class ExperimentPublishValidator:
    """Single server authority for all formal experiment publish preconditions."""

    def validate(
        self, session: Session, *, course_id: int, experiment_id: str,
    ) -> ExperimentDefinition:
        definition = definition_service.get_definition(
            session, course_id=course_id, experiment_id=experiment_id,
        )
        self.validate_existing(session, definition=definition)
        return definition

    def validate_existing(self, session: Session, *, definition: ExperimentDefinition) -> None:
        _require_formal_experiment_capabilities(session, course_id=definition.course_id)
        if not definition.language_whitelist or any(lang not in ALLOWED_LANGUAGES for lang in definition.language_whitelist):
            reject_validation_failed("实验语言白名单为空或包含不支持的语言")
        if not definition.default_version_id:
            reject_state_conflict("实验缺少活动默认版本，无法发布")
        version = version_service.get_version(
            session, course_id=definition.course_id, version_id=definition.default_version_id,
        )
        if version.experiment_id != definition.experiment_id or not version.is_active:
            reject_state_conflict("默认版本不是该实验的活动版本")
        if not version.is_locked:
            reject_state_conflict("活动默认版本必须先锁定")
        if version.reference_preview_verified_at is None:
            reject_state_conflict("参考解预览尚未全量通过")
        if version.passing_score != 1.0:
            reject_validation_failed("正式实验必须使用 ACM/ICPC 通过阈值 1.0")
        if not (1 <= version.cpu_time_limit <= 30 and 16_000 <= version.memory_limit <= 512_000 and 1 <= version.wall_time_limit <= 60):
            reject_validation_failed("实验资源限制超出安全边界")
        cases = version_service.list_test_cases(
            session, course_id=definition.course_id, version_id=version.version_id,
        )
        if not cases:
            reject_validation_failed("实验至少需要一个测试用例")
        if abs(sum(case.weight for case in cases) - 1.0) > 1e-9:
            reject_validation_failed("测试用例权重总和必须为 1")
        if not sandbox_client.health_check():
            reject_state_conflict("Judge0 健康检查未通过，无法发布")
