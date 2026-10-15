import os
import smtplib
from email.message import EmailMessage

def send_verification_email(to_email: str, link: str) -> bool:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    mail_from = os.getenv("MAIL_FROM", smtp_user)

    if not smtp_host:
        print(f"[DEV] email verification link for {to_email}: {link}")
        return False

    try:
        msg = EmailMessage()
        msg["Subject"] = "Confirm your new email address - John Monash"
        msg["From"] = mail_from
        msg["To"] = to_email
        msg.set_content(
            f"Please confirm your new email address by clicking the following link:\n\n{link}\n\n"
            "This link expires in 24 hours and can be ignored if you didn't request this change."
        )

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Error sending verification email: {e}")
        return False