# EVE Diagnostics Booking API

Backend for diagnostic-test bookings with a **simulated payment service** and an **idempotent payment webhook**.
Built for the EVE Healthcare SDE Intern assignment.

**Stack:** Python 3.12+, FastAPI, SQLAlchemy 2.0, PostgreSQL (SQLite for tests/quick local run), JWT (PyJWT), bcrypt, pytest, Docker.

## Run it

### Docker (Postgres, recommended)
```bash
docker compose up --build
docker compose exec api python seed.py      # optional demo centres/tests
```
API: http://localhost:8000 · Swagger UI: http://localhost:8000/docs · ReDoc: `/redoc`

### Local (no Docker)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # set DATABASE_URL=sqlite:///./eve.db for zero-setup, or point at your Postgres
python seed.py           # optional
uvicorn app.main:app --reload
```

### Tests
```bash
pytest -q      # 34 tests, in-memory SQLite, ~4s
```

### Config (env vars, see `.env.example`)
| Var | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL (default `sqlite:///./eve.db`) |
| `JWT_SECRET`, `JWT_EXPIRE_MINUTES` | Token signing key / lifetime |
| `WEBHOOK_SECRET` | HMAC key shared with the payment provider |
| `ADMIN_EMAILS` | Comma-separated; signing up with one of these emails creates an admin |
| `PAYMENT_SUCCESS_RATE` | Chance the simulator returns SUCCESS (default 0.8) |
| `RATE_LIMIT_PER_MINUTE` | Per-IP limit on signup/login; `0` disables |
| `BCRYPT_ROUNDS` | bcrypt cost (default 12; tests use 4) |

## Endpoints

| Method & path | Auth | Description |
|---|---|---|
| `POST /auth/signup` | – | Create user (email, full_name, password ≥ 8 chars) |
| `POST /auth/login` | – | Returns `{access_token}` |
| `GET /auth/me` | JWT | Current user |
| `POST /tests/` · `GET /tests/` | admin · JWT | Test catalogue (e.g. "Lipid Profile") |
| `POST /centres/` | admin | Create centre (name, location) |
| `GET /centres/` | – | List; filters `location`, `test`; `limit`/`offset` |
| `GET /centres/{id}` | – | Centre with its tests and prices |
| `POST /centres/{id}/tests` · `PUT /centres/{id}/tests/{test_id}` | admin | Offer a test at a price / change price |
| `POST /bookings/` | JWT | Book (centre_id, test_id, appointment_at) |
| `GET /bookings/` · `GET /bookings/{id}` | JWT | Own bookings only; `status`, pagination |
| `POST /bookings/{id}/cancel` | JWT | Cancel own booking (idempotent) |
| `POST /payments/` | JWT | Simulated payment; optional `Idempotency-Key` header |
| `POST /payments/webhook/` | HMAC signature | Provider status callback (idempotent) |
| `GET /health` | – | Liveness |

### Example requests
```bash
B=http://localhost:8000

# 1. signup + login
curl -X POST $B/auth/signup -H 'content-type: application/json' \
  -d '{"email":"asha@example.com","full_name":"Asha","password":"password123"}'
TOKEN=$(curl -s -X POST $B/auth/login -H 'content-type: application/json' \
  -d '{"email":"asha@example.com","password":"password123"}' | jq -r .access_token)

# 2. browse centres
curl "$B/centres/?location=delhi&test=lipid"

# 3. book (amount comes from the centre's price, never from the client)
curl -X POST $B/bookings/ -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"centre_id":1,"test_id":1,"appointment_at":"2026-12-01T10:00:00+05:30"}'
# -> {"id":1,"amount":"350.00","status":"PENDING",...}

# 4. pay (simulated). Random SUCCESS/FAILED, or force with "simulate": "SUCCESS" | "FAILED" | "PENDING"
curl -X POST $B/payments/ -H "Authorization: Bearer $TOKEN" -H 'Idempotency-Key: order-123' \
  -H 'content-type: application/json' -d '{"booking_id":1}'
# -> {"status":"SUCCESS","booking_status":"CONFIRMED","provider_reference":"pay_...",...}

# 5. webhook (what the provider would send). Signature = hex HMAC-SHA256(WEBHOOK_SECRET, raw body)
BODY='{"event_id":"evt_1","provider_reference":"pay_...","status":"SUCCESS"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | awk '{print $NF}')
curl -X POST $B/payments/webhook/ -H "X-Webhook-Signature: $SIG" -H 'content-type: application/json' -d "$BODY"
# first call  -> {"result":"applied","payment_status":"SUCCESS","booking_status":"CONFIRMED"}
# replay      -> {"result":"duplicate", ...same state...}
```
To create centres, sign up with an email listed in `ADMIN_EMAILS` and use its token on the admin endpoints (or run `seed.py`).
To see the webhook settle a payment, create it with `"simulate": "PENDING"`, then send the webhook for its `provider_reference`.

## Design

### Layout
```
app/
  main.py            app, request-id + access-log middleware, error fallback
  config.py          env settings            security.py   bcrypt, JWT, webhook HMAC
  models.py          SQLAlchemy models       schemas.py    Pydantic request/response models
  deps.py            auth dependencies       rate_limit.py in-memory limiter
  routers/           thin HTTP layer: auth, catalog, bookings, payments
  services/payments.py   payment/booking state machine + webhook processing (all the tricky logic)
tests/               pytest, one file per area
```
Routers handle HTTP and validation; the only non-trivial business logic lives in `services/payments.py` so it can be reasoned about (and changed) in one place.

