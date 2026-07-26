"""阶段3 统一任务中心与教师课程建设工作流服务。

承载路线图 §6 七步建设状态：
    materials → structure → scripts → page_mappings → media → validate → release

核心约束：
- 教师锁定的映射/讲稿不被 AI 重跑覆盖（locked_by 非空时跳过）
- 发布前质量门禁可阻断；error/blocker 级别问题阻断发布
- 发布后 release 不可变；回滚产生新激活版本而非破坏历史
- 所有操作按 course_id 严格隔离
"""
from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from app.core.exceptions import (
    reject,
    reject_course_access_denied,
    reject_resource_not_found,
    reject_state_conflict,
    reject_validation_failed,
)
from app.core.time_utils import utcnow_naive
from app.models.course_build_model import (
    BuildStepName,
    BuildStepStatus,
    CourseBuildDraft,
    CourseBuildStep,
    CourseQualityGateRun,
    CourseRelease,
    CourseReleaseArtifact,
    GateSeverity,
    MaterialStatus,
    ReleaseStatus,
    SourceMaterial,
    SourceMaterialVersion,
)


# ---------------------------------------------------------------------------
# 步骤顺序与状态机
# ---------------------------------------------------------------------------


# 七步顺序
_STEP_ORDER: list[BuildStepName] = [
    BuildStepName.MATERIALS,
    BuildStepName.STRUCTURE,
    BuildStepName.SCRIPTS,
    BuildStepName.PAGE_MAPPINGS,
    BuildStepName.MEDIA,
    BuildStepName.VALIDATE,
    BuildStepName.RELEASE,
]


def _step_index(step: BuildStepName) -> int:
    return _STEP_ORDER.index(step)


def _next_step(step: BuildStepName) -> Optional[BuildStepName]:
    idx = _step_index(step)
    if idx + 1 < len(_STEP_ORDER):
        return _STEP_ORDER[idx + 1]
    return None


# 步骤状态转移：仅允许从 NOT_STARTED/FAILED → IN_PROGRESS；IN_PROGRESS → READY_FOR_REVIEW/APPROVED/FAILED
_STEP_TRANSITIONS: dict[BuildStepStatus, set[BuildStepStatus]] = {
    BuildStepStatus.NOT_STARTED: {BuildStepStatus.IN_PROGRESS, BuildStepStatus.BLOCKED},
    BuildStepStatus.IN_PROGRESS: {
        BuildStepStatus.READY_FOR_REVIEW,
        BuildStepStatus.APPROVED,
        BuildStepStatus.FAILED,
        BuildStepStatus.LOCKED,
    },
    BuildStepStatus.BLOCKED: {BuildStepStatus.IN_PROGRESS, BuildStepStatus.NOT_STARTED},
    BuildStepStatus.READY_FOR_REVIEW: {
        BuildStepStatus.APPROVED,
        BuildStepStatus.FAILED,
        BuildStepStatus.LOCKED,
        BuildStepStatus.IN_PROGRESS,  # 重新跑
    },
    BuildStepStatus.APPROVED: {BuildStepStatus.LOCKED, BuildStepStatus.IN_PROGRESS},  # approved 后可锁定或重跑
    BuildStepStatus.FAILED: {BuildStepStatus.IN_PROGRESS},
    BuildStepStatus.LOCKED: {BuildStepStatus.APPROVED, BuildStepStatus.IN_PROGRESS},  # 解锁或重跑
}


def _assert_step_transition(current: BuildStepStatus, target: BuildStepStatus) -> None:
    if target not in _STEP_TRANSITIONS.get(current, set()):
        reject_state_conflict(
            f"建设步骤状态 {current.value} 不能转移到 {target.value}",
            details={"current_status": current.value, "target_status": target.value},
        )


# ---------------------------------------------------------------------------
# 课程建设草稿与步骤
# ---------------------------------------------------------------------------


