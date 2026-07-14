import importlib
import os
import shutil
import socket
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

_TEST_TMP_PARENT = Path.cwd() / ".pytest_tmp"
_TEST_ROOT = _TEST_TMP_PARENT / "ai_course_m4a"
_TEST_DB_PATH = _TEST_ROOT / "test_smart_class.db"
_TEST_ROOT.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("AI_COURSE_TESTING", "1")
os.environ.setdefault("AI_COURSE_SKIP_STARTUP_SIDE_EFFECTS", "1")
os.environ.setdefault("AI_COURSE_DATABASE_URL", f"sqlite:///{_TEST_DB_PATH.as_posix()}")
os.environ.setdefault("TTS_PROVIDER", "mock")
os.environ.setdefault("LLM_API_KEY", "")
os.environ.setdefault("DOUBAO_API_KEY", "")
os.environ.setdefault("QWEN_API_KEY", "")
os.environ.setdefault("WENXIN_API_KEY", "")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("XFYUN_PPT_APP_ID", "")
os.environ.setdefault("XFYUN_PPT_API_SECRET", "")
os.environ.setdefault("VOLCENGINE_TTS_ACCESS_TOKEN", "")
os.environ.setdefault("VOLCENGINE_VOICE_CLONE_API_KEY", "")

from app.core.security import create_access_token, get_password_hash  # noqa: E402
from app.models.user_model import User, UserRole  # noqa: E402
from fakes import (  # noqa: E402
    FakeDigitalHumanClient,
    FakeLLMClient,
    FakePPTClient,
    FakeTTSClient,
    FakeVoiceCloneClient,
)


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

    engine = create_engine(
        os.environ["AI_COURSE_DATABASE_URL"],
        connect_args={"check_same_thread": False},
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)
    engine.dispose()


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

from fakes import (  # noqa: E402
    FakeParserProvider,
    FakeRetrieverProvider,
    FakeMasteryProvider,
    FakeSafetyProvider,
    FakeMemoryStore,
    FakeLearningEventStore,
    FakeCitationValidator,
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
