# Dokan Ecommerce

## Final Year Project Documentation

Dokan Ecommerce is a final-year 5-credit academic project developed using Python and Django. The application is presented through a Redstore-themed storefront interface and implements a complete ecommerce workflow covering product browsing, cart management, checkout, payments, order tracking, returns, customer support, analytics, and API integration.

## Historical Note

This repository contains the maintained and extended version of the original 2022 final-year project. The academic project began in 2022, and the current codebase includes later improvements in deployment, analytics, APIs, reliability, and operations.

## Project Objectives

- design and implement a full-featured ecommerce web application using Python
- apply Django for modular architecture, ORM-based modeling, routing, templates, and admin management
- build secure customer account, cart, checkout, and order-processing workflows
- expose structured application APIs for integration, reporting, and monitoring
- incorporate 2022-appropriate AI and ML-style analytical components for recommendations and customer insight
- prepare the system for real deployment using PostgreSQL-backed hosting

## Project Overview

The system follows a backend-first ecommerce architecture. Core business workflows are implemented in Python and Django, while the frontend uses server-rendered templates for a clean and maintainable user experience. The application includes both customer-facing features and administrative capabilities, making it suitable as a complete academic capstone-style submission rather than a simple storefront prototype.

The user interface is branded as Redstore, while the project repository and documentation are maintained under the Dokan Ecommerce name.

## Major Modules

- Catalog and inventory management
- Customer account and authentication management
- Cart, checkout, and coupon handling
- Payment processing and confirmation
- Order history, tracking, and return requests
- Support ticket and conversation workflow
- Email notification and verification flow
- Admin analytics and operational monitoring
- JSON API layer for application services
- Health monitoring and deployment support

## Key Features

- Product catalog with categories, brands, product metadata, pricing, and stock visibility
- Product detail pages with verified reviews and ratings
- Cart management with quantity updates and coupon application
- Stripe Checkout integration with payment success, cancel, and webhook handling
- Order creation, tracking, and status history
- Wishlist, compare, and recently viewed product flows
- Return request workflow for delivered orders
- Customer dashboard with order overview, profile state, and account activity
- Email verification flow and login activity tracking
- Support thread system for customer-service communication
- Transactional email support for verification, orders, payments, returns, and support replies
- Admin analytics dashboard for revenue, top products, support activity, and inventory visibility
- Health endpoints and cleanup tooling for operational reliability

## Applied Intelligence Components

This project includes classical AI and ML-style modules aligned with a 2022 academic project scope. It does not rely on modern LLM-based architecture. Instead, it focuses on practical analytical features that can be implemented and explained clearly within a Python ecommerce system.

- recommendation scoring based on product and customer activity
- ranked catalog search and support-answer retrieval
- customer segmentation and retention scoring
- demand prioritization and stock-risk estimation
- analytics-driven operational insights for administrators

## Technology Stack

- Programming language: Python
- Framework: Django
- Database: SQLite for development, PostgreSQL for deployment
- Frontend: Django templates, HTML, CSS, JavaScript
- Payment integration: Stripe Checkout
- Deployment: Render, Gunicorn, WhiteNoise
- API style: JSON-based application endpoints
- Runtime target: Python 3.12+

## Project Structure

- `dokan/` main ecommerce application, models, views, forms, services, APIs, and business logic
- `redstore/` project settings, URL configuration, ASGI and WSGI entry points
- `templates/` server-rendered frontend templates
- `static/` CSS, JavaScript, and image assets
- `render.yaml` deployment blueprint for Render
- `build.sh` production build script
- `Procfile` application start command
- `.env.example` environment configuration template

## Selected Functional Endpoints

### Web Routes

- `/`
- `/products/`
- `/cart/`
- `/checkout/`
- `/dashboard/`
- `/orders/`
- `/support/threads/`
- `/admin/analytics/`

### API Routes

- `/api/v1/`
- `/api/v1/catalog/`
- `/api/v1/catalog/<slug>/`
- `/api/v1/recommendations/<slug>/`
- `/api/v1/analytics/overview/`
- `/api/v1/account/overview/`
- `/api/v1/account/security/`
- `/api/v1/intelligence/assistant/?q=<query>`
- `/api/v1/orders/<reference>/`
- `/api/v1/support/threads/`
- `/api/v1/health/`

## Local Setup

### 1. Create a virtual environment

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

### 4. Run the development server

```powershell
.\.venv\Scripts\python.exe manage.py runserver
```

### 5. Optional demo data

The project includes seeded store data through migrations so a fresh setup can be demonstrated quickly after migration.

## Environment Variables

Use `.env.example` as the starting reference. Important settings include:

- `PYTHON_VERSION`
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DATABASE_URL`
- `SITE_BASE_URL`
- `SUPPORT_CONTACT_EMAIL`
- `DJANGO_DEFAULT_FROM_EMAIL`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_CURRENCY`

Optional email settings for SMTP:

- `DJANGO_EMAIL_BACKEND`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS`

## Payment and Email Configuration

Stripe is used for hosted checkout flow. To enable payment processing, configure:

- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_CURRENCY`

Stripe webhook endpoint:

- `/webhooks/stripe/`

For local development, email defaults to the Django console backend. For a deployed environment, SMTP values can be added to enable real outgoing email.

## Deployment

This project is configured for Render deployment and has already been prepared with the required deployment files.

- `render.yaml` defines the service and database blueprint
- `build.sh` installs requirements, collects static files, and applies migrations
- `Procfile` starts Gunicorn with the ASGI application
- `redstore/settings.py` supports `DATABASE_URL`, secure cookies, proxy headers, and WhiteNoise static serving

Deployment notes:

- use Python `3.12+` because the project currently pins `Django==6.0.3`
- PostgreSQL is recommended for deployed environments
- set `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` for the deployed domain
- configure Stripe and SMTP credentials separately for production use

## Verification

The following commands are used to verify local correctness:

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
```

Operational health endpoints:

- `/health/`
- `/api/v1/health/`

Cleanup command for pending payment sessions:

```powershell
.\.venv\Scripts\python.exe manage.py cleanup_pending_payments --minutes 30
```

## Academic Relevance

This project demonstrates the practical application of:

- object-oriented backend design in Python
- relational database modeling and migrations
- web application development with Django
- authentication and authorization workflows
- payment gateway integration
- email and notification workflows
- REST-style API design
- analytics-oriented problem solving in ecommerce systems
- production deployment and environment configuration

## Future Enhancements

- background job processing for email and post-order tasks
- stronger reporting dashboards and exportable analytics
- advanced product filtering and search indexing
- role-based staff permission refinement
- caching and performance optimization
- extended payment reconciliation and audit logging

## Author

Birat Khadka  
Project contact: `biratkhadka6@gmail.com`
