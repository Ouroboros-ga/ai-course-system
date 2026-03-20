import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.main import app
from app.core.security import get_password_hash
from app.models.database import get_session
from app.models.user_model import User, UserRole


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    def override_get_session():
        return session

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def create_test_users(session: Session):
    teacher = User(
        username="teacher1",
        hashed_password=get_password_hash("123456"),
        role=UserRole.TEACHER,
        school_id="sch10001",
        is_active=True,
        email="teacher@example.com",
        real_name="张老师",
    )
    student = User(
        username="student1",
        hashed_password=get_password_hash("123456"),
        role=UserRole.STUDENT,
        school_id="sch10001",
        is_active=True,
        email="student@example.com",
        real_name="李学生",
    )
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


def test_login_success(client: TestClient):
    response = client.post(
        "/api/v1/user/login",
        json={"username": "teacher1", "password": "123456"},
    )

    print(f"\nStatus Code: {response.status_code}")
    print(f"Response Body: {response.text}")

    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert data["message"] == "登录成功"
    assert "data" in data
    assert "token" in data["data"]
    assert "userInfo" in data["data"]
    assert "id" in data["data"]["userInfo"]


def test_login_wrong_password(client: TestClient):
    response = client.post(
        "/api/v1/user/login",
        json={"username": "teacher1", "password": "wrongpass"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 401
    assert data["message"] == "用户名密码错误"
    assert data["data"] is None


def test_login_user_not_exist(client: TestClient):
    response = client.post(
        "/api/v1/user/login",
        json={"username": "unknown", "password": "123456"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 401
    assert data["message"] == "用户名密码错误"
    assert data["data"] is None


def test_login_inactive_user(client: TestClient):
    response = client.post(
        "/api/v1/user/login",
        json={"username": "inactive", "password": "123456"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 403
    assert data["message"] == "账户已禁用"
    assert data["data"] is None


def test_register_success(client: TestClient):
    response = client.post(
        "/api/v1/user/register",
        json={"username": "newuser", "password": "newpass123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert data["message"] == "注册并登录成功"
    assert "data" in data
    assert "token" in data["data"]
    assert "userInfo" in data["data"]
    assert "id" in data["data"]["userInfo"]


def test_register_duplicate_username(client: TestClient):
    response = client.post(
        "/api/v1/user/register",
        json={"username": "teacher1", "password": "newpass123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 409
    assert data["message"] == "用户名已存在"
    assert data["data"] is None


def test_get_me_without_token(client: TestClient):
    response = client.get("/api/v1/user/me")
    assert response.status_code == 401


def test_get_me_with_token(client: TestClient):
    login_resp = client.post(
        "/api/v1/user/login",
        json={"username": "student1", "password": "123456"},
    )
    token = login_resp.json()["data"]["token"]

    response = client.get(
        "/api/v1/user/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert data["message"] == "获取成功"
    user_info = data["data"]
    assert user_info["username"] == "student1"
    assert user_info["role"] == "student"


def test_get_me_with_invalid_token(client: TestClient):
    response = client.get(
        "/api/v1/user/me",
        headers={"Authorization": "Bearer invalid.token.here"},
    )
    assert response.status_code == 401
