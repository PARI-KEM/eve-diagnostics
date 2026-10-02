def pay(client, headers, booking_id, simulate=None):
    body = {"booking_id": booking_id, **({"simulate": simulate} if simulate else {})}
    return client.post("/payments/", json=body, headers=headers)


def test_success_confirms_booking(client, user, booking):
    r = pay(client, user, booking["id"], "SUCCESS")
    assert r.status_code == 201
    assert r.json()["status"] == "SUCCESS" and r.json()["booking_status"] == "CONFIRMED" and r.json()["amount"] == "500.00"
    assert client.get(f"/bookings/{booking['id']}", headers=user).json()["status"] == "CONFIRMED"


def test_failure_marks_booking_failed_then_retry_succeeds(client, user, booking):
    assert pay(client, user, booking["id"], "FAILED").json()["booking_status"] == "FAILED"
    r = pay(client, user, booking["id"], "SUCCESS")
    assert r.status_code == 201 and r.json()["booking_status"] == "CONFIRMED"


def test_random_outcome_is_valid(client, user, booking):
    assert pay(client, user, booking["id"]).json()["status"] in ("SUCCESS", "FAILED")


def test_cannot_pay_twice_or_for_cancelled(client, user, booking):
    pay(client, user, booking["id"], "SUCCESS")
    assert pay(client, user, booking["id"], "SUCCESS").status_code == 409
    other_b = client.post("/bookings/", json={k: booking[k] for k in ("centre_id", "test_id", "appointment_at")}, headers=user).json()
    client.post(f"/bookings/{other_b['id']}/cancel", headers=user)
    assert pay(client, user, other_b["id"], "SUCCESS").status_code == 409


def test_authorization_and_validation(client, user, other, booking):
    assert pay(client, other, booking["id"], "SUCCESS").status_code == 404
    assert client.post("/payments/", json={"booking_id": booking["id"]}).status_code == 401
    assert pay(client, user, 99999, "SUCCESS").status_code == 404
    assert client.post("/payments/", json={"booking_id": "x"}, headers=user).status_code == 422
    assert client.post("/payments/", json={"booking_id": booking["id"], "simulate": "MAYBE"}, headers=user).status_code == 422


def test_idempotency_key_replays_same_payment(client, user, booking):
    h = {"Idempotency-Key": "abc-1"}
    a = pay(client, {**user, **h}, booking["id"], "FAILED")
    b = pay(client, {**user, **h}, booking["id"], "SUCCESS")  # replay must NOT re-run / flip outcome
    assert a.json()["id"] == b.json()["id"] and b.json()["status"] == "FAILED"


def test_pending_payment_blocks_a_second_attempt(client, user, booking):
    assert pay(client, user, booking["id"], "PENDING").json()["status"] == "PENDING"
    assert pay(client, user, booking["id"], "SUCCESS").status_code == 409
