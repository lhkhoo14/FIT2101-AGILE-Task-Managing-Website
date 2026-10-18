"""Offline checks for the transactional email layer.

The mailer talks to Brevo over HTTPS. These checks need no network and no API
key: the HTTP call is replaced with a stub, and the dev fallback is exercised by
clearing BREVO_API_KEY. That way CI, a teammate's laptop and the deployed
service behave the same way, and a test never sends real mail.

Run it from the repository root with:

    .venv\\Scripts\\python.exe server\\tests\\test_mailer.py

Every check is printed and the process exits non-zero if any failed. It is a
plain script rather than a pytest module because the repository has no test
runner configured.
"""
import contextlib
import io
import os
import pathlib
import re
import sys

import httpx

TESTS_DIR = pathlib.Path(__file__).resolve().parent
SERVER = TESTS_DIR.parent                     # the server package
REPO = SERVER.parent                          # the repository root

sys.path.insert(0, str(SERVER))
import mailer  # noqa: E402

results = []
failures = []


def check(label, condition, detail: object = ""):
    results.append(bool(condition))
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + ("" if condition else f"  <- {detail}"))
    if not condition:
        failures.append(label)


captured = []
real_post = httpx.post


def stub(status_code: int = 201, body: str = '{"messageId":"<test>"}', error=None):
    """Return a stand-in for httpx.post that records what the mailer sent."""
    def _post(url, headers=None, json=None, timeout=None):
        captured.append({"url": url, "headers": headers or {}, "json": json, "timeout": timeout})
        if error is not None:
            raise error
        return httpx.Response(status_code, text=body)
    return _post


def configure(key: str = "xkeysib-test-key", mail_from: str = "sender@example.com",
              name: str = "Agasti Ngoh"):
    os.environ["BREVO_API_KEY"] = key
    os.environ["MAIL_FROM"] = mail_from
    os.environ["MAIL_FROM_NAME"] = name


def unconfigure():
    for var in ("BREVO_API_KEY", "MAIL_FROM", "MAIL_FROM_NAME"):
        os.environ.pop(var, None)


# --- 1. Local development and CI run without a key ------------------------
unconfigure()
captured.clear()
setattr(httpx, "post", stub())
log = io.StringIO()
with contextlib.redirect_stdout(log):
    sent = mailer.send_verification_code("dev@example.com", "AB12CD")
check("without BREVO_API_KEY nothing is reported as sent", sent is False, sent)
check("without BREVO_API_KEY no HTTP request happens", captured == [], captured)
check("without BREVO_API_KEY the code is written to the log", "AB12CD" in log.getvalue(), log.getvalue())

# --- 2. A configured send builds the Brevo payload -------------------------
configure()
captured.clear()
setattr(httpx, "post", stub(201))
sent = mailer.send_verification_code("user@example.com", "AB12CD")
request = captured[0] if captured else {}
payload = request.get("json") or {}

check("a 201 response counts as sent", sent is True, sent)
check("posts to the Brevo transactional endpoint", request.get("url") == mailer.BREVO_URL, request.get("url"))
check("authenticates with the api-key header",
      (request.get("headers") or {}).get("api-key") == "xkeysib-test-key", request.get("headers"))
check("sends JSON", (request.get("headers") or {}).get("Content-Type") == "application/json",
      request.get("headers"))
check("sender is MAIL_FROM with MAIL_FROM_NAME",
      payload.get("sender") == {"email": "sender@example.com", "name": "Agasti Ngoh"}, payload.get("sender"))
check("recipient is the requested address",
      payload.get("to") == [{"email": "user@example.com"}], payload.get("to"))
check("the code appears in the HTML body", "AB12CD" in str(payload.get("htmlContent", "")))
check("the code appears in the text body", "AB12CD" in str(payload.get("textContent", "")))
check("a subject is set", bool(str(payload.get("subject", "")).strip()), payload.get("subject"))
check("the request has a timeout", request.get("timeout") == mailer.TIMEOUT_SECONDS, request.get("timeout"))

