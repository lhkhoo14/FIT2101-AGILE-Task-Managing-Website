from pyscript import window  # type: ignore

ACTIVE_SESSION_KEY = "session_user_id"
API_URL = (
    "http://127.0.0.1:8000/api"
    if window.location.hostname in ("localhost", "127.0.0.1")
    else "https://fit2101-api.onrender.com/api"
)
RESEND_API_KEY= "re_V4aDdiUB_CkQXcF4wdYk3QA6CCSXDLaow"