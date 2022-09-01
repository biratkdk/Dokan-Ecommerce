# Redstore Advanced Ecommerce

Redstore is a Django-based ecommerce application upgraded into a stronger portfolio-level Python project. The current build keeps a 2022-style architecture: server-rendered pages, clean Python services, transactional email, account security, support chat, classical recommendation logic, JSON APIs, and a richer commerce domain without depending on modern LLM tooling.

## Core Features

- Django ecommerce storefront with catalog, product detail, cart, checkout, and account flows
- Structured catalog domain with brands, categories, product attributes, tags, gallery images, and inventory signals
- Wishlist and verified product reviews
- Product compare and recently viewed browsing flows
- Order history and order status timeline tracking
- Return request workflow for delivered orders
- Account dashboard with email verification, login activity tracking, notification log, and customer health summary
- Support ticket chat workflow with customer/staff conversations and assistant-style help suggestions
- Transactional email flow for account verification, order placement, payment confirmation, return submission, and support replies
- Stripe Checkout integration with webhook-driven payment confirmation
- Coupon rules with minimum order value, usage caps, and validity windows
- Store intelligence layer for recommendation scoring, ranked search, customer segmentation, retention scoring, support-answer retrieval, demand scoring, and stockout estimation
- Admin analytics dashboard at `/admin/analytics/` for revenue, payment mix, top products, low-stock monitoring, open returns, verified profiles, and open support threads
- Health endpoints plus stale pending-payment cleanup tooling for better operational reliability
- JSON API endpoints for catalog, product detail, recommendations, compare state, analytics, account overview, account security, assistant search/support suggestions, order tracking, support threads, and wishlist actions
- Seeded 2022-era demo data for products, reviews, historical orders, and analytics

## Tech Direction

- Backend: Python + Django
- Frontend: Django templates, static CSS, server-rendered UX
- Intelligence: classical Python heuristics, retrieval, and analytics functions
- Data: SQLite by default
- Deployment: dynamic-host ready with Render blueprint, Gunicorn, WhiteNoise, and `DATABASE_URL` support
- Style: practical, clean, backend-heavy ecommerce project suitable for a strong academic or 2-year Python developer portfolio

## API Endpoints

- `/api/v1/`
- `/api/v1/catalog/`
- `/api/v1/catalog/<slug>/`
- `/api/v1/recommendations/<slug>/`
- `/api/v1/compare/`
- `/api/v1/analytics/overview/`
- `/api/v1/account/overview/`
- `/api/v1/account/security/`
- `/api/v1/intelligence/assistant/?q=<query>`
- `/api/v1/health/`
- `/api/v1/orders/<reference>/`
- `/api/v1/support/threads/`
- `/api/v1/support/threads/<id>/`
- `/api/v1/wishlist/<slug>/toggle/`

## Local Run

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

Environment template:

- copy values from `.env.example`
- default support/contact email is set to `biratkhadka6@gmail.com`

## Stripe Configuration

Set these environment variables before using hosted card payments:

- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_CURRENCY` (defaults to `usd`)

Email and application settings:

- `DJANGO_EMAIL_BACKEND` (defaults to Django console backend for local development)
- `DJANGO_DEFAULT_FROM_EMAIL`
- `SUPPORT_CONTACT_EMAIL`
- `SITE_BASE_URL` (used in verification and support emails)
- `DATABASE_URL` (used automatically in deployment)

Webhook endpoint:

- `/webhooks/stripe/`

## Operations

Health endpoints:

- `/health/`
- `/api/v1/health/`

Key authenticated UI routes:

- `/dashboard/`
- `/support/threads/`
- `/account/verify/<token>/`

Cleanup stale Stripe sessions:

```powershell
.\.venv\Scripts\python.exe manage.py cleanup_pending_payments --minutes 30
```

## Dynamic Deployment

This project is now prepared for dynamic deployment on Render:

- `render.yaml` provisions a Python web service plus PostgreSQL
- `build.sh` runs `collectstatic` and `migrate`
- `Procfile` starts the app with Gunicorn + Uvicorn worker
- `redstore/settings.py` supports `DATABASE_URL`, Render host detection, WhiteNoise static serving, secure cookies, and proxy SSL headers

Render-specific env vars already scaffolded:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG=0`
- `DATABASE_URL`
- `SUPPORT_CONTACT_EMAIL=biratkhadka6@gmail.com`
- `DJANGO_DEFAULT_FROM_EMAIL=Redstore Support <biratkhadka6@gmail.com>`

If you want real outgoing email after deployment, switch `DJANGO_EMAIL_BACKEND` from console backend to SMTP and provide:

- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS`

## Validation

```powershell
python manage.py check
python manage.py test
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
```
