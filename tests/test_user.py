import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.main import app  # 假设 FastAPI 应用实例在 app/main.py 中
from app.core.security import get_password_hash
from app.models.database import get_session
from app.models.user_model import User, UserRole
from app.schemas.common_schema import LoginRequest



# ---------------------------
# 测试数据库 Fixture
# ---------------------------
@pytest.fixture(name="session")
def session_fixture():
    """创建内存 SQLite 数据库，并初始化表结构"""
    engine = create_engine(
        "sqlite://",  # 内存数据库
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    """创建测试客户端，并覆盖 get_session 依赖，使用测试会话"""

    def override_get_session():
        return session

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()  # 测试结束后清除覆盖


# ---------------------------
# 准备测试数据
# ---------------------------
@pytest.fixture(autouse=True)
def create_test_users(session: Session):
    """在每个测试前自动插入两个测试用户（教师、学生）"""
    # 教师用户（已激活）
    teacher = User(
        username="teacher1",
        hashed_password=get_password_hash("123456"),
        role=UserRole.TEACHER,
        school_id="sch10001",
        is_active=True,
        email="teacher@example.com",
        real_name="张老师",
    )
    # 学生用户（已激活）
    student = User(
        username="student1",
        hashed_password=get_password_hash("123456"),
        role=UserRole.STUDENT,
        school_id="sch10001",
        is_active=True,
        email="student@example.com",
        real_name="李学生",
    )
    # 未激活用户（用于测试禁用账号）
    inactive_user = User(
        username="inactive",
        hashed_password=get_password_hash("123456"),
        role=UserRole.STUDENT,
        school_id="sch10001",
        is_active=False,
        email="inactive@example.com",
    )
    session.add(teacher)
    session.add(student)
    session.add(inactive_user)
    session.commit()


# ---------------------------
# 测试用例
# ---------------------------
def test_login_success(client: TestClient):
    """测试正常登录，应返回 200 和 token"""
    response = client.post(
        "/api/v1/user/login",
        json={"username": "teacher1", "password": "123456"},
    )

    print(f"\nStatus Code: {response.status_code}")
    print(f"Response Body: {response.text}")

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert data["msg"] == "登录成功"
    assert "data" in data
    assert "authToken" in data["data"]
    assert data["data"]["internalUserId"] is not None


def test_login_wrong_password(client: TestClient):
    """测试密码错误，应返回 401"""
    response = client.post(
        "/api/v1/user/login",
        json={"username": "teacher1", "password": "wrongpass"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["msg"] == "用户名或密码错误"


def test_login_user_not_exist(client: TestClient):
    """测试用户不存在，应返回 401"""
    response = client.post(
        "/api/v1/user/login",
        json={"username": "unknown", "password": "123456"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["msg"] == "用户名或密码错误"


def test_login_inactive_user(client: TestClient):
    """测试未激活用户登录，应返回 403"""
    response = client.post(
        "/api/v1/user/login",
        json={"username": "inactive", "password": "123456"},
    )
    assert response.status_code == 403
    data = response.json()
    assert data["msg"] == "账户已禁用，请联系管理员"


def test_get_me_without_token(client: TestClient):
    """测试未提供 token 访问 /me，应返回 401"""
    response = client.get("/api/v1/user/me")
    assert response.status_code == 401


def test_get_me_with_token(client: TestClient):
    """先登录获取 token，然后用 token 访问 /me，应返回用户信息"""
    # 1. 登录
    login_resp = client.post(
        "/api/v1/user/login",
        json={"username": "student1", "password": "123456"},
    )
    token = login_resp.json()["data"]["authToken"]

    # 2. 携带 token 访问 /me
    response = client.get(
        "/api/v1/user/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert data["msg"] == "获取成功"
    user_info = data["data"]
    assert user_info["username"] == "student1"
    assert user_info["role"] == "student"
    # 确保密码哈希不被返回
    assert "hashed_password" not in user_info


def test_get_me_with_invalid_token(client: TestClient):
    """使用无效 token 访问 /me，应返回 401"""
    response = client.get(
        "/api/v1/user/me",
        headers={"Authorization": "Bearer invalid.token.here"},
    )
    assert response.status_code == 401