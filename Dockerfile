# ---- Etapa 1: compila CSS y copia HTMX/Alpine/fuentes ----------------------
FROM node:22-alpine AS assets
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tailwind.config.js ./
COPY scripts ./scripts
COPY static ./static
COPY templates ./templates
COPY apps ./apps
RUN npm run build

# ---- Etapa 2: aplicación Django ------------------------------------------
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gettext \
    && rm -rf /var/lib/apt/lists/*

COPY requirements ./requirements
ARG REQUIREMENTS=base
RUN pip install -r requirements/${REQUIREMENTS}.txt

COPY . .
COPY --from=assets /app/static/css ./static/css
COPY --from=assets /app/static/vendor ./static/vendor

RUN SECRET_KEY=build DATABASE_URL=sqlite:////tmp/build.db python manage.py collectstatic --noinput \
    && useradd --create-home pms && chown -R pms /app
USER pms

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60"]
