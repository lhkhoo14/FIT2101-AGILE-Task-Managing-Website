import os
import resend

resend.api_key = "re_V4aDdiUB_CkQXcF4wdYk3QA6CCSXDLaow"

# r = resend.Emails.send({
#   "from": "onboarding@resend.dev",
#   "to": "ccha0215@student.monash.edu",
#   "subject": "Hello World",
#   "html": "<p>Congrats on sending your <strong>first email</strong>!</p>"
# })

def send_verification_email(to_email: str, code: str) -> bool:
    html_content = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px;">
        <h2>Verify Your Email</h2>
        <p>Your 6-character verification code is:</p>
        <h1 style="color: #4F46E5; letter-spacing: 4px; font-family: monospace;">{code}</h1>
        <p style="color: #64748b; font-size: 14px; margin-top: 20px;">Please enter this code in the application to activate your account. This code expires in 24 hours.</p>
        <p style="color: #64748b; font-size: 12px;">If you didn't request this, you can safely ignore this email.</p>
    </div>
    """

    try:
        resend.Emails.send({
            "from": "onboarding@resend.dev",
            "to": [to_email],
            "subject": "Your Verification Code",
            "html": html_content,
        })
        return True
    except Exception as e:
        print(f"[Email Error] Failed to send: {e}")
        return False