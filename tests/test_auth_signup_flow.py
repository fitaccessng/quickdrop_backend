import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db_session
from app.core.config import settings
from app.db.session import Base
from app.main import app
from app.schemas.auth import GoogleOAuthUser


@pytest_asyncio.fixture
async def auth_signup_test_context():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async def override_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db
    try:
        yield {"engine": engine, "session_factory": session_factory}
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_unified_signup_rejects_invalid_role(auth_signup_test_context):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/unified-signup",
            json={
                "full_name": "Bad Role User",
                "email": "bad-role@example.com",
                "phone": "123456789",
                "password": "Password123",
                "role": "superadmin",
            },
        )

    assert response.status_code == 422
    assert "role" in response.text.lower()


@pytest.mark.asyncio
async def test_admin_signup_and_login(auth_signup_test_context):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        signup_response = await client.post(
            "/auth/unified-signup",
            json={
                "full_name": "Platform Admin",
                "email": "platform-admin@example.com",
                "phone": "123456789",
                "password": "Password123",
                "role": "admin",
            },
        )
        login_response = await client.post(
            "/auth/unified-login",
            json={
                "email": "platform-admin@example.com",
                "password": "Password123",
            },
        )

    assert signup_response.status_code == 201
    assert signup_response.json()["account_type"] == "admin"
    assert login_response.status_code == 200
    assert login_response.json()["account_type"] == "admin"


@pytest.mark.asyncio
async def test_signup_preflight_allows_production_frontend(auth_signup_test_context):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.options(
            "/auth/unified-signup",
            headers={
                "Origin": "https://www.quickdrop.online",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,authorization",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://www.quickdrop.online"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "Authorization" in response.headers["access-control-allow-headers"]


@pytest.mark.asyncio
async def test_signup_validation_error_keeps_cors_headers(auth_signup_test_context):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/unified-signup",
            headers={"Origin": "https://www.quickdrop.online"},
            json={
                "full_name": "Invalid Signup",
                "email": "invalid-signup@example.com",
                "phone": "123456789",
                "password": "Password123",
                "role": "invalid",
            },
        )

    assert response.status_code == 422
    assert response.headers["access-control-allow-origin"] == "https://www.quickdrop.online"
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.asyncio
async def test_google_signup_prompts_for_role_then_creates_selected_account(
    auth_signup_test_context, monkeypatch
):
    async def validate_google_token(token, client_id):
        assert token == "valid-google-id-token"
        assert client_id == "test-google-client-id"
        return GoogleOAuthUser(
            id="google-user-123",
            email="google-rider@example.com",
            name="Google Rider",
        )

    monkeypatch.setattr(settings, "google_client_id", "test-google-client-id")
    monkeypatch.setattr("app.api.auth.validate_google_token", validate_google_token)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        role_prompt = await client.post(
            "/auth/oauth/google",
            json={"token": "valid-google-id-token"},
        )
        signup = await client.post(
            "/auth/oauth/google",
            json={"token": "valid-google-id-token", "role": "rider"},
        )

    assert role_prompt.status_code == 200
    assert role_prompt.json()["requires_role_selection"] is True
    assert role_prompt.json()["access_token"] is None
    assert signup.status_code == 200
    assert signup.json()["account_type"] == "rider"
    assert signup.json()["user"]["role"] == "rider"
