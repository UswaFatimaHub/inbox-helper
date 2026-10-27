"""Google sign-in with a fake token exchange: no network. The reviewer on every action is the signed-in user."""
import time
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from inbox_helper.api import create_app
from inbox_helper.auth import AuthConfig, AuthConfigError, parse_allowed
from inbox_helper.worker import Worker

from test_api import fake_lanes

CONFIG = AuthConfig("google", client_id="client-123", client_secret="s3cret",
                    allowed=parse_allowed("amna@brightpath.example, @recruiting.example"),
                    session_secret="test-session-secret", public_url="http://testserver")


class FakeGoogle:
    """Stands in for Google's token endpoint; returns whatever claims the test sets."""

    def __init__(self):
        self.claims: dict = {}

    def __call__(self, config, code):
        return dict(self.claims)


def make_client(db, config=CONFIG, google=None):
    app = create_app(db, lanes_factory=fake_lanes, use_cache=False, embedded_worker=False, auth=config,
                     exchange_code=google or FakeGoogle())
    return TestClient(app)


def sign_in(client, google, email, **overrides):
    r = client.get("/api/auth/google/login", follow_redirects=False)
    query = parse_qs(urlparse(r.headers["location"]).query)
    google.claims = {"iss": "https://accounts.google.com", "aud": CONFIG.client_id, "exp": time.time() + 300,
                     "nonce": query["nonce"][0], "email": email, "email_verified": True, "name": "Amna R",
                     **overrides}
    return client.get(f"/api/auth/google/callback?code=abc&state={query['state'][0]}", follow_redirects=False)


@pytest.fixture
def google():
    return FakeGoogle()


@pytest.fixture
def client(db, google):
    with make_client(db, google=google) as c:
        yield c


def test_api_needs_a_signed_in_user_but_health_does_not(client):
    assert client.get("/api/runs").status_code == 401
    assert client.post("/api/runs/sample").status_code == 401
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/auth/config").json() == {"mode": "google"}


def test_login_redirects_to_google_with_state_and_nonce(client):
    r = client.get("/api/auth/google/login", follow_redirects=False)
    url = urlparse(r.headers["location"])
    q = parse_qs(url.query)
    assert url.netloc == "accounts.google.com"
    assert q["client_id"] == ["client-123"] and q["redirect_uri"] == ["http://testserver/api/auth/google/callback"]
    assert q["scope"] == ["openid email profile"] and q["state"][0] and q["nonce"][0]


def test_signed_in_user_is_the_reviewer(db, client, google):
    r = sign_in(client, google, "Amna@Brightpath.example")
    assert r.status_code == 307 and r.headers["location"] == "/"
    assert client.get("/api/me").json() == {"email": "amna@brightpath.example", "name": "Amna R", "mode": "google"}

    run_id = client.post("/api/runs/sample").json()["id"]
    Worker(db, fake_lanes, cache_path=None, log=lambda _: None).run_once()
    item = client.get(f"/api/runs/{run_id}/items").json()[0]
    # a reviewer name sent by the browser is ignored
    r = client.post(f"/api/items/{item['id']}/review",
                    json={"action": "approve", "text": "Hello", "reviewer": "Someone Else"}).json()
    assert r["reviewed_by"] == "amna@brightpath.example"
    assert r["events"][-1]["reviewer"] == "amna@brightpath.example"


def test_whole_domain_can_be_allowed(client, google):
    assert sign_in(client, google, "zara@recruiting.example").status_code == 307
    assert client.get("/api/me").status_code == 200


def test_email_not_on_the_list_is_refused(client, google):
    r = sign_in(client, google, "intruder@gmail.example")
    assert r.status_code == 403 and "intruder@gmail.example" in r.text
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize("bad", [
    {"aud": "someone-elses-client"}, {"iss": "https://evil.example"}, {"email_verified": False},
    {"exp": time.time() - 10}, {"nonce": "replayed"},
])
def test_unverifiable_google_answers_are_refused(client, google, bad):
    assert sign_in(client, google, "amna@brightpath.example", **bad).status_code == 400
    assert client.get("/api/me").status_code == 401


def test_callback_without_a_matching_login_is_refused(client, google):
    assert client.get("/api/auth/google/callback?code=abc&state=forged").status_code == 400
    r = client.get("/api/auth/google/login", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    client.get(f"/api/auth/google/callback?code=abc&state=wrong-{state}")
    # the pending login was used up by the failed attempt: the right state no longer works either
    assert client.get(f"/api/auth/google/callback?code=abc&state={state}").status_code == 400


def test_removing_someone_from_the_list_signs_them_out(db, client, google):
    sign_in(client, google, "amna@brightpath.example")
    narrower = replace(CONFIG, allowed=parse_allowed("@recruiting.example"))
    with make_client(db, narrower) as other:
        other.cookies = client.cookies  # same signed session cookie, new allowed list
        assert other.get("/api/me").status_code == 401


def test_logout(client, google):
    sign_in(client, google, "amna@brightpath.example")
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/me").status_code == 401


def test_session_cookie_is_secure_and_http_only_on_https(db, google):
    with make_client(db, replace(CONFIG, public_url="https://inbox.example"), google) as c:
        r = c.get("/api/auth/google/login", follow_redirects=False)
    cookie = r.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie


def test_google_mode_refuses_to_start_half_configured(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "google")
    for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "ALLOWED_EMAILS", "SESSION_SECRET", "PUBLIC_URL",
                "RENDER_EXTERNAL_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "x")
    with pytest.raises(AuthConfigError, match="GOOGLE_CLIENT_SECRET, ALLOWED_EMAILS, SESSION_SECRET, PUBLIC_URL"):
        AuthConfig.from_env()
    for var, value in (("GOOGLE_CLIENT_SECRET", "y"), ("ALLOWED_EMAILS", "a@b.example"), ("SESSION_SECRET", "z"),
                       ("RENDER_EXTERNAL_URL", "https://inbox-helper.onrender.com")):
        monkeypatch.setenv(var, value)
    config = AuthConfig.from_env()  # Render's own URL variable is enough
    assert config.redirect_uri == "https://inbox-helper.onrender.com/api/auth/google/callback"
    assert config.secure_cookies
    monkeypatch.setenv("AUTH_MODE", "off")
    with pytest.raises(AuthConfigError, match="AUTH_MODE"):
        AuthConfig.from_env()


def test_dev_mode_acts_as_the_configured_user(db):
    with TestClient(create_app(db, lanes_factory=fake_lanes, embedded_worker=False)) as c:
        assert c.get("/api/me").json() == {"email": "uswa@example.com", "name": "Local reviewer", "mode": "dev"}
