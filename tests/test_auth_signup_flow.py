import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db_session
from app.db.session import Base
from app.main import app


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
