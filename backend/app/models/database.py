from sqlmodel import SQLModel, create_engine, Session
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
    GraphSnapshotRecord,
    GraphNodeReview,
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
    CourseQualityGateRun,
    CourseRelease,
    CourseReleaseArtifact,
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

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DATABASE_DIR = os.path.join(PROJECT_ROOT, "database")
os.makedirs(DATABASE_DIR, exist_ok=True)

PRODUCTION_DATABASE_PATH = os.path.join(DATABASE_DIR, "smart_class.db")
DEFAULT_DATABASE_URL = f"sqlite:///{PRODUCTION_DATABASE_PATH}"
DATABASE_URL = os.environ.get("AI_COURSE_DATABASE_URL", DEFAULT_DATABASE_URL)

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


def create_tables():
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
