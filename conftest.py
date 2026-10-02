import json
import os
from datetime import datetime, timedelta, timezone

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["RATE_LIMIT_PER_MINUTE"] = "0"
os.environ["BCRYPT_ROUNDS"] = "4"
os.environ["JWT_SECRET"] = "test-secret-key-at-least-32-bytes-long!!"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import rate_limit
from app.database import Base, get_db
from app.main import app
from app.security import sign_webhook


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    rate_limit.reset()
    with TestClient(app) as c:
        c.session_factory = Session
        yield c
    app.dependency_overrides.clear()


def signup_login(client, email="user@example.com", password="password123"):
    client.post("/auth/signup", json={"email": email, "full_name": "Test User", "password": password})
    token = client.post("/auth/login", json={"email": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin(client):
    return signup_login(client, "admin@example.com")


@pytest.fixture()
def user(client):
    return signup_login(client)


@pytest.fixture()
def other(client):
    return signup_login(client, "other@example.com")


@pytest.fixture()
def catalog(client, admin):
    """One centre offering one test at 500.00. Returns (centre_id, test_id)."""
    t = client.post("/tests/", json={"name": "Lipid Profile"}, headers=admin).json()
    c = client.post("/centres/", json={"name": "EVE Saket", "location": "Delhi"}, headers=admin).json()
    r = client.post(f"/centres/{c['id']}/tests", json={"test_id": t["id"], "price": "500.00"}, headers=admin)
    assert r.status_code == 201
    return c["id"], t["id"]


def future(days=3) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


@pytest.fixture()
def booking(client, user, catalog):
    centre_id, test_id = catalog
    r = client.post("/bookings/", json={"centre_id": centre_id, "test_id": test_id, "appointment_at": future()}, headers=user)
    assert r.status_code == 201, r.text
    return r.json()


def post_webhook(client, payload: dict, signature: str | None = "auto"):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signature == "auto":
        headers["X-Webhook-Signature"] = sign_webhook(body)
    elif signature:
        headers["X-Webhook-Signature"] = signature
    return client.post("/payments/webhook/", content=body, headers=headers)
