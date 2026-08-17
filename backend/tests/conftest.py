import importlib
import os
import shutil
import socket
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

# P1-1 修复：兼容从仓库根目录或 backend/ 目录运行测试
# - 仓库根目录：pytest.ini 已设 pythonpath=backend，app.* 可导入；
#   但 `from fakes import` 这种无前缀导入需要把 backend/tests 加入 sys.path
# - backend/ 目录：fakes 直接可见
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

_TEST_TMP_PARENT = Path.cwd() / ".pytest_tmp"
_TEST_RUN_ID = os.environ.get("AI_COURSE_TEST_RUN_ID") or (
    f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
)
_TEST_ROOT = _TEST_TMP_PARENT / f"ai_course_{_TEST_RUN_ID}"
_TEST_DB_PATH = _TEST_ROOT / "test_smart_class.db"
_TEST_ROOT.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("AI_COURSE_TESTING", "1")
os.environ.setdefault("AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS", "1")
os.environ.setdefault("AI_COURSE_DATABASE_URL", f"sqlite:///{_TEST_DB_PATH.as_posix()}")
os.environ.setdefault("TTS_PROVIDER", "mock")
os.environ.setdefault("MEDIA_DEMO_MODE", "true")
os.environ.setdefault("STAGE8_TTS_PROVIDER", "fake")
os.environ.setdefault("LLM_API_KEY", "")
os.environ.setdefault("DOUBAO_API_KEY", "")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("XFYUN_PPT_APP_ID", "")
os.environ.setdefault("XFYUN_PPT_API_SECRET", "")
os.environ.setdefault("VOLCENGINE_TTS_ACCESS_TOKEN", "")
os.environ.setdefault("VOLCENGINE_VOICE_CLONE_API_KEY", "")
# 组 A 修复（2026-08-17）：中和豆包 TTS 真实凭据，防止 provider_manager.restore_from_db
# 在 TestClient 启动时把全局 settings 从演示模式(fake)改写为正式豆包模式(doubao)，
# 导致测试会话内所有媒体测试失效（202 vs 200、422 Provider 未注册、cache 缺失）。
os.environ.setdefault("VOLCENGINE_DOUBAO_TTS_WS_URL", "")
os.environ.setdefault("VOLCENGINE_DOUBAO_TTS_API_KEY", "")
os.environ.setdefault("VOLCENGINE_DOUBAO_TTS_RESOURCE_ID", "")
os.environ.setdefault("VOLCENGINE_DOUBAO_TTS_SPEAKER", "")
# P0-1: 测试用内部服务令牌（供 attach-evidence 等服务间调用测试）
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "test-internal-service-token")

from fakes import (
    FakeDigitalHumanClient,
    FakeLLMClient,
    FakePPTClient,
    FakeTTSClient,
    FakeVoiceCloneClient,
)

from app.core.security import create_access_token, get_password_hash
from app.models.user_model import User, UserRole


@pytest.fixture(scope="session")
def test_settings():
    return {
        "test_root": _TEST_ROOT,
        "database_url": os.environ["AI_COURSE_DATABASE_URL"],
        "skip_startup_side_effects": os.environ["AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS"],
    }


@pytest.fixture(scope="session")
def temp_db_path():
    return _TEST_DB_PATH


@pytest.fixture(scope="session")
def test_engine(temp_db_path):
    _TEST_ROOT.mkdir(parents=True, exist_ok=True)
    temp_db_path.parent.mkdir(parents=True, exist_ok=True)
    if temp_db_path.exists():
        temp_db_path.unlink()
    from app.models import database

    assert database.DATABASE_URL == os.environ["AI_COURSE_DATABASE_URL"]
    assert str(database.PRODUCTION_DATABASE_PATH) not in database.DATABASE_URL
    assert temp_db_path.name == "test_smart_class.db"

    # 使用 alembic upgrade head 建库，而非 create_all
    # 这确保测试数据库结构与生产一致（经过迁移链验证）
    # 当 alembic 未安装时回退到 create_all，保证测试可运行
    try:
        from alembic.config import CommandLine
        backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        alembic_ini = os.path.join(backend_root, "alembic.ini")
        cmdline = CommandLine(prog="alembic")
        try:
            cmdline.main(["-c", alembic_ini, "upgrade", "head"])
        except SystemExit as e:
            if e.code not in (None, 0):
                raise RuntimeError(f"alembic upgrade head failed with exit code {e.code}")
    except ModuleNotFoundError:
        # 测试环境未安装 alembic，回退到 create_all 建表
        engine_fallback = create_engine(
            os.environ["AI_COURSE_DATABASE_URL"],
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(engine_fallback)
        engine_fallback.dispose()

    engine = create_engine(
        os.environ["AI_COURSE_DATABASE_URL"],
        connect_args={"check_same_thread": False},
    )
    yield engine
    SQLModel.metadata.drop_all(engine)
    engine.dispose()
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)


