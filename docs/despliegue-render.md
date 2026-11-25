# Despliegue en Render: Web Service + PostgreSQL

El repo ya trae todo lo necesario: `requirements.txt`, `build.sh`, `render.yaml`, `.env.example` y un `settings.py` que lee la configuración de variables de entorno.

> **Rama de despliegue: `feat/render-allocation`.** Todo push a esa rama llega a producción. El trabajo nuevo se hace en otra rama (por ejemplo `feat/iot-vip`) y se fusiona solo con `python manage.py test` en verde.

## Archivos de despliegue (raíz del repo)

| Archivo | Para qué sirve |
|---|---|
| `requirements.txt` | Dependencias que instala Render con `pip`. Debe coincidir con el `Pipfile` |
| `build.sh` | Build Command: `pip install`, `collectstatic`, `migrate`, `cargar_catalogo`, `crear_terminal caja-1` y, si se definen sus variables, el superusuario y los usuarios demo VIP |
| `render.yaml` | Blueprint que crea a la vez el Web Service y la base PostgreSQL |
| `.env.example` | Plantilla de variables para desarrollo local (cópiala a `.env`) |
| `.gitattributes` | Obliga a usar saltos de línea LF en `*.sh`. Con CRLF, Render no puede ejecutar el script |

## Opción A: Blueprint (recomendada)

Render → **New → Blueprint** → selecciona el repo. Se crean `bakeandmade-db` (PostgreSQL) y `bakeandmade` (Web Service), con `DATABASE_URL` ya conectada y `SECRET_KEY` e `IOT_DEVICE_TOKEN` generados. Las variables marcadas con `sync: false` (AWS, superusuario y demo) se llenan en el panel.

> Si el servicio se creó **a mano** (opción B), los cambios de `render.yaml` no se aplican solos: agrega las variables nuevas y el Health Check Path en el panel del servicio.

## Opción B: creación manual

### 1. PostgreSQL
**New → Postgres**, en la misma región que el Web Service. Copia la **Internal Database URL**.

> Según la política actual de Render, la base de datos gratuita **expira a los 30 días**. Para datos reales conviene un plan de pago.

### 2. Web Service

| Campo | Valor |
|---|---|
| Language | Python 3 |
| Branch | `feat/render-allocation` |
| **Root Directory** | *(vacío: raíz del repo)* |
| **Build Command** | `./build.sh` |
| **Start Command** | `cd bakeandmade && gunicorn bakeandmade.wsgi:application --bind 0.0.0.0:$PORT` |
| Health Check Path | `/healthz` (responde 200 sin tocar la base de datos y está exento de la redirección a HTTPS) |

gunicorn es el servidor WSGI de producción: levanta `WEB_CONCURRENCY` procesos que ejecutan `bakeandmade/bakeandmade/wsgi.py`. WhiteNoise sirve el CSS y el JS desde el mismo proceso, y las imágenes y videos subidos se guardan en S3.

### 3. Variables de entorno

| Variable | Obligatoria | Valor |
|---|---|---|
| `PYTHON_VERSION` | sí | `3.13.5` (Django 6.1 requiere ≥ 3.12) |
| `SECRET_KEY` | sí | Botón *Generate*. **No** reutilices la clave que estaba en el repo |
| `DEBUG` | sí | `False` |
| `DATABASE_URL` | sí | Internal Database URL del PostgreSQL |
| `WEB_CONCURRENCY` | recomendada | `2` |
| `AWS_STORAGE_BUCKET_NAME` | **sí para la capa VIP** | Nombre del bucket (privado). Si está vacía, imágenes y videos se guardan en el disco efímero y **se pierden** en cada deploy |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | con S3 | Credenciales de un usuario IAM con permisos solo sobre ese bucket |
| `AWS_S3_REGION_NAME` | con S3 | p. ej. `us-east-1` |
| `AWS_S3_CUSTOM_DOMAIN` | no | Dominio de CloudFront, si lo usas |
| `AWS_QUERYSTRING_AUTH` | no | `True` por defecto (URLs firmadas que vencen en 1 h). Déjala así: los videos del QR deben ser privados |
| `IOT_DEVICE_TOKEN` | sí para el lector | Botón *Generate* (el Blueprint lo genera). El mismo valor va en `firmware/esp32-vip/include/secrets.h`. Vacía = el lector siempre recibe 401 |
| `DEMO_PASSWORD` | no | Contraseña de los 3 usuarios demo VIP. `build.sh` los crea si existe junto con `DEMO_VIP_UIDS` |
| `DEMO_VIP_UIDS` | no | UID de las 3 tarjetas físicas separados por comas, en el orden Ana, Bruno, Carla (se leen del monitor serie del ESP32) |
| `DJANGO_SUPERUSER_USERNAME` / `_EMAIL` / `_PASSWORD` | no | `build.sh` crea el admin si están definidas |
| `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` | no | Solo para dominios propios, separados por comas (los orígenes con `https://`) |
| `SECURE_HSTS_SECONDS` | no | `0` por defecto. Súbela solo cuando HTTPS esté confirmado |
| `LOG_LEVEL` | no | `INFO` por defecto |
| `RENDER_EXTERNAL_HOSTNAME` | — | La define Render automáticamente. Se agrega sola a `ALLOWED_HOSTS` y a `CSRF_TRUSTED_ORIGINS` |

