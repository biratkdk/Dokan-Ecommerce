# Render Deployment Guide

## What is already prepared

- `render.yaml`
- `build.sh`
- `Procfile`
- PostgreSQL via `DATABASE_URL`
- WhiteNoise static serving
- secure production settings
- support/contact email defaulted to `biratkhadka6@gmail.com`

## Before you deploy

1. Put this project in a Git repository.
2. Push it to GitHub, GitLab, or Bitbucket.
3. Create a Render account and connect the repository.

## Blueprint deploy

The easiest path is Blueprint deploy because `render.yaml` already exists.

1. Push the repo to GitHub.
2. In Render, open `Blueprints`.
3. Create a new Blueprint instance from the repo.
4. Apply the blueprint.

This will create:

- one web service
- one PostgreSQL database

## Environment variables

Set or confirm these values in Render:

- `PYTHON_VERSION=3.12.11`
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG=0`
- `DATABASE_URL`
- `SUPPORT_CONTACT_EMAIL=biratkhadka6@gmail.com`
- `DJANGO_DEFAULT_FROM_EMAIL=Redstore Support <biratkhadka6@gmail.com>`
- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`
- `STRIPE_CURRENCY=usd`
- `SITE_BASE_URL=https://<your-service>.onrender.com`
- `DJANGO_ALLOWED_HOSTS=<your-service>.onrender.com`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://<your-service>.onrender.com`

Use Python `3.12+` on Render because this project currently pins `Django==6.0.3`.

## Optional real email delivery

If you want actual email sending instead of console logging, set:

- `DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS=1`

If you do not set SMTP values, the project still deploys, but emails will use the configured backend behavior.

## Build and start commands

These are already configured:

- Build: `bash build.sh`
- Start: `python -m gunicorn redstore.asgi:application -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT`

## After first deploy

Open the Render shell and run:

```powershell
python manage.py createsuperuser
```

Then verify:

- home page loads
- `/admin/` works
- `/dashboard/` works
- `/api/v1/health/` returns ok
- static CSS loads correctly
- checkout page loads

## If Stripe is not ready yet

Leave Stripe keys empty for the first deploy. The store will still run, but hosted Stripe checkout will stay disabled until keys are added.

## Project Positioning Note

Deployment instructions are retained in this repository to reflect a practical, production-aware handoff path for the ecommerce system.
