"""Transactional email delivery for the API.

Messages go out through Brevo's HTTPS API instead of SMTP. Render's free web
services block outbound traffic to the SMTP ports (25, 465 and 587), so an
SMTP client works locally but times out once deployed; HTTPS is not restricted.

Configuration comes from the environment only:

    BREVO_API_KEY   Brevo v3 API key. When it is unset nothing is sent and the
                    message is written to the log instead, which is what keeps
                    local development and the test suites offline.
    MAIL_FROM       A sender address verified under Brevo > Senders. Brevo
                    rejects an unverified sender with a 400.
    MAIL_FROM_NAME  Display name shown next to that address.

The key is read per call and never stored in source. A key committed to the
repository - or worse, to a browser-side module - has to be rotated, so it
belongs in Render's environment variables and nowhere else.
"""
import os

import httpx

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
TIMEOUT_SECONDS = 10.0
DEFAULT_FROM_NAME = "John Monash"
SUCCESS_STATUSES = (200, 201, 202)

_CODE_STYLE = 'style="color: #4F46E5; letter-spacing: 4px; font-family: monospace;"'
_NOTE_STYLE = 'style="color: #64748b; font-size: 14px; margin-top: 20px;"'
_FINE_STYLE = 'style="color: #64748b; font-size: 12px;"'


def _send(to_email: str, subject: str, html: str, text: str) -> bool:
    """Deliver one message, returning False if it could not be sent.

    This never raises. A mail provider that is down or misconfigured must not
    turn a signup or a password reset into a 500 the user cannot recover from.
    """
    api_key = os.getenv("BREVO_API_KEY", "").strip()
    mail_from = os.getenv("MAIL_FROM", "").strip()

    if not api_key or not mail_from:
        print(f"[DEV] {subject} for {to_email}:\n{text}")
        return False

    payload = {
        "sender": {
            "email": mail_from,
            "name": os.getenv("MAIL_FROM_NAME", "").strip() or DEFAULT_FROM_NAME,
        },
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
        "textContent": text,
    }

    try:
        response = httpx.post(
            BREVO_URL,
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
                "accept": "application/json",
            },
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        print(f"[mailer] Brevo request failed for {to_email}: {exc}")
        return False

    if response.status_code in SUCCESS_STATUSES:
        return True

    # 400 = sender not verified, 401 = bad key, 403 = IP not authorised,
    # 429 = quota. The response body names the actual cause.
    print(
        f"[mailer] Brevo rejected the email to {to_email}: "
        f"{response.status_code} {response.text[:300]}"
    )
    return False


def send_verification_code(to_email: str, code: str) -> bool:
    """Send the six-character signup verification code (US-24)."""
    html = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px;">
        <h2>Verify Your Email</h2>
        <p>Your 6-character verification code is:</p>
        <h1 {_CODE_STYLE}>{code}</h1>
        <p {_NOTE_STYLE}>Please enter this code in the application to activate your account. This code expires in 24 hours.</p>
        <p {_FINE_STYLE}>If you didn't request this, you can safely ignore this email.</p>
    </div>
    """
    text = (
        f"Your verification code is {code}.\n\n"
        "Enter it in the application to activate your account. "
        "The code expires in 24 hours."
    )
    return _send(to_email, "Your Verification Code", html, text)


def send_password_reset_code(to_email: str, code: str) -> bool:
    """Send the six-character password reset code (US-25)."""
    html = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px;">
        <h2>Reset Your Password</h2>
        <p>Your 6-character password reset code is:</p>
        <h1 {_CODE_STYLE}>{code}</h1>
        <p {_NOTE_STYLE}>Please enter this code in the application to reset your password. This code expires in 15 minutes.</p>
        <p {_FINE_STYLE}>If you didn't request this, you can safely ignore this email.</p>
    </div>
    """
    text = (
        f"Your password reset code is {code}.\n\n"
        "Enter it in the application to reset your password. "
        "The code expires in 15 minutes."
    )
    return _send(to_email, "Password Reset Code", html, text)


def send_verification_email(to_email: str, link: str) -> bool:
    """Send the confirm-your-new-address link used by the email change flow.

    The link flow is kept separate from the code flows so the caller's variable
    name matches what is actually in the message.
    """
    html = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px;">
        <h2>Confirm Your New Email</h2>
        <p>Please confirm your new email address by clicking the button below.</p>
        <p>
            <a href="{link}" style="background: #4F46E5; color: #ffffff; padding: 12px 20px; text-decoration: none; border-radius: 6px;">Confirm Email Address</a>
        </p>
        <p {_NOTE_STYLE}>This link expires in 24 hours and can be ignored if you didn't request this change.</p>
    </div>
    """
    text = (
        "Please confirm your new email address by clicking the following link:"
        f"\n\n{link}\n\n"
        "This link expires in 24 hours and can be ignored if you didn't "
        "request this change."
    )
    return _send(to_email, "Confirm your new email address - John Monash", html, text)