### 4. Bucket de S3 (videos del QR e imágenes)

1. Crea el bucket en la región de `AWS_S3_REGION_NAME`, con **Block all public access** activado (las URLs firmadas no necesitan acceso público).
2. Crea un usuario IAM solo para la app, con una política limitada a ese bucket: `s3:GetObject`, `s3:PutObject` y `s3:DeleteObject` sobre `arn:aws:s3:::<bucket>/*`, y `s3:ListBucket` sobre `arn:aws:s3:::<bucket>`.
3. Genera sus claves de acceso y cópialas a `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY` en Render. Nunca al repo.
4. Los archivos se guardan bajo `media/` (`media/videos/` para los videos y `media/productos/` para las imágenes del catálogo). Sube videos cortos desde el admin (menos de ~30 MB): el archivo pasa por la instancia de Render, que tiene poca memoria y un timeout de 30 s.

5. **Imágenes del catálogo.** `cargar_catalogo` asigna a cada producto una ruta de `IMAGENES` (p. ej. `productos/crv.jpg`) solo al crearlo o si no tiene imagen; nunca pisa una imagen cambiada en el admin. Los archivos deben subirse al bucket en `media/productos/` con esos nombres. Mientras falten, la tienda muestra el logo en su lugar.

## Desarrollo local

```bash
cp .env.example .env          # pon DEBUG=True y deja DATABASE_URL vacía para usar SQLite
pipenv install                # o: pip install -r requirements.txt
cd bakeandmade
python manage.py migrate
python manage.py cargar_catalogo
python manage.py crear_terminal caja-1
DEMO_PASSWORD=algo-local python manage.py crear_usuarios_demo --uids A1B2C3D4,B2C3D4E5,C3D4E5F6
python manage.py runserver
python manage.py test         # tests de tienda, usuarios e iot
```

Para probar el kiosco sin hardware: entra como staff a `/kiosco/caja-1/` y, en otra terminal, `python manage.py simular_scan A1B2C3D4 --terminal caja-1`.

Para simular producción en WSL:
```bash
cd bakeandmade
DEBUG=False SECRET_KEY=prueba python manage.py check --deploy
DEBUG=False SECRET_KEY=prueba python manage.py collectstatic --no-input
DEBUG=False SECRET_KEY=prueba gunicorn bakeandmade.wsgi:application --bind 0.0.0.0:8000
```

`check --deploy` todavía avisa `mail.E001` (backend de correo de consola, hallazgo #15) y `security.W004` (HSTS, hallazgo #16). Ninguno impide el deploy.

## Checklist después del deploy

- [ ] Los logs del build muestran `collectstatic`, `migrate`, `cargar_catalogo` y `crear_terminal` sin errores (y `crear_usuarios_demo` si definiste las variables demo).
- [ ] `https://<servicio>.onrender.com/healthz` responde `ok`.
- [ ] `/` carga con estilos (si no, revisa WhiteNoise y `STATIC_ROOT`).
- [ ] `/admin/` permite entrar con el superusuario y muestra las secciones "IoT (RFID)" y "Perfiles VIP".
- [ ] Una imagen subida desde el admin se ve en `/` y sigue ahí después de un redeploy (S3).
- [ ] El registro, el login, el carrito, el checkout y el Sweet Plan funcionan (si da error CSRF, revisa `CSRF_TRUSTED_ORIGINS`).
- [ ] Con un usuario Sweet aparece la pestaña "VIP" y `/vip/` carga el calendario.
- [ ] `curl` al lector responde 401 sin token y 404 con un UID inventado:
  ```bash
  curl -i -X POST https://<servicio>.onrender.com/api/rfid/scan/ \
    -H "Authorization: Token $IOT_DEVICE_TOKEN" -H "Content-Type: application/json" \
    -d '{"uid":"FFFFFFFF","terminal":"caja-1"}'
  ```