### Schema
```
users(id, email UNIQUE, full_name, password_hash, is_admin, created_at)
centres(id, name, location IDX, UNIQUE(name, location))
diagnostic_tests(id, name UNIQUE, description)
centre_tests(id, centre_id FK, test_id FK, price NUMERIC(10,2), UNIQUE(centre_id, test_id))   -- which centre offers what, at what price
bookings(id, user_id FK, centre_id FK, test_id FK, appointment_at tz, amount NUMERIC(10,2), status, IDX(user_id,status))
payments(id, booking_id FK IDX, user_id FK, amount, status, provider_reference UNIQUE,
         idempotency_key, UNIQUE(user_id, idempotency_key))
webhook_events(id, event_id UNIQUE, provider_reference, status, outcome, payload JSON, received_at)
```
Key choices:
- **`centre_tests`** is the many-to-many between centres and tests with price as payload, so prices are per centre.
- **`bookings.amount` is a snapshot** of the price at booking time; later price edits don't change existing bookings (tested).
- **Money is `NUMERIC`/`Decimal`**, never float.
- **`payments` is separate from `bookings`**: a booking can have several attempts (failed, then retry). Webhooks target a payment via `provider_reference`.
- **`webhook_events` is the idempotency ledger**; `UNIQUE(event_id)` is enforced by the database, so it holds under concurrent deliveries.

### State machine
```
Payment:  PENDING -> SUCCESS | FAILED          FAILED -> SUCCESS (late/out-of-order success)         SUCCESS is terminal
Booking:  PENDING -> CONFIRMED (payment SUCCESS) | FAILED (payment FAILED) | CANCELLED
          FAILED  -> CONFIRMED (successful retry) | CANCELLED
          CONFIRMED / CANCELLED: new payments rejected with 409
```
Every transition goes through one function (`apply_payment_status`), used by both `POST /payments/` and the webhook.

### Webhook idempotency & safety
1. **Authenticity:** HMAC-SHA256 of the raw body in `X-Webhook-Signature` (constant-time compare), 401 otherwise. Webhooks are server-to-server, so JWT doesn't apply.
2. **Idempotency:** the ledger row insert and the state change are **one DB transaction**. A replayed `event_id` violates the unique constraint, is caught, and returns `200 {"result":"duplicate"}` with no side effects. Returning 200 (not 4xx) stops provider retries.
3. **Retry-safe:** if processing fails midway, the transaction rolls back *including* the ledger row, so the provider's retry is processed normally. Unknown payment reference → 404 and nothing recorded, so a retry works once the payment exists.
4. **Different event ids, conflicting content** (e.g. `FAILED` arriving after `SUCCESS`) can't corrupt state: illegal transitions are recorded as `ignored`.
5. Rows are locked (`SELECT ... FOR UPDATE`) while payment/booking change, so concurrent webhooks/payments serialise on Postgres.

### Edge cases handled
Invalid/malformed bodies (422) · unknown booking/centre/test (404/422) · someone else's booking returns 404, same as a missing one, so IDs can't be probed · missing/invalid/expired JWT (401) · non-admin on admin routes (403) · past or timezone-less appointment times (422) · centre doesn't offer the test (422) · client-supplied `amount`/`status` ignored · double payment, paying a cancelled booking, or a second payment while one is pending (409) · failed payment then successful retry · client retry with `Idempotency-Key` returns the original payment instead of paying again · webhook replay, bad signature, amount mismatch, out-of-order events, webhook for a cancelled booking (booking stays cancelled, logged as needing a refund) · duplicate emails (case-insensitive) · login doesn't reveal whether an email exists (generic error, constant-cost hash check) · pagination bounds.

### Bonus items included
Docker + compose (Postgres with healthcheck) · Swagger/OpenAPI (`/docs`) · 34 unit/integration tests · structured JSON logging with per-request `X-Request-ID` · pagination and filtering · per-IP rate limiting on auth · idempotency keys.

## Assumptions
- A "test" is a catalogue entry (e.g. HbA1c) and a centre offers it at its own price; there is no slot/capacity model, so any number of bookings can share a time.
- Centres/tests/prices are managed by admins; anyone can browse centres. Admins are designated via `ADMIN_EMAILS` for simplicity (no admin UI).
- Appointment times must be timezone-aware and in the future.
- The payment "provider" is simulated: `POST /payments/` decides the outcome immediately (random, or forced with `simulate`). `simulate: "PENDING"` leaves the payment open to be settled by the webhook, which is how the webhook can be exercised end to end. `simulate` is a test hook and would be removed in production.
- Cancelling a booking that is already paid does not trigger a refund (no refund flow in scope).
- Single implicit currency (INR); no currency field.
- Tables are created at startup with `create_all` rather than migrations, to keep setup to one command.

## What I'd improve with more time
- **Alembic migrations** instead of `create_all`; add a Postgres service to CI so concurrency/locking behaviour is tested on the real database (tests currently use SQLite, where row locks are no-ops).
- **Slot/capacity model** to prevent double-booking a centre's time slot, plus reschedule.
- **Refund flow** and reconciliation for payments that succeed on cancelled bookings (currently logged only).
- **Background processing** (Celery + Redis): process webhooks asynchronously (ack fast, retry with backoff, dead-letter queue), expire stale `PENDING` bookings/payments, send confirmation notifications.
- **Redis** for caching the centre listing and for a shared rate limiter (the current in-memory one is per-process).
- Refresh tokens / logout, email verification and password reset; proper RBAC and an audit log instead of the `ADMIN_EMAILS` shortcut.
- Replay-window check on webhooks (signed timestamp), key rotation, and an admin view of webhook events.
- Async SQLAlchemy driver, Prometheus metrics, and request tracing.
