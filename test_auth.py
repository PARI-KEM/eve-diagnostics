from tests.conftest import signup_login


def test_signup_login_me(client):
    h = signup_login(client)
    r = client.get("/auth/me", headers=h)
    assert r.status_code == 200 and r.json()["email"] == "user@example.com" and not r.json()["is_admin"]


def test_signup_response_never_leaks_password(client):
    r = client.post("/auth/signup", json={"email": "a@b.com", "full_name": "A", "password": "password123"})
    assert r.status_code == 201 and "password" not in r.text


def test_duplicate_email_case_insensitive(client):
    body = {"full_name": "A", "password": "password123"}
    assert client.post("/auth/signup", json={"email": "a@b.com", **body}).status_code == 201
    assert client.post("/auth/signup", json={"email": "A@B.com", **body}).status_code == 409


def test_validation(client):
    assert client.post("/auth/signup", json={"email": "nope", "full_name": "A", "password": "password123"}).status_code == 422
    assert client.post("/auth/signup", json={"email": "a@b.com", "full_name": "A", "password": "short"}).status_code == 422


def test_bad_credentials(client, user):
    assert client.post("/auth/login", json={"email": "user@example.com", "password": "wrongwrong"}).status_code == 401
    assert client.post("/auth/login", json={"email": "ghost@example.com", "password": "password123"}).status_code == 401


def test_protected_routes_need_valid_token(client):
    assert client.get("/bookings/").status_code == 401
    assert client.get("/bookings/", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_rate_limit_on_auth(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "rate_limit_per_minute", 3)
    codes = [client.post("/auth/login", json={"email": "a@b.com", "password": "password123"}).status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401] and codes[3:] == [429, 429]
