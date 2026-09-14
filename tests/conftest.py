import sys
from pathlib import Path

import pytest
import pytest_asyncio

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def client():
    """Sync test client — use for simple non-DB route tests."""
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    yield client


@pytest.fixture
def db_session():
    """Sync SQLite in-memory session for unit tests."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.database import Base
    # Import all models to register with metadata
    import app.requisitions.models  # noqa: F401
    import app.quotations.models    # noqa: F401
    import app.work_orders.models   # noqa: F401
    import app.vendors.models       # noqa: F401
    import app.auth.models          # noqa: F401
    import app.decisions.models     # noqa: F401
    import app.settings.models      # noqa: F401
    import app.audit.models         # noqa: F401

    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    session = TestSession()
    yield session
    session.close()


@pytest_asyncio.fixture
async def async_db():
    """Async SQLite in-memory session for integration tests."""
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from app.database import Base
    # Import all models
    import app.requisitions.models  # noqa: F401
    import app.quotations.models    # noqa: F401
    import app.work_orders.models   # noqa: F401
    import app.vendors.models       # noqa: F401
    import app.auth.models          # noqa: F401
    import app.decisions.models     # noqa: F401
    import app.settings.models      # noqa: F401
    import app.audit.models         # noqa: F401

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session

    await engine.dispose()


@pytest.fixture
def sample_vendor_data():
    return {
        "id": "vendor-001",
        "company_name": "Test Supplies Co.",
        "contact_email": "supplier@test.com",
        "contact_person": "John Doe",
        "phone": "+1234567890",
    }


@pytest.fixture
def sample_requisition_items():
    return [
        {"name": "Office Chair", "description": "Ergonomic", "qty": 10},
        {"name": "Standing Desk", "description": "Height adjustable", "qty": 5},
        {"name": "Monitor Stand", "description": "Dual arm", "qty": 8},
    ]
