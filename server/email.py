import os
import resend

resend.api_key = "re_V4aDdiUB_CkQXcF4wdYk3QA6CCSXDLaow"

# r = resend.Emails.send({
#   "from": "onboarding@resend.dev",
#   "to": "ccha0215@student.monash.edu",
#   "subject": "Hello World",
#   "html": "<p>Congrats on sending your <strong>first email</strong>!</p>"
# })

def send_verification_email(to_email: str, token: str) -> bool:
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:8000")
    verify_url = f"{frontend_url}/verify?token={token}"
    
    html_content = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px;">
        <h2>Verify Your Email</h2>
        <p>Click the link below to complete your registration:</p>
        <a href="{verify_url}" style="background: #4F46E5; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block;">Verify Account</a>
        <p style="color: #64748b; font-size: 12px; margin-top: 20px;">If you didn't request this, you can safely ignore this email.</p>
    </div>
    """

    try:
        # Note: Resend requires a verified domain, but provides an onboarding domain 
        # (onboarding@resend.dev) for testing instantly without adding a custom domain.
        response = resend.Emails.send({
            "from": "Project App <onboarding@resend.dev>",
            "to": [to_email],
            "subject": "Verify Your Account",
            "html": html_content,
        })
        return True
    except Exception as e:
        print(f"[Email Error] Failed to send: {e}")
        return False