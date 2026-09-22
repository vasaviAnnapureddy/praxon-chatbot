"""
Admin login: password hashing and session tokens.

Why PBKDF2 from the standard library instead of bcrypt/passlib:
  * zero extra dependencies and zero compiled wheels — matters on a 512 MB box
  * 390,000 SHA-256 iterations is the current OWASP recommendation
  * this protects ONE founder account, not a user database
If Praxon ever adds many admin users, moving to bcrypt is a one-file change.

Sessions are stateless JWTs so the app keeps nothing on disk (Render wipes disk)
and nothing in memory (Render restarts whenever it likes).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

import jwt

from app.config import settings
from app.core.timezone import utc_now

_ITERATIONS = 390_000
_ALGO = "HS256"


# --------------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    """Returns 'pbkdf2_sha256$iterations$salt$hash' — one string for one column."""
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return "$".join(
        [
            "pbkdf2_sha256",
            str(_ITERATIONS),
            base64.b64encode(salt).decode(),
            base64.b64encode(dk).decode(),
        ]
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, b64salt, b64hash = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), base64.b64decode(b64salt), int(iterations)
        )
        # compare_digest, not ==, so the comparison time tells an attacker nothing.
        return hmac.compare_digest(dk, base64.b64decode(b64hash))
    except Exception:
        return False


def password_strength_problem(password: str) -> str | None:
    """Issue #14: the dashboard is on a public URL. Weak passwords are refused."""
    if len(password) < 12:
        return "Password must be at least 12 characters."
    if password.lower() in {"password1234", "admin1234567", "praxon123456"}:
        return "That password is too predictable."
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(not c.isalnum() for c in password),
        ]
    )
    if classes < 3:
        return "Use at least three of: lowercase, uppercase, digits, symbols."
    return None


# Short, common words: easy to read out or type from a WhatsApp message.
_WORDS = (
    "kite moon rain river stone cloud tiger mango lotus pearl amber cedar coral delta eagle "
    "flame grape honey ivory jade lemon maple night ocean piano quartz rose sand tulip "
    "violet wave zebra apple bridge candle dune ember forest garden harbor island jungle "
    "lantern meadow nectar orbit palm quill ridge silver thunder valley willow yarn comet "
    "falcon glacier hazel indigo koala lilac marble nova olive pepper raven saffron topaz"
).split()


def generate_temporary_password() -> str:
    """
    A one-time password like "Kite-Ocean-4821-Lotus" for a new account.

      Q: Why words, not random letters like "xK9#pQ2m"?
      A: It is sent on WhatsApp and typed on a phone. Words are hard to mistype
         and still strong: 80 words x 3 x 4 digits is ~5 billion combinations,
         and sign-in allows only 8 tries per 15 minutes.
    """
    w = [secrets.choice(_WORDS).capitalize() for _ in range(3)]
    return f"{w[0]}-{w[1]}-{secrets.randbelow(9000) + 1000}-{w[2]}"


# ----------------------------------------------------------------------- tokens
ROLES = {"owner", "team", "client"}


def create_access_token(user_id: int, role: str, *, scope: str = "session") -> str:
    """
    The signed "pass" handed to the browser after login: who you are + your role.

      scope "session" -> the normal pass, 12 hours, opens the pages for your role
      scope "setup"   -> after signing in with a TEMPORARY password: 30 minutes,
                         and it opens ONE thing only — "choose your own password"
    """
    now = utc_now()
    life = timedelta(minutes=30) if scope == "setup" else timedelta(hours=settings.ADMIN_SESSION_HOURS)
    payload = {
        "sub": str(user_id),                 # JWT standard: "subject" is a string
        "role": role,                        # owner | team | client
        "iat": int(now.timestamp()),         # issued at
        "exp": int((now + life).timestamp()),
        "scope": scope,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=_ALGO)


def decode_access_token(token: str) -> dict | None:
    """
    Returns {"uid": 7, "role": "team", "scope": "session"} — or None if the pass
    is missing, forged, expired, or from the old username-only format.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[_ALGO])
    except jwt.PyJWTError:
        return None
    if payload.get("scope") not in {"session", "setup"} or payload.get("role") not in ROLES:
        return None
    try:
        return {"uid": int(payload["sub"]), "role": payload["role"], "scope": payload["scope"]}
    except (KeyError, ValueError):
        return None


# ------------------------------------------------------------------ Google
class GoogleAuthError(Exception):
    pass


async def verify_google_credential(credential: str) -> dict:
    """
    Checks a "Continue with Google" result is genuine, and returns who it is.

      Q: Can't we just trust the email the browser sends us?
      A: Never. Anyone can send any email. Google instead gives the browser a
         signed token; this checks Google's signature, that it was issued FOR
         OUR app (GOOGLE_CLIENT_ID), that it has not expired, and that Google
         itself has verified the email. Only then do we believe it.

    Returns {"email": "a@gmail.com", "sub": "1098...", "name": "Anita"}.
    """
    if not settings.GOOGLE_CLIENT_ID:
        raise GoogleAuthError("Google sign-in is not set up on this server")

    import asyncio

    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    def _verify() -> dict:
        # Sync library call (it fetches Google's public keys, then caches them),
        # so it runs in a worker thread instead of blocking other visitors.
        return id_token.verify_oauth2_token(
            credential, google_requests.Request(), settings.GOOGLE_CLIENT_ID
        )

    try:
        info = await asyncio.to_thread(_verify)
    except ValueError as exc:                       # bad signature, wrong app, expired
        raise GoogleAuthError(f"Google sign-in could not be verified: {exc}") from exc

    if not info.get("email") or not info.get("email_verified"):
        raise GoogleAuthError("This Google account has no verified email")
    return {
        "email": str(info["email"]).strip().lower(),
        "sub": str(info.get("sub", "")),
        "name": str(info.get("name", "")),
    }


def security_headers() -> dict[str, str]:
    """
    Issue #14 again. Applied to every response in main.py.

    frame-ancestors is intentionally permissive for the demo (the widget has to
    be embeddable on a client's site). Tighten it by setting
    ALLOWED_EMBED_ORIGINS once the real domains are known.
    """
    allowed = settings.ALLOWED_EMBED_ORIGINS.strip()
    frame_ancestors = "*" if allowed == "*" else " ".join(
        o.strip() for o in allowed.split(",") if o.strip()
    )
    # No X-Frame-Options here on purpose: it cannot express "allow these two
    # domains", only "allow one" or "allow none", and CSP frame-ancestors
    # supersedes it in every browser that matters. Setting both would just mean
    # two places to get embedding rules wrong.
    return {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Content-Security-Policy": f"frame-ancestors {frame_ancestors};",
        "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    }
