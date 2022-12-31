# Render Deployment Notes

This document explains how to deploy Dokan Ecommerce to Render using the repository as it exists today. The project is already prepared for a simple web-service deployment on a stable Python/Django stack.

## Deployment Baseline

The repository already includes:

- `render.yaml`
- `build.sh`
- `Procfile`
- production-aware Django settings
- PostgreSQL support through `DATABASE_URL`
- WhiteNoise static file serving
- runtime target pinned to Python `3.10.8`

The current Render blueprint creates:

- one PostgreSQL database
- one Python web service

## Runtime Assumptions

This deployment is aligned to the project runtime used in the repository:

- Python `3.10.8`
- Django `4.1.4`
- Django REST Framework `3.14.0`

Do not switch the Render runtime to a newer major Python version unless you also revalidate the project locally.

## Before You Deploy

1. Push the repository to GitHub, GitLab, or Bitbucket.
2. Create or sign in to your Render account.
3. Confirm that the repo contains the current `render.yaml`.
4. Decide whether you want:
   - demo deployment with console email backend
   - real SMTP-backed outgoing email

## Recommended Deployment Path

Use Render Blueprint deployment.

1. Open `Blueprints` in Render.
2. Create a new Blueprint from the repository.
3. Review the generated service and database.
4. Apply the Blueprint.

Render will provision the database first, then build and start the web service.

## Default Build and Start Commands

These are already wired into the repo.

Build:

```bash
bash build.sh
```

Start:

```bash
python -m gunicorn redstore.asgi:application -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT
```

## Required Environment Variables

Set or confirm these values in Render:

- `PYTHON_VERSION=3.10.8`
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG=0`
- `DATABASE_URL`
- `SITE_BASE_URL=https://<your-service>.onrender.com`
- `DJANGO_ALLOWED_HOSTS=<your-service>.onrender.com`
- `DJANGO_CSRF_TRUSTED_ORIGINS=https://<your-service>.onrender.com`
- `SUPPORT_CONTACT_EMAIL=biratkhadka6@gmail.com`
- `DJANGO_DEFAULT_FROM_EMAIL=Redstore Support <biratkhadka6@gmail.com>`
- `STRIPE_CURRENCY=usd`

## Optional Payment Variables

Set these only when Stripe is ready:

- `STRIPE_SECRET_KEY`
- `STRIPE_WEBHOOK_SECRET`

If these are blank, the application still runs, but Stripe hosted checkout stays disabled.

## Optional Email Variables

For a demo deployment, the current `console` backend is enough. For real outgoing email, configure SMTP:

- `DJANGO_EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend`
- `DJANGO_EMAIL_DELIVERY_MODE=queue`
- `EMAIL_QUEUE_BATCH_SIZE=25`
- `EMAIL_HOST`
- `EMAIL_PORT`
- `EMAIL_HOST_USER`
- `EMAIL_HOST_PASSWORD`
- `EMAIL_USE_TLS=1`
- `EMAIL_USE_SSL=0`

## Email Queue Note

Application emails are not sent inline during requests. They are first written to the database outbox through the `EmailNotification` model, then delivered by the worker command.

Manual processing command:

```powershell
python manage.py process_email_queue --limit 25
```

For a stronger deployment, wire this command into a scheduled job or separate worker process.

## First Deploy Checklist

After the service is live:

1. Open the Render shell.
2. Create an admin user.

```powershell
python manage.py createsuperuser
```

3. Verify these routes:

- `/`
- `/products/`
- `/dashboard/`
- `/operations/overview/`
- `/operations/inventory/`
- `/api/v1/health/`
- `/api/v2/`
- `/admin/`

4. Verify static assets load correctly.
5. If Stripe is configured, verify the checkout page shows Stripe availability.

## Operational Commands

These are useful after deployment:

Run tests locally before deploy:

```powershell
.\.venv\Scripts\python.exe manage.py test
```

Release expired reservations:

```powershell
python manage.py release_expired_reservations
```

Reopen stale pending payments:

```powershell
python manage.py cleanup_pending_payments --minutes 30
```

Deliver queued emails:

```powershell
python manage.py process_email_queue --limit 25
```

## Current Deployment Shape

This deployment approach is appropriate for a final year Django project because it stays simple:

- one web app
- one database
- one documented runtime target
- no unnecessary infrastructure overhead

It is production-aware, but still intentionally monolithic and easy to explain during project review or viva.

## Known Constraints

- email queue processing is not yet provisioned as a dedicated Render worker in `render.yaml`
- media storage is local unless you later move to S3 or another object store
- the project is optimized for academic/demo deployment scale, not high-traffic marketplace scale

Those are acceptable constraints for this project stage.
