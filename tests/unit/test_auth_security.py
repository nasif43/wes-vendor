import pytest
from app.auth.security import hash_password, verify_password
from app.auth.models import UserProfile, UserRole


def test_hash_and_verify_password():
    pwd = "pu55inboot$"
    hashed = hash_password(pwd)
    assert hashed != pwd
    assert hashed.startswith("$2b$")
    assert verify_password(pwd, hashed) is True
    assert verify_password("wrongpassword", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(pwd, None) is False


def test_user_profile_password_helpers():
    user = UserProfile(
        email="testuser@example.com",
        username="testuser",
        full_name="Test User",
        role=UserRole.PROCUREMENT,
    )
    user.set_password("mypassword123")
    assert user.password_hash is not None
    assert user.check_password("mypassword123") is True
    assert user.check_password("wrong") is False