class CourseBuildService:
    """课程建设服务

    - get_or_create_draft: 每个课程有一个活跃草稿
    - get_build_view: 聚合七步状态 + 质量门禁 + 发布历史
    - update_step: 更新单步状态与产物
    - lock_step / unlock_step: 教师锁定/解锁，AI 重跑不可覆盖 locked 步骤
    """

    def get_or_create_draft(
        self,
        session: Session,
        *,
        course_id: int,
        actor_user_id: int,
    ) -> CourseBuildDraft:
        draft = session.exec(
            select(CourseBuildDraft).where(CourseBuildDraft.course_id == course_id)
        ).first()
        if draft is None:
            draft = CourseBuildDraft(
                course_id=course_id,
                current_step=BuildStepName.MATERIALS,
                overall_status="not_started",
                created_by=actor_user_id,
            )
            session.add(draft)
            session.flush()
            # 初始化七步
            for step_name in _STEP_ORDER:
                step = CourseBuildStep(
                    course_id=course_id,
                    draft_id=draft.draft_id,
                    step_name=step_name,
                    status=BuildStepStatus.NOT_STARTED,
                )
                session.add(step)
            session.flush()
        return draft

    def get_build_view(
        self,
        session: Session,
        *,
        course_id: int,
    ) -> dict:
        """聚合课程建设 ViewModel：草稿 + 七步状态 + 质量门禁 + 发布历史。"""
        draft = session.exec(
            select(CourseBuildDraft).where(CourseBuildDraft.course_id == course_id)
        ).first()
        if draft is None:
            return {
                "course_id": course_id,
                "draft": None,
                "steps": [],
                "current_step": None,
                "overall_status": "not_started",
                "quality_gate": None,
                "releases": [],
                "active_release": None,
            }

        steps = session.exec(
            select(CourseBuildStep).where(
                CourseBuildStep.course_id == course_id,
                CourseBuildStep.draft_id == draft.draft_id,
            )
        ).all()
        steps_view = [self._serialize_step(s) for s in steps]

        # 最近质量门禁
        latest_gate = session.exec(
            select(CourseQualityGateRun).where(
                CourseQualityGateRun.course_id == course_id,
                CourseQualityGateRun.draft_id == draft.draft_id,
            ).order_by(CourseQualityGateRun.created_at.desc())
        ).first()
        gate_view = self._serialize_gate(latest_gate) if latest_gate else None

        # 发布历史
        releases = session.exec(
            select(CourseRelease).where(
                CourseRelease.course_id == course_id,
            ).order_by(CourseRelease.version.desc())
        ).all()
        releases_view = [self._serialize_release(r) for r in releases]
        active_release = next((r for r in releases_view if r["is_active"]), None)

        return {
            "course_id": course_id,
            "draft": {
                "draft_id": draft.draft_id,
                "current_step": draft.current_step.value,
                "overall_status": draft.overall_status,
                "created_at": draft.created_at.isoformat() if draft.created_at else None,
                "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
            },
            "steps": steps_view,
            "current_step": draft.current_step.value,
            "overall_status": draft.overall_status,
            "quality_gate": gate_view,
            "releases": releases_view,
            "active_release": active_release,
        }

    def get_step(
        self,
        session: Session,
        *,
        course_id: int,
        step_name: BuildStepName,
    ) -> CourseBuildStep:
        step = session.exec(
            select(CourseBuildStep).where(
                CourseBuildStep.course_id == course_id,
                CourseBuildStep.step_name == step_name,
            )
        ).first()
        if step is None:
            reject_resource_not_found(f"建设步骤 {step_name.value} 不存在")
        return step

    def update_step(
        self,
        session: Session,
        *,
        course_id: int,
        step_name: BuildStepName,
        target_status: Optional[BuildStepStatus] = None,
        output_ref: Optional[str] = None,
        output_snapshot: Optional[dict] = None,
        input_summary: Optional[dict] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        actor_user_id: Optional[int] = None,
        bypass_lock: bool = False,
    ) -> CourseBuildStep:
        """更新单步状态与产物。

        - 如果步骤已锁定（locked_by 非空）且 bypass_lock=False，拒绝覆盖
        - 状态转移必须合法
        - 更新 current_step 到当前步骤
        """
        draft = self.get_or_create_draft(
            session, course_id=course_id, actor_user_id=actor_user_id or 0,
        )
        step = self.get_step(session, course_id=course_id, step_name=step_name)

        # 教师锁定保护
        if step.locked_by is not None and not bypass_lock:
            if target_status is not None and target_status != BuildStepStatus.APPROVED:
                reject_state_conflict(
                    f"步骤 {step_name.value} 已被教师锁定，AI 重跑不可覆盖",
                    details={"locked_by": step.locked_by, "step_name": step_name.value},
                )

        if target_status is not None:
            _assert_step_transition(step.status, target_status)
            step.status = target_status

        if output_ref is not None:
            step.output_ref = output_ref
        if output_snapshot is not None:
            step.output_snapshot = output_snapshot
        if input_summary is not None:
            step.input_summary = input_summary
        if error_code is not None:
            step.error_code = error_code
        if error_message is not None:
            step.error_message = error_message

        step.updated_at = utcnow_naive()
        session.add(step)

        # 更新草稿 current_step
        draft.current_step = step_name
        draft.updated_at = utcnow_naive()
        session.add(draft)
        session.flush()
        return step

    def lock_step(
        self,
        session: Session,
        *,
        course_id: int,
        step_name: BuildStepName,
        locked_by: int,
        lock_reason: str = "",
    ) -> CourseBuildStep:
        """教师锁定步骤：AI 重跑不可覆盖。"""
        # 确保草稿与七步已初始化，未初始化时 not_started 状态应返回 409 而非 404
        self.get_or_create_draft(
            session, course_id=course_id, actor_user_id=locked_by,
        )
        step = self.get_step(session, course_id=course_id, step_name=step_name)
        # 锁定前必须已经产出内容（READY_FOR_REVIEW 或 APPROVED）
        if step.status not in (BuildStepStatus.READY_FOR_REVIEW, BuildStepStatus.APPROVED):
            reject_state_conflict(
                f"步骤 {step_name.value} 状态 {step.status.value} 不可锁定",
                details={"current_status": step.status.value},
            )
        step.status = BuildStepStatus.LOCKED
        step.locked_by = locked_by
        step.locked_at = utcnow_naive()
        step.lock_reason = lock_reason
        step.updated_at = utcnow_naive()
        session.add(step)
        session.flush()
        return step

    def unlock_step(
        self,
        session: Session,
        *,
        course_id: int,
        step_name: BuildStepName,
        actor_user_id: int,
    ) -> CourseBuildStep:
        """教师解锁步骤。"""
        step = self.get_step(session, course_id=course_id, step_name=step_name)
        if step.status != BuildStepStatus.LOCKED:
            reject_state_conflict(f"步骤 {step_name.value} 未被锁定")
        step.status = BuildStepStatus.APPROVED
        step.locked_by = None
        step.locked_at = None
        step.lock_reason = ""
        step.updated_at = utcnow_naive()
        session.add(step)
        session.flush()
        return step

    def _serialize_step(self, s: CourseBuildStep) -> dict:
        return {
            "step_id": s.step_id,
            "step_name": s.step_name.value,
            "status": s.status.value,
            "input_summary": s.input_summary,
            "output_ref": s.output_ref,
            "output_snapshot": s.output_snapshot,
            "error_code": s.error_code,
            "error_message": s.error_message,
            "retry_count": s.retry_count,
            "locked_by": s.locked_by,
            "locked_at": s.locked_at.isoformat() if s.locked_at else None,
            "lock_reason": s.lock_reason,
            "quality_gate_passed": s.quality_gate_passed,
            "quality_gate_details": s.quality_gate_details,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }

    def _serialize_gate(self, g: CourseQualityGateRun) -> dict:
        return {
            "gate_run_id": g.gate_run_id,
            "passed": g.passed,
            "blocker_count": g.blocker_count,
            "error_count": g.error_count,
            "warning_count": g.warning_count,
            "checks": g.checks,
            "target_release_id": g.target_release_id,
            "created_at": g.created_at.isoformat() if g.created_at else None,
            "completed_at": g.completed_at.isoformat() if g.completed_at else None,
        }

    def _serialize_release(self, r: CourseRelease) -> dict:
        return {
            "release_id": r.release_id,
            "version": r.version,
            "status": r.status.value,
            "is_active": r.is_active,
            "prev_release_id": r.prev_release_id,
            "label": r.label,
            "release_notes": r.release_notes,
            "content_hash": r.content_hash,
            "quality_gate_passed": r.quality_gate_passed,
            "quality_gate_run_id": r.quality_gate_run_id,
            "published_by": r.published_by,
            "published_at": r.published_at.isoformat() if r.published_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }


