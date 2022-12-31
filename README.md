# Dokan Ecommerce

Dokan Ecommerce is a final year Django ecommerce project presented through a Redstore-style storefront. The project started as an academic commerce system and was expanded into a more complete platform with transactional checkout, payment handling, warehouse-aware inventory control, support workflows, analytics, and API integration.

This repository is written and maintained like a serious student capstone, not a basic CRUD submission. The codebase is structured around clear business modules, testable services, and a stable Python/Django stack.

## Project Summary

The goal of this project is to build a complete ecommerce application using Python and Django while covering the kinds of workflows that matter in a real store:

- customer registration and authentication
- catalog browsing and product detail pages
- cart and checkout workflows
- coupon handling
- online payment integration
- order tracking
- returns and customer support
- role-based internal operations
- inventory reservation and warehouse visibility
- API access for integration and reporting

This project is suitable for a 5-credit final year submission because it goes beyond storefront pages and includes backend design, transactional logic, internal tooling, testing, and deployment readiness.

## What Is Included

- customer-facing ecommerce website
- Django admin with custom analytics entry point
- internal operations dashboard
- internal inventory control dashboard
- DRF-based API v2
- JSON API v1 for legacy/internal application flows
- queued email outbox workflow
- warehouse stock reservation model
- stock movement ledger for auditability
- test coverage for major business flows

## Tech Stack

The runtime and framework choices are intentionally aligned to a stable, production-aware Django setup.

| Area | Stack |
| --- | --- |
| Language | Python 3.10.8 |
| Web framework | Django 4.1.4 |
| API framework | Django REST Framework 3.14.0 |
| Database | SQLite in development, PostgreSQL-ready in deployment |
| Payments | Stripe Checkout |
| Static delivery | WhiteNoise |
| App server | Gunicorn + Uvicorn worker |
| Media handling | Pillow-backed Django `ImageField` |
| Deployment target | Render |

## Core Features

### Storefront

- category and brand based product catalog
- product detail pages with ratings and reviews
- wishlist and compare features
- recently viewed products
- recommendation and ranked search signals
- low stock visibility on product pages

### Checkout and Orders

- cart management with quantity updates
- coupon validation and discount application
- manual/offline payment flow
- Stripe hosted checkout flow
- payment pending state handling
- order status timeline
- order history and tracking

### Inventory and Fulfillment

- warehouse model with stock levels per item
- inventory reservation during Stripe payment pending state
- reservation expiry and stale payment cleanup commands
- stock movement ledger for:
  - manual adjustments
  - warehouse transfers
  - reservation holds
  - reservation releases
  - fulfillment commits
- internal inventory dashboard for warehouse visibility

### Customer Account and Security

- signup and login
- email verification workflow
- password reset flow
- account settings and profile update module
- address book management
- login activity tracking

### Support and Post-Order Operations

- support thread and support message workflow
- return request workflow
- internal support access by role
- email notifications for support, returns, orders, and payments

### API Layer

- v1 JSON endpoints for application data
- v2 DRF endpoints with:
  - session auth
  - basic auth
  - token auth
  - throttling
  - inventory visibility
  - account update endpoints
  - inventory adjustment and transfer endpoints

## Internal Roles

The project now includes a fuller role matrix through Django groups and permissions:

- `Support Team`
- `Support Agent`
- `Support Lead`
- `Operations Team`
- `Operations Analyst`
- `Inventory Manager`
- `Warehouse Manager`
- `Finance Analyst`
- `Merchandising Manager`
- `Customer Success Manager`

This is still a monolithic Django permission model, but it is much stronger than a simple `is_staff` gate.

## Architecture

One of the strengths of this project is that the code is not organized as one giant views file with mixed logic. Business concerns are separated into predictable modules.

- `dokan/models.py`
  - catalog, orders, payments, support, notifications, warehouses, reservations, media, and stock movement models
- `dokan/services.py`
  - transactional business logic for cart, checkout, reservations, fulfillment, inventory adjustments, and transfers
- `dokan/views.py`
  - server-rendered customer and internal views
- `dokan/api_v2_views.py`
  - DRF endpoints for account and inventory operations
- `dokan/notifications.py`
  - email outbox and delivery processing
- `dokan/intelligence.py`
  - recommendation, ranking, customer insight, and support suggestion logic
- `dokan/admin_dashboard.py`
  - aggregated operational metrics for admin/internal dashboards
- `dokan/signals.py`
  - role bootstrap, stock sync hooks, and image normalization

## Key Workflows

### 1. Standard Order Flow

1. Customer browses products and adds items to cart.
2. Customer checks out with shipping and billing data.
3. Manual payment orders are placed immediately.
4. Stock is committed through service-layer logic.
5. Order status events are recorded.

### 2. Stripe Pending Payment Flow

1. Customer starts Stripe checkout.
2. Inventory is reserved across active warehouses.
3. Order enters `payment_pending`.
4. If Stripe confirms payment, reservations are fulfilled and stock is committed.
5. If payment is cancelled or expires, the cart is reopened and reservations are released or expired correctly.

### 3. Inventory Operations Flow

1. Internal user opens the inventory dashboard.
2. Stock changes are performed through controlled adjustment or transfer forms.
3. Each mutation creates stock movement records.
4. `Item.stock` is synchronized from warehouse availability.
5. Dashboards and APIs reflect updated stock immediately.

