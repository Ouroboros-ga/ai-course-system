from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy import event
from typing import Generator
import os

from app.models.course_model import (
    Course,
    CourseScript,
    ScriptNode,
    DoclingDocument,
    DoclingGroup,
    DoclingTable,
    DoclingTableCell,
    DoclingText,
    DoclingPicture,
    StudentEnrollment,
)
from app.models.access_control_model import (
    CourseCapability,
    CourseMembership,
    PlatformPermissionAssignment,
)
from app.models.user_model import (
    User,
    ChatHistory,
    ChatMessage,
)
from app.models.progress_model import (
    LearningProgress,
    NodeProgress,
    UnderstandingAnalysis,
    LearningJumpHistory,
)
from app.models.knowledge_model import (
    KnowledgeBase,
    KnowledgePoint,
    KnowledgeRelation,
    KnowledgeImportLog,
    KnowledgeSearchHistory,
)
from app.models.mapping_model import (
    KnowledgePageMap,
)
from app.models.video_generation_model import (
    VideoGenerationTask,
)
from app.models.asset_model import (
    TeacherAsset,
)
from app.models.qa_model import (
    QASession,
    QAMessage,
    QAContext,
)
from app.models.document_artifact_model import DocumentArtifact
from app.models.note_model import Note
from app.models.confirmation_model import CourseConfirmation
from app.models.feedback_model import Feedback
from app.models.question_bank_model import (
    QuestionBankItem,
    QuestionSourceMapping,
    QuestionAttempt,
)
from app.models.cognitive_state_model import (
    CognitiveState,
    LearningEvidenceRecord,
    RecommendationRecord,
)
from app.models.visualization_model import VisualizationPlanRecord
from app.models.safety_policy_model import (
    CourseSafetyPolicy,
    CourseSandboxPolicy,
    SafetyAuditLog,
)
from app.models.web_research_model import (
    WebResearchConfig,
    WebResearchResult,
    ExternalReference,
)
from app.models.media_timeline_model import (
    MediaAsset,
    MediaTimelineCue,
)
from app.models.graph_production_model import (
    CourseEvidenceRecord,
    CourseKnowledgeNode,
    GraphSnapshotRecord,
    GraphNodeReview,
)
from app.models.unified_learning_model import (
    LearningEvent,
    StudentLearningProjection,
    CourseLearningStatsProjection,
    LearningEvidenceContext,
)
from app.models.knowledge_bundle_model import (
    GraphRagRun,
    GraphRagEntityMapping,
    CourseVectorIndex,
    CourseKnowledgeBundle,
    CourseKnowledgeHead,
    CourseKnowledgeActivation,
    CourseKnowledgeBuildLease,
    LearningProjectionOutbox,
)
from app.models.agent_log import (
    AgentLearningEvent,
    AgentTraceRecord,
    AgentConversationSession,
    AgentLogMigrationRecord,
)
from app.models.task_model import (
    SchemaMigrationRecord,
    TaskRecord,
    TaskEventRecord,
    TaskResourceLinkRecord,
    IdempotencyKeyRecord,
)
from app.models.course_lifecycle_model import (
    CourseJoinRequest,
    CourseGroup,
    CourseGroupMember,
    CourseSettingVersion,
    CourseAuditEvent,
    IntegrationSyncRun,
)
from app.models.course_build_model import (
    CourseBuildDraft,
    CourseBuildStep,
    SourceMaterial,
    SourceMaterialVersion,
    CourseCorpusSnapshot,
    CourseCorpusItem,
    CourseRetrievalSnapshot,
    CourseDraftBuildTask,
    CourseDraftBuildCheckpoint,
    CourseQualityGateRun,
    CourseRelease,
    CourseReleaseArtifact,
)
from app.models.course_outline_model import (
    CourseOutlineVersion,
    CourseOutlineNode,
    CoursePptMapping,
    OutlineNodeType,
    OutlineLifecycleStatus,
    TeachingScriptVersion,
    TeachingScriptNode,
    CourseScriptCoverageIssue,
    PatchProposal,
    PatchProposalOperation,
    PatchProposalStatus,
    PatchOperation,
)
# 阶段4：课程材料解析、Evidence、Citation 与图谱候选
from app.models.document_parse_model import (
    DocumentParseRun,
    DocumentBlock,
    EvidenceSpan,
    EvidenceCitation,
    EvidenceRenderAsset,
    GraphCandidateBatch,
    GraphReleaseLink,
    DocumentIRVersion,
    EvidenceAnchor,
    RetrievalChunk,
    RetrievalIndexSnapshot,
    DocumentParseOwnerLease,
)
# 阶段5：题库导入、AI 生成草稿、个性化练习推荐与正式学习证据链接
from app.models.practice_recommendation_model import (
    QuestionImportRun,
    QuestionGenerationDraft,
    QuestionRecommendationRun,
    QuestionRecommendationItem,
    AssessmentPolicy,
    LearningEvidenceLink,
)
# 阶段6：课程实验、版本、测试用例、尝试、运行与 CodingAgent 提示记录
from app.models.experiment_model import (
    ExperimentDefinition,
    ExperimentVersion,
    ExperimentTestCase,
    ExperimentAttempt,
    ExperimentRun,
    ExperimentRunArtifact,
    CodingHintRecord,
)
from app.models.coding_diagnosis_model import CodingDiagnosisRecord
# 阶段7：通用资源库、回收站与平台实验室目录
from app.models.resource_model import (
    ResourceItem,
    ResourceVersion,
    ResourceTag,
    ResourceReference,
    ResourceAclEntry,
    RecycleBinEntry,
    LabCatalogEntry,
    LabEnrollment,
    LabRecord,
)
# 阶段8：媒体生成任务、发布版本、播放能力配置与教师数字人资产中心
from app.models.media_release_model import (
    MediaGenerationJob,
    MediaGenerationAttempt,
    MediaRelease,
    MediaReleaseCue,
    MediaBuildBatch,
    MediaReleaseItem,
    PlaybackCapabilityProfile,
)
from app.models.platform_media_preset_model import (
    PlatformVoicePreset,
    PlatformAvatarPreset,
)
from app.models.avatar_model import (
    AvatarProfile,
    AvatarSourceMedia,
    AvatarPreparationJob,
    AvatarAssetPackage,
    CourseAvatarBinding,
)
# 阶段9：Agent 工具治理与教师安全阀
from app.models.agent_governance_model import (
    AgentPolicyVersion,
    AgentToolPolicy,
    AgentActionProposal,
    AgentActionDecision,
    AgentToolInvocation,
)
from app.models.agent_run_model import (
    AgentRunRecord,
    AgentRunEventRecord,
    AgentLLMDiagnosticRecord,
)
from app.models.platform_admin_model import (
    PlatformIntegrationConfig,
    PlatformAdminAuditEvent,
    PlatformTaskConcurrencyConfig,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATABASE_DIR = os.path.join(PROJECT_ROOT, "database")
os.makedirs(DATABASE_DIR, exist_ok=True)

PRODUCTION_DATABASE_PATH = os.path.join(DATABASE_DIR, "smart_class.db")
DEFAULT_DATABASE_URL = f"sqlite:///{PRODUCTION_DATABASE_PATH}"
DATABASE_URL = os.environ.get("AI_COURSE_DATABASE_URL", DEFAULT_DATABASE_URL)


def _build_connect_args(url: str) -> dict:
    """按数据库类型构建连接参数。

    SQLite 需要 check_same_thread=False（FastAPI 多线程访问）；
    PostgreSQL/MySQL 不需要且不接受该参数。
    """
    if url.startswith("sqlite"):
        # SQLite is used by the local/demo deployment and is accessed by the
        # request process and task worker concurrently.  ``timeout`` makes the
        # sqlite driver wait for a short-lived writer instead of immediately
        # surfacing ``database is locked``.
        return {"check_same_thread": False, "timeout": 30.0}
    return {}


def _positive_int_env(name: str, default: int) -> int:
    """Read bounded pool settings without making startup fragile.

    Invalid values are deliberately ignored in favour of the safe deployment
    default.  These knobs are only consumed by PostgreSQL engines; SQLite
    retains its single-file behaviour and PRAGMA configuration below.
    """
    raw_value = os.environ.get(name, "").strip()
    if not raw_value:
        return default
    try:
        return max(1, int(raw_value))
    except ValueError:
        return default


def _build_engine_kwargs(url: str) -> dict:
    """Return dialect-specific engine configuration.

    PostgreSQL runs behind two Uvicorn workers and durable task handlers.  A
    small bounded pool per process avoids stale connections after container or
    database restarts while keeping the total connection budget predictable.
    """
    kwargs: dict = {
        "echo": False,
        "connect_args": _build_connect_args(url),
    }
    if url.startswith("postgresql"):
        kwargs.update(
            pool_pre_ping=True,
            pool_size=_positive_int_env("AI_COURSE_DB_POOL_SIZE", 5),
            max_overflow=_positive_int_env("AI_COURSE_DB_MAX_OVERFLOW", 5),
            pool_recycle=_positive_int_env("AI_COURSE_DB_POOL_RECYCLE_SECONDS", 1800),
            pool_timeout=_positive_int_env("AI_COURSE_DB_POOL_TIMEOUT_SECONDS", 30),
            isolation_level="READ COMMITTED",
        )
    return kwargs


engine = create_engine(
    DATABASE_URL,
    **_build_engine_kwargs(DATABASE_URL),
)


@event.listens_for(engine, "connect")
def _configure_sqlite_connection(dbapi_connection, connection_record) -> None:
    """Apply bounded-writer settings only to SQLite connections.

    The listener is intentionally attached to this engine (rather than using
    application startup SQL) so every pooled connection, including worker
    sessions, receives the same settings.  Other database dialects are not
    affected.
    """
    dialect = engine.url.get_backend_name()
    if dialect == "postgresql":
        # The source SQLite history contains both naive and aware timestamps.
        # PostgreSQL sessions are fixed to UTC so service code has one stable
        # interpretation while the transfer tool normalizes legacy rows.
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET TIME ZONE 'UTC'")
        finally:
            cursor.close()
        return
    if dialect != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def create_tables():
    """仅用于开发/测试空库初始化。

    生产部署必须使用 `alembic upgrade head` 建表和迁移；
    应用启动路径不再调用此函数（见 app.main）。
    """
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """
    依赖注入函数：生成数据库会话。
    用法：在 FastAPI 路径操作函数中作为 Depends(get_session) 使用。

    yield 机制确保即使发生异常，session 也会在最后被正确关闭。
    """
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()


def session_factory() -> Session:
    """任务 worker 使用的会话工厂。

    返回一个新的 Session，可作为上下文管理器使用：
        with session_factory() as session:
            ...

    LocalTaskWorker 的 handler 通过 ctx.session_factory() 获取独立 session，
    避免与请求级事务耦合。
    """
    return Session(engine)