# --- 3. Provider failures are reported, never raised -----------------------
captured.clear()
setattr(httpx, "post", stub(400, '{"message":"sender not valid"}'))
log = io.StringIO()
with contextlib.redirect_stdout(log):
    rejected = mailer.send_verification_code("user@example.com", "AB12CD")
check("a Brevo rejection returns False", rejected is False, rejected)
check("a Brevo rejection is logged with its response", "sender not valid" in log.getvalue(), log.getvalue())

captured.clear()
setattr(httpx, "post", stub(error=httpx.ConnectError("connection refused")))
log = io.StringIO()
with contextlib.redirect_stdout(log):
    failed = mailer.send_password_reset_code("user@example.com", "ZZ99ZZ")
check("a network error returns False instead of raising", failed is False, failed)
check("a network error is logged", "connection refused" in log.getvalue(), log.getvalue())

# --- 4. The email-change link flow ----------------------------------------
captured.clear()
setattr(httpx, "post", stub(202))
link = "https://fit2101-frontend-fiie.onrender.com/src/views/settings.html?verify_email=token123"
linked = mailer.send_verification_email("new@example.com", link)
body = (captured[0]["json"] if captured else {}) or {}
check("a 202 response counts as sent", linked is True, linked)
check("the confirmation link is in the HTML body", link in str(body.get("htmlContent", "")))
check("the confirmation link is in the text body", link in str(body.get("textContent", "")))
check("the email-change subject is unchanged",
      body.get("subject") == "Confirm your new email address - John Monash", body.get("subject"))

setattr(httpx, "post", real_post)
unconfigure()

# --- 5. Hygiene: no committed secrets, no SMTP, no Resend -----------------
resend_key = re.compile(r"re_[A-Za-z0-9_]{20,}")
brevo_key = re.compile(r"xkeysib-[A-Za-z0-9]{20,}")
sources = (
    list(SERVER.glob("*.py"))
    + list((SERVER / "routes").glob("*.py"))
    + list((REPO / "src").rglob("*.py"))
)


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def has_secret(path: pathlib.Path) -> bool:
    """Spot a committed key rather than a look-alike identifier.

    A Resend key is re_ followed by a long mixed-case alphanumeric run. Names
    such as re_leadership_membership match the character shape but are all
    lower-case, so they are excluded instead of reported as leaks.
    """
    text = read(path)
    if brevo_key.search(text):
        return True
    return any(
        re.search(r"[A-Z]", match.group(0)) and re.search(r"\d", match.group(0))
        for match in resend_key.finditer(text)
    )


leaks = [str(path.relative_to(REPO)) for path in sources if has_secret(path)]
check("no API key is committed in server/ or src/", not leaks, leaks)

resend_importers = [str(p.relative_to(REPO)) for p in sources
                    if re.search(r"^\s*(import|from)\s+resend", read(p), re.M)]
check("nothing imports the Resend SDK", not resend_importers, resend_importers)
check("the Resend module is deleted", not (SERVER / "email_service.py").exists())
check("resend is no longer a dependency",
      "resend" not in read(SERVER / "requirements.txt").lower())

mailer_source = read(SERVER / "mailer.py")
check("the mailer does not open an SMTP connection", "smtplib" not in mailer_source)
check("the mailer reads its key from the environment only",
      'os.getenv("BREVO_API_KEY"' in mailer_source)

render_config = read(REPO / "render.yaml")
check("render.yaml declares the Brevo settings",
      all(key in render_config for key in ("BREVO_API_KEY", "MAIL_FROM", "MAIL_FROM_NAME", "FRONTEND_URL")))
env_example = read(REPO / ".env.example")
check(".env.example documents the Brevo settings",
      "BREVO_API_KEY=" in env_example and "FRONTEND_URL=" in env_example)

passed = sum(results)
print(f"\n{passed}/{len(results)} checks passed")
if failures:
    print("failed: " + "; ".join(failures))
sys.exit(0 if passed == len(results) else 1)