### 4. Email Notification Flow

1. Business event creates an `EmailNotification` record.
2. Email body is rendered and stored in the outbox.
3. Worker command processes queued notifications.
4. Delivery state changes to `sent`, `failed`, or `skipped`.

## API Overview

### v1

The v1 layer is kept for structured JSON endpoints already used by the application and tests.

Examples:

- `/api/v1/`
- `/api/v1/catalog/`
- `/api/v1/catalog/<slug>/`
- `/api/v1/analytics/overview/`
- `/api/v1/account/security/`
- `/api/v1/orders/<reference>/`
- `/api/v1/health/`

### v2

The v2 layer is the more modern interface and uses Django REST Framework.

Examples:

- `/api/v2/`
- `/api/v2/auth/token/`
- `/api/v2/catalog/`
- `/api/v2/account/profile/`
- `/api/v2/account/security/`
- `/api/v2/account/access/`
- `/api/v2/account/password/`
- `/api/v2/account/addresses/`
- `/api/v2/orders/<reference>/reservations/`
- `/api/v2/inventory/overview/`
- `/api/v2/inventory/warehouses/`
- `/api/v2/inventory/reservations/active/`
- `/api/v2/inventory/movements/`
- `/api/v2/inventory/adjustments/`
- `/api/v2/inventory/transfers/`

## Project Structure

```text
redstore/
|-- dokan/
|   |-- admin.py
|   |-- admin_dashboard.py
|   |-- api_serializers.py
|   |-- api_v2_serializers.py
|   |-- api_v2_views.py
|   |-- forms.py
|   |-- intelligence.py
|   |-- models.py
|   |-- notifications.py
|   |-- permissions.py
|   |-- services.py
|   |-- signals.py
|   |-- support.py
|   |-- tests.py
|   `-- views.py
|-- redstore/
|   |-- settings.py
|   |-- urls.py
|   |-- asgi.py
|   `-- wsgi.py
|-- templates/
|-- static/
|-- render.yaml
|-- build.sh
|-- Procfile
`-- requirements.txt
```

## Local Setup

Use Python `3.10.8` to match the repository runtime target.

### 1. Create virtual environment

```powershell
python -m venv .venv
```

### 2. Install dependencies

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Apply migrations

```powershell
.\.venv\Scripts\python.exe manage.py migrate
```

### 4. Start development server

```powershell
.\.venv\Scripts\python.exe manage.py runserver
```

### 5. Create admin user if needed

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

## Useful Commands

### Health and validation

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
```

### Email queue

```powershell
.\.venv\Scripts\python.exe manage.py process_email_queue --limit 25
```

### Payment cleanup

```powershell
.\.venv\Scripts\python.exe manage.py cleanup_pending_payments --minutes 30
.\.venv\Scripts\python.exe manage.py release_expired_reservations
```

## Environment Variables

Use `.env.example` as the base reference. Important values include:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DATABASE_URL`
- `SITE_BASE_URL`
- `DJANGO_ALLOWED_HOSTS`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `SUPPORT_CONTACT_EMAIL`
- `DJANGO_DEFAULT_FROM_EMAIL`
- `DJANGO_EMAIL_BACKEND`
- `DJANGO_EMAIL_DELIVERY_MODE`
- `EMAIL_QUEUE_BATCH_SIZE`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_CURRENCY`

## Media and Static Files

- static assets are served through WhiteNoise in deployment
- uploaded product media is stored through Django media handling
- in development, media is served through Django when `DEBUG=True`

## Deployment

The project is prepared for Render deployment.

- `render.yaml` defines the service blueprint
- `build.sh` installs dependencies, collects static files, and runs migrations
- `Procfile` starts Gunicorn with the ASGI application
- `redstore/settings.py` supports production database, proxy, static, and security settings

## Testing Status

The project currently has passing automated tests for the major flows:

- storefront and catalog
- cart and checkout
- Stripe pending payment workflow
- reservation expiry and cleanup
- support thread workflow
- account settings
- inventory permission boundaries
- DRF v2 token auth and inventory endpoints
- stock movement operations
- uploaded media handling

Current suite status:

- `40` tests passing

## Why This Is Stronger Than a Basic Student Ecommerce Project

Many final year ecommerce projects stop at:

- login/signup
- product listing
- cart
- simple order placement

This project goes further by including:

- transactional checkout services
- Stripe pending-state handling
- warehouse-aware reservation logic
- inventory audit trail
- internal roles and permission matrix
- support and return workflows
- queued notification design
- DRF API layer
- deployment preparation
- automated tests

That gives the project much better academic depth and much better viva value.

## Current Limitations

This is a strong final year project, but it is still a Django monolith and not a large distributed commerce platform.

Current limitations are mostly reasonable for a final year scope:

- email queue is command-driven, not backed by Celery/Redis
- media storage is local by default, not cloud object storage
- DRF token auth is used instead of OAuth2/JWT
- analytics are operational, not warehouse-forecasting or BI-grade

These are future scaling improvements, not project-breaking weaknesses.

## Academic Value

This project demonstrates practical application of:

- Python backend development
- Django architecture and ORM design
- relational data modeling and migrations
- service-layer business logic
- payment integration
- email workflow design
- REST API design
- authentication and authorization
- operational tooling
- test-driven verification
- production deployment basics

## Author

Birat Khadka  
Final Year Project  
Python / Django Focus
