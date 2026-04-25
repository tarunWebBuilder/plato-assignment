# Playto Payout Engine

Minimal payout engine for Indian merchants receiving international payments.

## Stack

- Backend: Django, Django REST Framework
- Database: PostgreSQL in Docker, SQLite fallback for quick local checks
- Background jobs: Celery with Redis
- Frontend: React, Vite, Tailwind

## Run with Docker

```bash
docker compose up --build
```

Backend: http://localhost:8000  
Frontend: http://localhost:5173

Seed data is loaded automatically by the backend container.

## Environment Variables

Do not commit real secrets. Copy the examples and fill values for your environment:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

Backend hosting needs:

- `DATABASE_URL` for hosted PostgreSQL
- `REDIS_URL` or `CELERY_BROKER_URL` for Redis/Celery
- `DJANGO_SECRET_KEY`
- `DJANGO_ALLOWED_HOSTS`
- `CORS_ALLOWED_ORIGINS`
- `CSRF_TRUSTED_ORIGINS`

Frontend hosting needs:

- `VITE_API_BASE_URL`, pointing to the hosted backend API

## API

Use merchant `1`, `2`, or `3` via `X-Merchant-Id`.

```bash
curl http://localhost:8000/api/v1/dashboard -H "X-Merchant-Id: 1"
```

```bash
curl -X POST http://localhost:8000/api/v1/payouts \
  -H "Content-Type: application/json" \
  -H "X-Merchant-Id: 1" \
  -H "Idempotency-Key: 11111111-1111-1111-1111-111111111111" \
  -d '{"amount_paise":6000,"bank_account_id":1}'
```

## Local Backend Checks

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo
python manage.py test
python manage.py runserver 127.0.0.1:8000


# Terminal 1
docker start playto-redis

# Terminal 2
cd C:\Users\user\Desktop\assignment\backend
.venv\Scripts\activate
python manage.py runserver 127.0.0.1:8000

# Terminal 3
cd C:\Users\user\Desktop\assignment\backend
.venv\Scripts\activate
celery -A playto worker -l info --pool=solo

# Terminal 4
cd C:\Users\user\Desktop\assignment\backend
.venv\Scripts\activate
celery -A playto beat -l info
```