course_build_service = CourseBuildService()


# ---------------------------------------------------------------------------
# 源材料服务
# ---------------------------------------------------------------------------


class SourceMaterialService:
    """源材料服务

    - 上传生成新版本；旧版本标记为 superseded
    - 解析基于版本执行；重解析生成新版本，不覆盖旧版本
    """

    def list_materials(self, session: Session, *, course_id: int) -> list[SourceMaterial]:
        return list(session.exec(
            select(SourceMaterial).where(
                SourceMaterial.course_id == course_id,
            ).order_by(SourceMaterial.created_at.desc())
        ).all())

    def get_material(
        self,
        session: Session,
        *,
        course_id: int,
        material_id: str,
    ) -> SourceMaterial:
        m = session.exec(
            select(SourceMaterial).where(
                SourceMaterial.course_id == course_id,
                SourceMaterial.material_id == material_id,
            )
        ).first()
        if m is None:
            reject_resource_not_found("源材料不存在")
        return m

    def create_material(
        self,
        session: Session,
        *,
        course_id: int,
        name: str,
        material_type: str = "document",
        source_kind: str = "upload",
        file_path: str = "",
        file_hash: str = "",
        file_size: int = 0,
        mime_type: str = "",
        created_by: Optional[int] = None,
    ) -> tuple[SourceMaterial, SourceMaterialVersion]:
        """创建材料 + 首版本。"""
        if not name.strip():
            reject_validation_failed("材料名称不能为空")
        material = SourceMaterial(
            course_id=course_id,
            name=name.strip(),
            material_type=material_type,
            source_kind=source_kind,
            status=MaterialStatus.UPLOADED,
            created_by=created_by,
        )
        session.add(material)
        session.flush()

        version = SourceMaterialVersion(
            material_id=material.material_id,
            course_id=course_id,
            version=1,
            file_path=file_path,
            file_hash=file_hash,
            file_size=file_size,
            mime_type=mime_type,
            parse_status=MaterialStatus.UPLOADED,
            is_current=True,
            created_by=created_by,
        )
        session.add(version)
        material.current_version_id = version.version_id
        session.add(material)
        session.flush()
        return material, version

    def add_version(
        self,
        session: Session,
        *,
        course_id: int,
        material_id: str,
        file_path: str = "",
        file_hash: str = "",
        file_size: int = 0,
        mime_type: str = "",
        created_by: Optional[int] = None,
    ) -> SourceMaterialVersion:
        """为已有材料添加新版本；旧版本标记为 superseded。"""
        material = self.get_material(session, course_id=course_id, material_id=material_id)
        # 旧版本置为非 current
        old_versions = session.exec(
            select(SourceMaterialVersion).where(
                SourceMaterialVersion.material_id == material_id,
                SourceMaterialVersion.is_current == True,  # noqa: E712
            )
        ).all()
        for v in old_versions:
            v.is_current = False
            session.add(v)
        # 计算新版本号
        latest_version_num = session.exec(
            select(SourceMaterialVersion).where(
                SourceMaterialVersion.material_id == material_id,
            ).order_by(SourceMaterialVersion.version.desc())
        ).first()
        new_version_num = (latest_version_num.version + 1) if latest_version_num else 1

        version = SourceMaterialVersion(
            material_id=material_id,
            course_id=course_id,
            version=new_version_num,
            file_path=file_path,
            file_hash=file_hash,
            file_size=file_size,
            mime_type=mime_type,
            parse_status=MaterialStatus.UPLOADED,
            is_current=True,
            created_by=created_by,
        )
        session.add(version)
        material.current_version_id = version.version_id
        material.status = MaterialStatus.UPLOADED
        material.updated_at = utcnow_naive()
        session.add(material)
        session.flush()
        return version

    def list_versions(
        self,
        session: Session,
        *,
        course_id: int,
        material_id: str,
    ) -> list[SourceMaterialVersion]:
        # 校验材料归属
        self.get_material(session, course_id=course_id, material_id=material_id)
        return list(session.exec(
            select(SourceMaterialVersion).where(
                SourceMaterialVersion.material_id == material_id,
                SourceMaterialVersion.course_id == course_id,
            ).order_by(SourceMaterialVersion.version.desc())
        ).all())

    def mark_parse_status(
        self,
        session: Session,
        *,
        course_id: int,
        material_id: str,
        version_id: str,
        status: MaterialStatus,
        parse_task_id: Optional[str] = None,
        parse_output_ref: Optional[str] = None,
        parse_error: Optional[str] = None,
    ) -> SourceMaterialVersion:
        version = session.exec(
            select(SourceMaterialVersion).where(
                SourceMaterialVersion.version_id == version_id,
                SourceMaterialVersion.course_id == course_id,
                SourceMaterialVersion.material_id == material_id,
            )
        ).first()
        if version is None:
            reject_resource_not_found("材料版本不存在")
        version.parse_status = status
        if parse_task_id is not None:
            version.parse_task_id = parse_task_id
        if parse_output_ref is not None:
            version.parse_output_ref = parse_output_ref
        if parse_error is not None:
            version.parse_error = parse_error
        session.add(version)
        # 同步 material 状态
        material = self.get_material(session, course_id=course_id, material_id=material_id)
        material.status = status
        material.updated_at = utcnow_naive()
        session.add(material)
        session.flush()
        return version


