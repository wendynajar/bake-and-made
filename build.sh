#!/usr/bin/env bash
# Build Command de Render: instala dependencias, recolecta estáticos,
# aplica migraciones y carga el catálogo inicial (idempotente).
set -o errexit
set -o pipefail

pip install --upgrade pip
pip install -r requirements.txt

cd bakeandmade
python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py cargar_catalogo

# Crea el superusuario solo si se definieron las variables DJANGO_SUPERUSER_*.
if [[ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]]; then
  python manage.py createsuperuser --no-input || echo "El superusuario ya existe; se omite."
fi
