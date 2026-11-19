#!/usr/bin/env bash
# Build Command de Render: instala dependencias, recolecta estáticos,
# aplica migraciones y carga los datos iniciales (todo idempotente).
set -o errexit
set -o pipefail

pip install --upgrade pip
pip install -r requirements.txt

cd bakeandmade
python manage.py collectstatic --no-input
python manage.py migrate --no-input
python manage.py cargar_catalogo

# Terminal del kiosco de la tienda (capa VIP/RFID). No falla si ya existe.
python manage.py crear_terminal caja-1

# Crea el superusuario solo si se definieron las variables DJANGO_SUPERUSER_*.
if [[ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]]; then
  python manage.py createsuperuser --no-input || echo "El superusuario ya existe; se omite."
fi

# Usuarios Sweet de la demo VIP, solo si se definieron DEMO_PASSWORD y DEMO_VIP_UIDS.
if [[ -n "${DEMO_PASSWORD:-}" && -n "${DEMO_VIP_UIDS:-}" ]]; then
  python manage.py crear_usuarios_demo
fi
