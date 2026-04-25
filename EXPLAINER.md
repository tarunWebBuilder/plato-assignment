# Playto Payout Engine Explainer

## What I Built

This is a minimal payout engine with:

- Django + DRF backend
- PostgreSQL-ready schema, with SQLite fallback for quick local tests
- Celery worker + beat for payout processing and retry scans
- React + Tailwind dashboard
- Seeded merchants, bank accounts, and credit ledger history

The core money path is in `backend/payouts/services.py`. API views stay thin; they validate HTTP shape and delegate accounting decisions to the service layer.

## Money Model

Amounts are stored as integer paise using `BigIntegerField`. There are no float or decimal money fields.

The ledger is append-only. Each `LedgerEntry` has:

- `available_delta_paise`
- `held_delta_paise`

Balances are derived with database `SUM()` aggregates:

```text
available = sum(available_delta_paise)
held = sum(held_delta_paise)
total merchant liability = available + held
```

Payout accounting:

```text
customer payment credit:  available +10000, held +0
payout requested:         available -6000, held +6000
payout completed:         available +0,     held -6000
payout failed:            available +6000, held -6000
```

This makes the invariant explicit:

```text
available + held = credits - completed payouts
```

Pending and processing payouts do not destroy merchant balance; they only move it from available funds to held funds.

## Concurrency

The dangerous path is payout creation. A merchant with INR 100 should not be able to create two simultaneous INR 60 payouts.

`create_payout()` wraps the whole operation in `transaction.atomic()` and locks the merchant row using `select_for_update()`. Every balance-changing operation for a merchant should take that same merchant lock. Inside the lock, available balance is computed using a database aggregate, then the hold ledger entry is inserted in the same transaction as the payout row.

That means two concurrent payout requests for the same merchant serialize at the database lock. The second request sees the first request's hold entry before deciding whether funds are available.

## Idempotency

`Idempotency-Key` is required and must be a UUID. Keys are scoped per merchant with a unique database constraint:

```text
merchant_id + key
```

The service stores:

- request hash
- response status
- response body
- expiry timestamp
- linked payout

If the same merchant retries the same key and same body, the exact stored response body and status are returned. If the same key is reused with a different body, the API returns `409 Conflict`.

Keys expire after 24 hours. Expired keys are deleted before key lookup in the payout creation transaction.

## State Machine

Legal payout transitions:

```text
pending -> processing -> completed
pending -> processing -> failed
```

Terminal states are terminal:

```text
completed: no outgoing transitions
failed:    no outgoing transitions
```

The transition logic rejects illegal movement such as `completed -> pending` or `failed -> completed`.

Failure is especially important: moving a payout to `failed` and releasing held funds happen in the same database transaction. There is no state where the payout failed but funds were not returned.

## Background Processing

Celery beat runs two periodic tasks:

- `process_pending_payouts`
- `retry_stuck_processing_payouts`

The processor claims pending payouts under row locks. It moves a payout to `processing`, increments attempts, and simulates bank settlement:

- 70% completed
- 20% failed
- 10% remains processing

Rows are selected with `select_for_update(skip_locked=True)` when the database supports it, so multiple workers can run without processing the same payout.

Processing payouts stuck for more than 30 seconds are eligible for retry after `next_retry_at`. Backoff is exponential using the attempt number. After 3 attempts, the payout is marked failed and funds are released.

## API Shape

Merchant identity is intentionally simple for the assignment: requests pass `X-Merchant-Id`. In production this would be derived from authenticated user/session claims, not a caller-provided header.

Main endpoints:

```text
GET  /api/v1/dashboard
GET  /api/v1/payouts
POST /api/v1/payouts
GET  /api/v1/payouts/<uuid>
```

`POST /api/v1/payouts` requires:

```text
X-Merchant-Id: 1
Idempotency-Key: <uuid>
```

Body:

```json
{
  "amount_paise": 6000,
  "bank_account_id": 1
}
```

## What I Would Improve Next

The next production steps would be:

- Add authenticated merchant sessions instead of `X-Merchant-Id`.
- Add a separate immutable state-transition audit table.
- Run concurrency tests against PostgreSQL in CI, not only SQLite unit tests.
- Move idempotency cleanup to a scheduled task instead of opportunistic request cleanup.
- Add webhook-style settlement provider abstraction instead of random simulation.
- Add admin tooling for stuck payout inspection and manual reconciliation.
