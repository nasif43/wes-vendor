import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    client = TestClient(app)
    yield client


@pytest.fixture
def db_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:", echo=False)

    # Import models to register them
    from app.database import Base
    Base.metadata.create_all(bind=engine)

    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    session = TestSession()
    yield session
    session.close()