@pytest.fixture
def run_alembic(monkeypatch):
    """返回一个函数，用于在指定 SQLite DB 路径上执行 alembic 命令。

    用法:
        run_alembic(db_path, "upgrade", "head")
        run_alembic(db_path, "stamp", "0001")
        run_alembic(db_path, "downgrade", "0002")
    """
    def _run(db_path: str, *alembic_args: str) -> None:
        from alembic.config import CommandLine
        backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        alembic_ini = os.path.join(backend_root, "alembic.ini")
        monkeypatch.setenv("AI_COURSE_DATABASE_URL", f"sqlite:///{db_path}")
        cmdline = CommandLine(prog="alembic")
        try:
            cmdline.main(["-c", alembic_ini] + list(alembic_args))
        except SystemExit as e:
            if e.code not in (None, 0):
                raise RuntimeError(
                    f"alembic {' '.join(alembic_args)} failed with exit code {e.code}"
                )
    return _run


@pytest.fixture(autouse=True)
def block_external_network(monkeypatch):
    real_connect = socket.socket.connect
    real_create_connection = socket.create_connection
    allowed_hosts = {"127.0.0.1", "::1", "localhost"}

    def _is_allowed(host):
        host = str(host)
        return host in allowed_hosts or host.startswith("127.")

    def guarded_connect(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if _is_allowed(host):
            return real_connect(sock, address)
        raise RuntimeError(f"External network calls are blocked in tests: {host}")

    def guarded_create_connection(address, timeout=None, source_address=None):
        host = address[0] if isinstance(address, tuple) else address
        if _is_allowed(host):
            return real_create_connection(address, timeout=timeout, source_address=source_address)
        raise RuntimeError(f"External network calls are blocked in tests: {host}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "create_connection", guarded_create_connection)


@pytest.fixture
def fake_llm():
    return FakeLLMClient()


@pytest.fixture
def fake_tts():
    return FakeTTSClient()


@pytest.fixture
def fake_voice_clone_client():
    return FakeVoiceCloneClient()


@pytest.fixture
def fake_ppt_client():
    return FakePPTClient()


@pytest.fixture
def fake_digital_human_client():
    return FakeDigitalHumanClient()


@pytest.fixture(autouse=True)
def install_external_fakes(monkeypatch, fake_llm, fake_tts, fake_voice_clone_client, fake_ppt_client, fake_digital_human_client):
    llm_module = importlib.import_module("app.common.llm_client")
    tts_module = importlib.import_module("app.common.tts_client")
    digital_module = importlib.import_module("app.common.digital_human_client")
    document_service = importlib.import_module("app.services.document_service")
    mapping_service = importlib.import_module("app.services.mapping_service")
    ppt_service = importlib.import_module("app.services.ppt_generation_service")
    prerequisite_service = importlib.import_module("app.services.prerequisite_service")
    progress_service = importlib.import_module("app.services.progress_service")
    qa_service = importlib.import_module("app.services.qa_service")
    smart_course_service = importlib.import_module("app.services.smart_course_service")
    video_service = importlib.import_module("app.services.video_generation_service")
    asset_endpoint = importlib.import_module("app.api.v1.endpoints.asset")
    document_endpoint = importlib.import_module("app.api.v1.endpoints.document")
    progress_endpoint = importlib.import_module("app.api.v1.endpoints.progress")
    video_generation_endpoint = importlib.import_module("app.api.v1.endpoints.video_generation")

    for module in [
        llm_module,
        document_service,
        mapping_service,
        ppt_service,
        prerequisite_service,
        progress_service,
        qa_service,
        smart_course_service,
        progress_endpoint,
    ]:
        if hasattr(module, "llm_client"):
            monkeypatch.setattr(module, "llm_client", fake_llm)

    for module in [tts_module, document_endpoint, video_service]:
        if hasattr(module, "tts_client"):
            monkeypatch.setattr(module, "tts_client", fake_tts)

    monkeypatch.setattr(tts_module, "voice_clone_client", fake_voice_clone_client)
    monkeypatch.setattr(asset_endpoint, "voice_clone_client", fake_voice_clone_client, raising=False)

    monkeypatch.setattr(digital_module, "digital_human_client", fake_digital_human_client)
    monkeypatch.setattr(video_service, "digital_human_client", fake_digital_human_client)
    monkeypatch.setattr(video_generation_endpoint, "digital_human_client", fake_digital_human_client)

    monkeypatch.setattr(ppt_service.ppt_generation_service, "xfyun_client", fake_ppt_client)


@pytest.fixture(scope="session")
def fastapi_app(test_engine):
    from app.main import app
    from app.models.database import get_session

    def override_get_session():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    return app


@pytest.fixture
def client(fastapi_app):
    with TestClient(fastapi_app) as test_client:
        yield test_client


@pytest.fixture
def session(test_engine):
    with Session(test_engine) as db_session:
        yield db_session
        db_session.rollback()


@pytest.fixture
def teacher_user(session):
    user = User(
        username=f"m4a_teacher_{uuid.uuid4().hex[:8]}",
        real_name="M4A Teacher",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.TEACHER,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def student_user(session):
    user = User(
        username=f"m4a_student_{uuid.uuid4().hex[:8]}",
        real_name="M4A Student",
        hashed_password=get_password_hash("test-password"),
        role=UserRole.STUDENT,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture
def teacher_token(teacher_user):
    return create_access_token({
        "sub": str(teacher_user.id),
        "username": teacher_user.username,
        "role": teacher_user.role.value,
        "school_id": teacher_user.school_id or "test-school",
    })


@pytest.fixture
def student_token(student_user):
    return create_access_token({
        "sub": str(student_user.id),
        "username": student_user.username,
        "role": student_user.role.value,
        "school_id": student_user.school_id or "test-school",
    })


@pytest.fixture
def admin_token():
    return create_access_token({
        "sub": "1",
        "username": "m4a_admin",
        "role": UserRole.ADMIN.value,
        "school_id": "test-school",
    })


def _safe_test_node_name(name: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in name)
    return safe[:80] or "test"


@pytest.fixture
def test_artifact_dir(request):
    path = _TEST_ROOT / "artifacts" / _safe_test_node_name(request.node.name)
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def temp_upload_dir(test_artifact_dir):
    path = test_artifact_dir / "uploads"
    path.mkdir()
    return path


@pytest.fixture
def temp_media_dir(test_artifact_dir):
    path = test_artifact_dir / "media"
    path.mkdir()
    return path


# ---------------------------------------------------------------------------
# P1-10 Product 1 new fake fixtures
# ---------------------------------------------------------------------------

from fakes import (
    FakeCitationValidator,
    FakeLearningEventStore,
    FakeMasteryProvider,
    FakeMemoryStore,
    FakeParserProvider,
    FakeRetrieverProvider,
    FakeSafetyProvider,
)


@pytest.fixture
def fake_parser_provider():
    return FakeParserProvider()


@pytest.fixture
def fake_retriever_provider():
    return FakeRetrieverProvider()


@pytest.fixture
def fake_mastery_provider():
    return FakeMasteryProvider()


@pytest.fixture
def fake_safety_provider():
    return FakeSafetyProvider()


@pytest.fixture
def fake_memory_store():
    return FakeMemoryStore()


@pytest.fixture
def fake_learning_event_store():
    return FakeLearningEventStore()


@pytest.fixture
def fake_citation_validator():
    return FakeCitationValidator()


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)
    try:
        _TEST_TMP_PARENT.rmdir()
    except OSError:
        pass