source_material_service = SourceMaterialService()


# ---------------------------------------------------------------------------
# 质量门禁服务
# ---------------------------------------------------------------------------


class QualityGateService:
    """质量门禁服务

    - 运行一系列检查项（结构完整性、讲稿覆盖、映射一致性等）
    - error/blocker 级别问题阻断发布
    - 每次校验生成一个 run，记录所有检查项结果
    """

    def run_checks(
        self,
        session: Session,
        *,
        course_id: int,
        draft_id: Optional[str] = None,
        initiated_by: Optional[int] = None,
        target_release_id: Optional[str] = None,
    ) -> CourseQualityGateRun:
        """运行质量门禁检查。"""
        checks: list[dict] = []
        blocker_count = 0
        error_count = 0
        warning_count = 0

        # 检查 1：必须至少有一个材料
        materials = source_material_service.list_materials(session, course_id=course_id)
        if not materials:
            checks.append({
                "check_id": "materials.exist",
                "name": "材料存在性",
                "severity": GateSeverity.ERROR.value,
                "passed": False,
                "message": "课程尚未上传任何材料",
            })
            error_count += 1
        else:
            checks.append({
                "check_id": "materials.exist",
                "name": "材料存在性",
                "severity": GateSeverity.INFO.value,
                "passed": True,
                "message": f"共 {len(materials)} 个材料",
            })

        # 检查 2：所有材料必须已解析
        unparsed = [m for m in materials if m.status not in (MaterialStatus.PARSED,)]
        if unparsed:
            checks.append({
                "check_id": "materials.parsed",
                "name": "材料解析完成",
                "severity": GateSeverity.WARNING.value,
                "passed": False,
                "message": f"{len(unparsed)} 个材料未完成解析",
            })
            warning_count += 1
        else:
            checks.append({
                "check_id": "materials.parsed",
                "name": "材料解析完成",
                "severity": GateSeverity.INFO.value,
                "passed": True,
                "message": "所有材料已解析",
            })

        # 检查 3：七步中 materials/structure/scripts 必须非 NOT_STARTED
        steps = session.exec(
            select(CourseBuildStep).where(CourseBuildStep.course_id == course_id)
        ).all()
        steps_map = {s.step_name: s for s in steps}
        required_steps = [BuildStepName.MATERIALS, BuildStepName.STRUCTURE, BuildStepName.SCRIPTS]
        for req_step in required_steps:
            s = steps_map.get(req_step)
            if s is None or s.status == BuildStepStatus.NOT_STARTED:
                checks.append({
                    "check_id": f"steps.{req_step.value}.started",
                    "name": f"步骤 {req_step.value} 已启动",
                    "severity": GateSeverity.ERROR.value,
                    "passed": False,
                    "message": f"步骤 {req_step.value} 尚未启动",
                })
                error_count += 1
            elif s.status == BuildStepStatus.FAILED:
                checks.append({
                    "check_id": f"steps.{req_step.value}.succeeded",
                    "name": f"步骤 {req_step.value} 成功",
                    "severity": GateSeverity.BLOCKER.value,
                    "passed": False,
                    "message": f"步骤 {req_step.value} 处于失败状态",
                })
                blocker_count += 1

        passed = blocker_count == 0 and error_count == 0
        run = CourseQualityGateRun(
            course_id=course_id,
            draft_id=draft_id,
            checks=checks,
            passed=passed,
            blocker_count=blocker_count,
            error_count=error_count,
            warning_count=warning_count,
            target_release_id=target_release_id,
            initiated_by=initiated_by,
            completed_at=utcnow_naive(),
        )
        session.add(run)
        session.flush()
        return run

    def get_run(
        self,
        session: Session,
        *,
        course_id: int,
        gate_run_id: str,
    ) -> CourseQualityGateRun:
        run = session.exec(
            select(CourseQualityGateRun).where(
                CourseQualityGateRun.course_id == course_id,
                CourseQualityGateRun.gate_run_id == gate_run_id,
            )
        ).first()
        if run is None:
            reject_resource_not_found("质量门禁运行不存在")
        return run


