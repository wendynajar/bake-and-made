# Despliegue en Render: Web Service + PostgreSQL

El repo ya trae todo lo necesario: `requirements.txt`, `build.sh`, `render.yaml`, `.env.example` y un `settings.py` que lee la configuración de variables de entorno.

## Archivos de despliegue (raíz del repo)

| Archivo | Para qué sirve |
|---|---|
| `requirements.txt` | Dependencias que instala Render con `pip`. Debe coincidir con el `Pipfile` |
| `build.sh` | Build Command: `pip install`, `collectstatic`, `migrate`, `cargar_catalogo` y, si se definen las variables, crea el superusuario |
| `render.yaml` | Blueprint que crea a la vez el Web Service y la base PostgreSQL |
| `.env.example` | Plantilla de variables para desarrollo local (cópiala a `.env`) |
| `.gitattributes` | Obliga a usar saltos de línea LF en `*.sh`. Con CRLF, Render no puede ejecutar el script |

## Opción A: Blueprint (recomendada)

Render → **New → Blueprint** → selecciona el repo. Se crean `bakeandmade-db` (PostgreSQL) y `bakeandmade` (Web Service), con `DATABASE_URL` ya conectada y un `SECRET_KEY` generado. Las variables marcadas con `sync: false` (AWS y superusuario) se llenan en el panel.

## Opción B: creación manual

### 1. PostgreSQL
**New → Postgres**, en la misma región que el Web Service. Copia la **Internal Database URL**.

> Según la política actual de Render, la base de datos gratuita **expira a los 30 días**. Para datos reales conviene un plan de pago.

### 2. Web Service

| Campo | Valor |
|---|---|
| Language | Python 3 |
| Branch | `main` |
| **Root Directory** | *(vacío: raíz del repo)* |
| **Build Command** | `./build.sh` |
| **Start Command** | `cd bakeandmade && gunicorn bakeandmade.wsgi:application --bind 0.0.0.0:$PORT` |
| Health Check Path | `/` |

gunicorn es el servidor WSGI de producción: levanta `WEB_CONCURRENCY` procesos que ejecutan `bakeandmade/bakeandmade/wsgi.py`. WhiteNoise sirve el CSS y el JS desde el mismo proceso, y las imágenes subidas se guardan en S3.

### 3. Variables de entorno

| Variable | Obligatoria | Valor |
|---|---|---|
| `PYTHON_VERSION` | sí | `3.13.5` (Django 6.1 requiere ≥ 3.12) |
| `SECRET_KEY` | sí | Botón *Generate*. **No** reutilices la clave que estaba en el repo |
| `DEBUG` | sí | `False` |
| `DATABASE_URL` | sí | Internal Database URL del PostgreSQL |
| `WEB_CONCURRENCY` | recomendada | `2` |
| `AWS_STORAGE_BUCKET_NAME` | para imágenes | Nombre del bucket. Si está vacía, las imágenes se guardan en el disco efímero y **se pierden** en cada deploy |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | con S3 | Credenciales de un usuario IAM con permisos sobre ese bucket |
| `AWS_S3_REGION_NAME` | con S3 | p. ej. `us-east-1` |
| `AWS_S3_CUSTOM_DOMAIN` | no | Dominio de CloudFront, si lo usas |
| `AWS_QUERYSTRING_AUTH` | no | `True` por defecto (URLs firmadas). Usa `False` si el bucket es público |
| `DJANGO_SUPERUSER_USERNAME` / `_EMAIL` / `_PASSWORD` | no | `build.sh` crea el admin si están definidas |
| `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` | no | Solo para dominios propios, separados por comas (los orígenes con `https://`) |
| `SECURE_HSTS_SECONDS` | no | `0` por defecto. Súbela solo cuando HTTPS esté confirmado |
| `LOG_LEVEL` | no | `INFO` por defecto |
| `RENDER_EXTERNAL_HOSTNAME` | — | La define Render automáticamente. Se agrega sola a `ALLOWED_HOSTS` y a `CSRF_TRUSTED_ORIGINS` |

## Desarrollo local

```bash
cp .env.example .env          # pon DEBUG=True y deja DATABASE_URL vacía para usar SQLite
pipenv install                # el Pipfile cambió: se regenera Pipfile.lock
cd bakeandmade
python manage.py migrate
python manage.py cargar_catalogo
python manage.py runserver
python manage.py test         # tests de tienda y usuarios
```

Para simular producción en WSL:
```bash
cd bakeandmade
DEBUG=False SECRET_KEY=prueba python manage.py check --deploy
DEBUG=False SECRET_KEY=prueba python manage.py collectstatic --no-input
DEBUG=False SECRET_KEY=prueba gunicorn bakeandmade.wsgi:application --bind 0.0.0.0:8000
```

## Checklist después del deploy

- [ ] Los logs del build muestran `collectstatic`, `migrate` y `cargar_catalogo` sin errores.
- [ ] `/` carga con estilos (si no, revisa WhiteNoise y `STATIC_ROOT`).
- [ ] `/admin/` permite entrar con el superusuario.
- [ ] Una imagen subida desde el admin se ve en `/` y sigue ahí después de un redeploy (S3).
- [ ] El registro, el login, el carrito, el checkout y el Sweet Plan funcionan (si da error CSRF, revisa `CSRF_TRUSTED_ORIGINS`).
