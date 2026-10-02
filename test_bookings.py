from tests.conftest import future


def test_create_uses_server_price_and_starts_pending(client, booking):
    assert booking["status"] == "PENDING" and booking["amount"] == "500.00"


def test_client_cannot_set_amount_or_status(client, user, catalog):
    c, t = catalog
    r = client.post("/bookings/", json={"centre_id": c, "test_id": t, "appointment_at": future(),
                                        "amount": "1.00", "status": "CONFIRMED"}, headers=user)
    assert r.json()["amount"] == "500.00" and r.json()["status"] == "PENDING"


def test_validation_errors(client, user, catalog):
    c, t = catalog
    ok = {"centre_id": c, "test_id": t, "appointment_at": future()}
    assert client.post("/bookings/", json={**ok, "appointment_at": future(-1)}, headers=user).status_code == 422
    assert client.post("/bookings/", json={**ok, "appointment_at": "2099-01-01T10:00:00"}, headers=user).status_code == 422  # naive
    assert client.post("/bookings/", json={**ok, "appointment_at": "garbage"}, headers=user).status_code == 422
    assert client.post("/bookings/", json={**ok, "test_id": 999}, headers=user).status_code == 422
    assert client.post("/bookings/", json={**ok, "centre_id": 999}, headers=user).status_code == 422
    assert client.post("/bookings/", json=ok).status_code == 401


def test_owner_isolation(client, booking, other):
    bid = booking["id"]
    assert client.get(f"/bookings/{bid}", headers=other).status_code == 404
    assert client.post(f"/bookings/{bid}/cancel", headers=other).status_code == 404
    assert client.get("/bookings/", headers=other).json()["total"] == 0


def test_invalid_booking_ids(client, user):
    assert client.get("/bookings/99999", headers=user).status_code == 404
    assert client.get("/bookings/abc", headers=user).status_code == 422


def test_list_filter_and_cancel(client, user, booking):
    assert client.get("/bookings/", headers=user).json()["total"] == 1
    r = client.post(f"/bookings/{booking['id']}/cancel", headers=user)
    assert r.json()["status"] == "CANCELLED"
    assert client.post(f"/bookings/{booking['id']}/cancel", headers=user).status_code == 200  # idempotent
    assert client.get("/bookings/", params={"status": "CANCELLED"}, headers=user).json()["total"] == 1
    assert client.get("/bookings/", params={"status": "PENDING"}, headers=user).json()["total"] == 0
    assert client.get("/bookings/", params={"status": "BOGUS"}, headers=user).status_code == 422
