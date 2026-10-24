import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.auth.models import UserProfile, UserRole
from app.database import AsyncSessionLocal, init_db


@pytest.mark.asyncio
async def test_functional_login():
    from app.database import engine
    await engine.dispose()
    await init_db()
    uid = uuid.uuid4().hex[:8]
    test_email = f"proc_{uid}@example.com"
    test_username = f"proc_{uid}"

    async with AsyncSessionLocal() as session:
        user = UserProfile(
            email=test_email,
            username=test_username,
            full_name="Dynamic Procure",
            role=UserRole.PROCUREMENT,
        )
        user.set_password("secretpass123")
        session.add(user)
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Invalid password
        res = await client.post("/auth/login", data={"username": test_username, "password": "wrongpassword"})
        assert res.status_code == 401
        assert "Invalid username" in res.text

        # 2. Login with username
        res_user = await client.post("/auth/login", data={"username": test_username, "password": "secretpass123"})
        assert res_user.status_code == 303
        assert res_user.headers["location"] == "/"

        # 3. Login with email
        res_email = await client.post("/auth/login", data={"username": test_email, "password": "secretpass123"})
        assert res_email.status_code == 303
        assert res_email.headers["location"] == "/"

    from app.database import engine
    await engine.dispose()