quality_gate_service = QualityGateService()


# ---------------------------------------------------------------------------
# 课程发布服务
# ---------------------------------------------------------------------------


class CourseReleaseService:
    """课程发布服务

    - 发布前必须通过质量门禁（error/blocker = 0）
    - 发布后 release 不可变（status=published）
    - 回滚产生新激活版本而非破坏历史（旧 published → superseded）
    - 学生只读 published 且 is_active 的 release
    """

    def list_releases(
        self,
        session: Session,
        *,
        course_id: int,
    ) -> list[CourseRelease]:
        return list(session.exec(
            select(CourseRelease).where(
                CourseRelease.course_id == course_id,
            ).order_by(CourseRelease.version.desc())
        ).all())

    def get_active_release(
        self,
        session: Session,
        *,
        course_id: int,
    ) -> Optional[CourseRelease]:
        return session.exec(
            select(CourseRelease).where(
                CourseRelease.course_id == course_id,
                CourseRelease.is_active == True,  # noqa: E712
            )
        ).first()

    def get_release(
        self,
        session: Session,
        *,
        course_id: int,
        release_id: str,
    ) -> CourseRelease:
        r = session.exec(
            select(CourseRelease).where(
                CourseRelease.course_id == course_id,
                CourseRelease.release_id == release_id,
            )
        ).first()
        if r is None:
            reject_resource_not_found("发布不存在")
        return r

    def create_release_draft(
        self,
        session: Session,
        *,
        course_id: int,
        label: str = "",
        release_notes: str = "",
        created_by: Optional[int] = None,
    ) -> CourseRelease:
        """创建发布草稿（status=draft）。"""
        latest = session.exec(
            select(CourseRelease).where(
                CourseRelease.course_id == course_id,
            ).order_by(CourseRelease.version.desc())
        ).first()
        new_version = (latest.version + 1) if latest else 1

        release = CourseRelease(
            course_id=course_id,
            version=new_version,
            status=ReleaseStatus.DRAFT,
            is_active=False,
            prev_release_id=latest.release_id if latest else None,
            label=label,
            release_notes=release_notes,
            created_by=created_by,
        )
        session.add(release)
        session.flush()
        return release

    def publish_release(
        self,
        session: Session,
        *,
        course_id: int,
        release_id: str,
        published_by: int,
        structure_snapshot: Optional[dict] = None,
        scripts_snapshot: Optional[dict] = None,
        page_mappings_snapshot: Optional[dict] = None,
        media_snapshot: Optional[dict] = None,
        graph_snapshot_ref: Optional[str] = None,
        evidence_refs: Optional[list] = None,
        run_quality_gate: bool = True,
    ) -> CourseRelease:
        """发布：质量门禁通过后，将 release 标记为 published + is_active。

        - 旧 active release 标记为 superseded
        - published 后不可变
        """
        release = self.get_release(session, course_id=course_id, release_id=release_id)
        if release.status == ReleaseStatus.PUBLISHED:
            reject_state_conflict("发布已发布，不可重复发布")
        if release.status == ReleaseStatus.SUPERSEDED:
            reject_state_conflict("发布已被替代，不可再发布")
        if release.status == ReleaseStatus.ROLLED_BACK:
            reject_state_conflict("发布已被回滚，不可再发布")

        # 质量门禁
        if run_quality_gate:
            gate_run = quality_gate_service.run_checks(
                session,
                course_id=course_id,
                draft_id=None,
                initiated_by=published_by,
                target_release_id=release_id,
            )
            release.quality_gate_run_id = gate_run.gate_run_id
            release.quality_gate_passed = gate_run.passed
            if not gate_run.passed:
                session.add(release)
                session.flush()
                reject_state_conflict(
                    "质量门禁未通过，无法发布",
                    details={
                        "blocker_count": gate_run.blocker_count,
                        "error_count": gate_run.error_count,
                        "gate_run_id": gate_run.gate_run_id,
                    },
                )

        # 旧 active release 标记为 superseded
        old_active = self.get_active_release(session, course_id=course_id)
        if old_active is not None and old_active.release_id != release_id:
            old_active.is_active = False
            old_active.status = ReleaseStatus.SUPERSEDED
            session.add(old_active)

        # 填充发布快照
        if structure_snapshot is not None:
            release.structure_snapshot = structure_snapshot
        if scripts_snapshot is not None:
            release.scripts_snapshot = scripts_snapshot
        if page_mappings_snapshot is not None:
            release.page_mappings_snapshot = page_mappings_snapshot
        if media_snapshot is not None:
            release.media_snapshot = media_snapshot
        if graph_snapshot_ref is not None:
            release.graph_snapshot_ref = graph_snapshot_ref
        if evidence_refs is not None:
            release.evidence_refs = evidence_refs

        release.status = ReleaseStatus.PUBLISHED
        release.is_active = True
        release.published_by = published_by
        release.published_at = utcnow_naive()
        session.add(release)
        session.flush()
        return release

    def rollback_to_release(
        self,
        session: Session,
        *,
        course_id: int,
        target_release_id: str,
        actor_user_id: int,
    ) -> CourseRelease:
        """回滚到指定发布：基于旧发布内容创建新激活版本（不破坏历史）。"""
        target = self.get_release(session, course_id=course_id, release_id=target_release_id)
        # 允许回滚到已发布或已被新版本取代（superseded）的历史发布
        if target.status not in (ReleaseStatus.PUBLISHED, ReleaseStatus.SUPERSEDED):
            reject_state_conflict("只能回滚到已发布的版本")

        # 旧 active 标记为 rolled_back
        old_active = self.get_active_release(session, course_id=course_id)
        if old_active is not None:
            old_active.is_active = False
            old_active.status = ReleaseStatus.ROLLED_BACK
            session.add(old_active)

        latest = session.exec(
            select(CourseRelease).where(
                CourseRelease.course_id == course_id,
            ).order_by(CourseRelease.version.desc())
        ).first()
        new_version = (latest.version + 1) if latest else 1

        new_release = CourseRelease(
            course_id=course_id,
            version=new_version,
            status=ReleaseStatus.PUBLISHED,
            is_active=True,
            prev_release_id=old_active.release_id if old_active else None,
            label=f"回滚到 v{target.version}",
            release_notes=f"回滚到 {target.release_id} (v{target.version})",
            structure_snapshot=dict(target.structure_snapshot),
            scripts_snapshot=dict(target.scripts_snapshot),
            page_mappings_snapshot=dict(target.page_mappings_snapshot),
            media_snapshot=dict(target.media_snapshot),
            graph_snapshot_ref=target.graph_snapshot_ref,
            evidence_refs=list(target.evidence_refs),
            quality_gate_passed=True,
            published_by=actor_user_id,
            published_at=utcnow_naive(),
            created_by=actor_user_id,
        )
        session.add(new_release)
        session.flush()
        return new_release

    def add_artifact(
        self,
        session: Session,
        *,
        course_id: int,
        release_id: str,
        artifact_type: str,
        artifact_id: str,
        artifact_version: int = 1,
        artifact_ref: str = "",
    ) -> CourseReleaseArtifact:
        """为发布关联产物。"""
        # 校验 release 归属
        self.get_release(session, course_id=course_id, release_id=release_id)
        art = CourseReleaseArtifact(
            release_id=release_id,
            course_id=course_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            artifact_ref=artifact_ref,
        )
        session.add(art)
        session.flush()
        return art

    def list_artifacts(
        self,
        session: Session,
        *,
        course_id: int,
        release_id: str,
    ) -> list[CourseReleaseArtifact]:
        self.get_release(session, course_id=course_id, release_id=release_id)
        return list(session.exec(
            select(CourseReleaseArtifact).where(
                CourseReleaseArtifact.release_id == release_id,
                CourseReleaseArtifact.course_id == course_id,
            )
        ).all())


course_release_service = CourseReleaseService()
