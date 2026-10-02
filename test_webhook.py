from sqlalchemy import func, select

from app.models import Payment, WebhookEvent
from tests.conftest import post_webhook


def pending_payment(client, user, booking):
    return client.post("/payments/", json={"booking_id": booking["id"], "simulate": "PENDING"}, headers=user).json()


def ev(ref, status="SUCCESS", event_id="evt_1", **kw):
    return {"event_id": event_id, "provider_reference": ref, "status": status, **kw}


def counts(client):
    with client.session_factory() as db:
        return db.scalar(select(func.count(Payment.id))), db.scalar(select(func.count(WebhookEvent.id)))


def test_success_webhook_confirms_booking(client, user, booking):
    p = pending_payment(client, user, booking)
    r = post_webhook(client, ev(p["provider_reference"]))
    assert r.status_code == 200
    assert r.json() == {"result": "applied", "payment_status": "SUCCESS", "booking_status": "CONFIRMED"}


def test_failed_webhook_fails_booking(client, user, booking):
    p = pending_payment(client, user, booking)
    r = post_webhook(client, ev(p["provider_reference"], "FAILED"))
    assert r.json()["booking_status"] == "FAILED"


def test_replayed_event_is_idempotent(client, user, booking):
    p = pending_payment(client, user, booking)
    first = post_webhook(client, ev(p["provider_reference"]))
    before = counts(client)
    for _ in range(5):
        r = post_webhook(client, ev(p["provider_reference"]))
        assert r.status_code == 200 and r.json()["result"] == "duplicate"
        assert r.json()["booking_status"] == "CONFIRMED"
    assert counts(client) == before  # no extra payments or ledger rows
    assert first.json()["result"] == "applied"
    assert len(client.get("/bookings/", headers=user).json()["items"]) == 1


def test_success_is_terminal_conflicting_later_event_ignored(client, user, booking):
    p = pending_payment(client, user, booking)
    post_webhook(client, ev(p["provider_reference"], "SUCCESS", "e1"))
    r = post_webhook(client, ev(p["provider_reference"], "FAILED", "e2"))  # new event id, contradictory
    assert r.json()["result"] == "ignored" and r.json()["booking_status"] == "CONFIRMED"


def test_out_of_order_late_success_after_failure(client, user, booking):
    p = pending_payment(client, user, booking)
    post_webhook(client, ev(p["provider_reference"], "FAILED", "e1"))
    r = post_webhook(client, ev(p["provider_reference"], "SUCCESS", "e2"))
    assert r.json()["result"] == "applied" and r.json()["booking_status"] == "CONFIRMED"


def test_webhook_for_cancelled_booking_does_not_resurrect_it(client, user, booking):
    p = pending_payment(client, user, booking)
    client.post(f"/bookings/{booking['id']}/cancel", headers=user)
    post_webhook(client, ev(p["provider_reference"]))
    assert client.get(f"/bookings/{booking['id']}", headers=user).json()["status"] == "CANCELLED"


def test_signature_required_and_checked(client, user, booking):
    p = pending_payment(client, user, booking)
    assert post_webhook(client, ev(p["provider_reference"]), signature=None).status_code == 401
    assert post_webhook(client, ev(p["provider_reference"]), signature="deadbeef").status_code == 401
    assert counts(client)[1] == 0


def test_invalid_payloads(client, user, booking):
    p = pending_payment(client, user, booking)
    ref = p["provider_reference"]
    assert post_webhook(client, ev("pay_unknown")).status_code == 404
    assert post_webhook(client, ev(ref, "REFUNDED")).status_code == 422
    assert post_webhook(client, {"status": "SUCCESS"}).status_code == 422
    assert post_webhook(client, ev(ref, amount="1.00")).status_code == 422  # amount mismatch
    assert counts(client)[1] == 0  # rejected events leave no ledger row, so provider retries still work
    assert post_webhook(client, ev(ref, amount="500.00")).json()["result"] == "applied"
