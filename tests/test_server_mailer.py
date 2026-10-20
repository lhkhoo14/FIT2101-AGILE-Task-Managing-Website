"""server/mailer.py: transactional email through Brevo's HTTPS API (no real network)."""
import httpx
import pytest

import mailer


class FakeResponse:
    def __init__(self, status_code=201, text=""):
        self.status_code = status_code
        self.text = text


@pytest.fixture
def brevo(monkeypatch):
    """Configured credentials and a fake httpx.post that records what would be sent."""
    monkeypatch.setenv("BREVO_API_KEY", "test-key")
    monkeypatch.setenv("MAIL_FROM", "noreply@x.com")
    monkeypatch.delenv("MAIL_FROM_NAME", raising=False)
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse(201)

    monkeypatch.setattr(mailer.httpx, "post", fake_post)
    return calls


@pytest.mark.unit
@pytest.mark.parametrize("name,arg,subject", [
    ("send_verification_code", "ABC123", "Your Verification Code"),
    ("send_password_reset_code", "XYZ789", "Password Reset Code"),
    ("send_verification_email", "http://x/y?verify_email=tok", "Confirm your new email address"),
])
def test_each_message_is_sent_through_brevo(brevo, name, arg, subject):
    assert getattr(mailer, name)("a@x.com", arg) is True
    call = brevo[0]
    assert call["url"] == mailer.BREVO_URL
    assert call["headers"]["api-key"] == "test-key"
    assert call["json"]["to"] == [{"email": "a@x.com"}]
    assert call["json"]["sender"] == {"email": "noreply@x.com", "name": mailer.DEFAULT_FROM_NAME}
    assert subject in call["json"]["subject"]
    assert arg in call["json"]["textContent"] and arg in call["json"]["htmlContent"]


@pytest.mark.unit
def test_sender_name_can_be_configured(brevo, monkeypatch):
    monkeypatch.setenv("MAIL_FROM_NAME", "Team 2")
    mailer.send_verification_code("a@x.com", "ABC123")
    assert brevo[0]["json"]["sender"]["name"] == "Team 2"


@pytest.mark.unit
@pytest.mark.parametrize("missing", ["BREVO_API_KEY", "MAIL_FROM"])
def test_without_credentials_nothing_is_sent_and_it_is_logged(brevo, monkeypatch, capsys, missing):
    monkeypatch.delenv(missing)
    assert mailer.send_verification_code("a@x.com", "ABC123") is False
    assert brevo == []
    assert "[DEV]" in capsys.readouterr().out


@pytest.mark.unit
def test_a_rejected_email_returns_false(brevo, monkeypatch, capsys):
    monkeypatch.setattr(mailer.httpx, "post", lambda *a, **k: FakeResponse(400, "sender not verified"))
    assert mailer.send_password_reset_code("a@x.com", "ABC123") is False
    assert "rejected" in capsys.readouterr().out


@pytest.mark.unit
def test_an_unreachable_provider_never_raises(brevo, monkeypatch, capsys):
    def down(*args, **kwargs):
        raise httpx.ConnectError("provider down")

    monkeypatch.setattr(mailer.httpx, "post", down)
    assert mailer.send_verification_email("a@x.com", "http://x/y") is False
    assert "request failed" in capsys.readouterr().out