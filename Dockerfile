FROM python:3.10.8-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Match the production storage backend (manifest-based) when building static
# assets, regardless of what DJANGO_DEBUG is set to at container runtime.
RUN DJANGO_DEBUG=0 python manage.py collectstatic --no-input

ENV DJANGO_DEBUG=0

EXPOSE 8000

CMD ["gunicorn", "redstore.asgi:application", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
