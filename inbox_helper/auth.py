"""Sign-in: Google OpenID Connect plus an allowed-email list. The reviewer recorded on every action is the
signed-in user, so nobody can approve a reply in someone else's name.

AUTH_MODE=google (the default) needs:
  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET   OAuth client (type "Web application") from Google Cloud
  ALLOWED_EMAILS                           comma-separated; an entry like "@company.com" allows the whole domain
  SESSION_SECRET                           long random string that signs the session cookie
  PUBLIC_URL                               e.g. https://inbox-helper.onrender.com (Render sets RENDER_EXTERNAL_URL,
                                           which is used when PUBLIC_URL is not set)
The app refuses to start when any of these is missing, so a deploy cannot come up without a login by accident.

AUTH_MODE=dev skips the login for local work: every request acts as DEV_USER_EMAIL (default reviewer@localhost).

Every /api route needs a signed-in user except /api/health and /api/auth/*. Routes added later are protected
unless they are deliberately added to PUBLIC_PATHS.
"""
import base64
import html
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
CALLBACK_PATH = "/api/auth/google/callback"
PUBLIC_PATHS = ("/api/health", "/api/auth/")
SESSION_MAX_AGE_S = 8 * 3600  # a working day; then sign in again


class AuthConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class User:
    email: str
    name: str


@dataclass(frozen=True)
class AuthConfig:
    mode: str  # "google" | "dev"
    client_id: str = ""
    client_secret: str = ""
    allowed: frozenset[str] = frozenset()  # lower-cased emails, or "@domain" entries
    session_secret: str = field(default="", repr=False)
    public_url: str = ""
    dev_user: User = User("reviewer@localhost", "Local reviewer")

    @classmethod
    def from_env(cls) -> "AuthConfig":
        mode = os.environ.get("AUTH_MODE", "google").strip().lower()
        if mode == "dev":
            email = os.environ.get("DEV_USER_EMAIL", "reviewer@localhost").strip()
            return cls("dev", dev_user=User(email, os.environ.get("DEV_USER_NAME", "Local reviewer").strip()),
                       session_secret=os.environ.get("SESSION_SECRET") or secrets.token_urlsafe(32))
        if mode != "google":
            raise AuthConfigError(f"AUTH_MODE must be 'google' or 'dev', not {mode!r}")
        env = {k: os.environ.get(k, "").strip() for k in
               ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "ALLOWED_EMAILS", "SESSION_SECRET")}
        env["PUBLIC_URL"] = (os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")).strip()
        if missing := [k for k, v in env.items() if not v]:
            raise AuthConfigError(f"Sign-in is not configured: set {', '.join(missing)} "
                                  f"(or AUTH_MODE=dev for local use without a login).")
        return cls("google", env["GOOGLE_CLIENT_ID"], env["GOOGLE_CLIENT_SECRET"],
                   parse_allowed(env["ALLOWED_EMAILS"]), env["SESSION_SECRET"], env["PUBLIC_URL"].rstrip("/"))

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def redirect_uri(self) -> str:
        return self.public_url + CALLBACK_PATH

    def allows(self, email: str) -> bool:
        email = email.strip().lower()
        return email in self.allowed or ("@" + email.rpartition("@")[2]) in self.allowed


def parse_allowed(value: str) -> frozenset[str]:
    return frozenset(e.strip().lower() for e in value.split(",") if e.strip())


def decode_id_token(id_token: str) -> dict:
    """Claims of an ID token received straight from Google's token endpoint. OpenID Connect Core 3.1.3.7 allows
    relying on TLS instead of the signature for a token obtained that way; the claims are still checked."""
    payload = id_token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def exchange_code_with_google(config: AuthConfig, code: str) -> dict:
    r = requests.post(GOOGLE_TOKEN_URL, timeout=10, data={
        "code": code, "client_id": config.client_id, "client_secret": config.client_secret,
        "redirect_uri": config.redirect_uri, "grant_type": "authorization_code"})
    if r.status_code != 200:
        raise HTTPException(400, f"Google sign-in failed ({r.status_code}). Try again.")
    return decode_id_token(r.json()["id_token"])


def current_user(request: Request, config: AuthConfig) -> User | None:
    if config.mode == "dev":
        return config.dev_user
    data = request.session.get("user")
    if not data or not config.allows(data.get("email", "")):  # removed from the list: out on the next request
        return None
    return User(data["email"], data.get("name") or data["email"])


def is_public(path: str) -> bool:
    return not path.startswith("/api/") or any(path == p or path.startswith(p) for p in PUBLIC_PATHS)


def message_page(title: str, text: str, status: int) -> HTMLResponse:
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>{title}</title>"
                        f"<body style='font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem'>"
                        f"<h1 style='font-size:1.25rem'>{title}</h1><p>{html.escape(text)}</p><p><a href='/'>Back</a></p>",
                        status_code=status)


def auth_router(config: AuthConfig,
                exchange_code: Callable[[AuthConfig, str], dict] = exchange_code_with_google) -> APIRouter:
    router = APIRouter()

    @router.get("/api/auth/config")
    def auth_config():
        return {"mode": config.mode}

    @router.get("/api/auth/google/login")
    def login(request: Request):
        if config.mode != "google":
            return RedirectResponse("/")
        state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        request.session["oauth"] = {"state": state, "nonce": nonce, "at": int(time.time())}
        return RedirectResponse(GOOGLE_AUTH_URL + "?" + urlencode({
            "client_id": config.client_id, "redirect_uri": config.redirect_uri, "response_type": "code",
            "scope": "openid email profile", "state": state, "nonce": nonce, "prompt": "select_account"}))

    @router.get(CALLBACK_PATH)
    def callback(request: Request, code: str = "", state: str = "", error: str = ""):
        pending = request.session.pop("oauth", None)
        if error:
            return message_page("Sign-in cancelled", "Google did not sign you in. Go back and try again.", 400)
        if not pending or not code or not secrets.compare_digest(state, pending["state"]) \
                or time.time() - pending["at"] > 600:
            return message_page("Sign-in expired", "The sign-in link was stale or already used. Start again.", 400)
        claims = exchange_code(config, code)
        if (claims.get("iss") not in GOOGLE_ISSUERS or claims.get("aud") != config.client_id
                or claims.get("exp", 0) < time.time() or claims.get("nonce") != pending["nonce"]
                or claims.get("email_verified") is not True or not claims.get("email")):
            return message_page("Sign-in failed", "Google's answer could not be verified. Start again.", 400)
        email = claims["email"].lower()
        if not config.allows(email):
            return message_page("Not allowed", f"{email} is not on this tool's list of reviewers. Ask the owner to add "
                                        f"it, or sign in with another account.", 403)
        request.session.clear()
        request.session["user"] = {"email": email, "name": claims.get("name") or email}
        return RedirectResponse("/")

    @router.post("/api/auth/logout", status_code=204)
    def logout(request: Request):
        request.session.clear()
        return Response(status_code=204)

    return router


def require_login(config: AuthConfig):
    """HTTP middleware: 401 for protected API paths without a signed-in, allowed user."""
    async def middleware(request: Request, call_next):
        if not is_public(request.url.path):
            user = current_user(request, config)
            if user is None:
                return JSONResponse({"detail": "Sign in to continue."}, status_code=401)
            request.state.user = user
        return await call_next(request)
    return middleware
