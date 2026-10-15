#!/usr/bin/env bash
# Construcción en Render: dependencias, archivos estáticos y migraciones (RNF-MAN-04).
# El CSS de Tailwind (static/css/app.css) y las traducciones (.mo) ya vienen compilados en el repositorio.
set -o errexit

pip install --upgrade pip
pip install -r requirements/base.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
