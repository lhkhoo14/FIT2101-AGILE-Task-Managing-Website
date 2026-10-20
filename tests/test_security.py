import pytest
from server.security import hash_password, verify_password

@pytest.mark.unit
@pytest.mark.parametrize("password", [
    "SimplePassword123!",
    "unicode_pässwörd_🎉",
    "A" * 500  # Very long password boundary
])
def test_security_password_hashing_roundtrip(password):
    """Test password hashing and verification success path."""
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True

@pytest.mark.unit
def test_security_password_verification_failure():
    """Test password verification fails with incorrect credentials."""
    hashed = hash_password("CorrectPassword123")
    assert verify_password("WrongPassword123", hashed) is False