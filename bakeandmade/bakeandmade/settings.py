"""
Configuración de Django para Bake & Made.

Todas las credenciales y valores que cambian entre entornos se leen de
variables de entorno (ver `.env.example` en la raíz del repositorio).
En local se cargan desde `.env` mediante python-dotenv; en Render se
definen en el panel del Web Service.

Docs: https://docs.djangoproject.com/en/6.1/ref/settings/
"""

import os
import sys
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

# BASE_DIR = carpeta que contiene manage.py; REPO_DIR = raíz del repositorio.
BASE_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BASE_DIR.parent

load_dotenv(REPO_DIR / '.env')


def env_bool(nombre: str, por_defecto: bool = False) -> bool:
    """Interpreta una variable de entorno como booleano ('true', '1', 'yes', 'on')."""
    valor = os.environ.get(nombre)
    if valor is None:
        return por_defecto
    return valor.strip().lower() in {'1', 'true', 'yes', 'on'}


def env_list(nombre: str) -> list[str]:
    """Interpreta una variable de entorno separada por comas como lista sin vacíos."""
    return [v.strip() for v in os.environ.get(nombre, '').split(',') if v.strip()]


# --- Seguridad ---------------------------------------------------------------

DEBUG = env_bool('DEBUG', por_defecto=False)
EJECUTANDO_TESTS = len(sys.argv) > 1 and sys.argv[1] == 'test'

SECRET_KEY = os.environ.get('SECRET_KEY', '')
if not SECRET_KEY:
    if not (DEBUG or EJECUTANDO_TESTS):
        raise RuntimeError('Define la variable de entorno SECRET_KEY (o DEBUG=True en local).')
    SECRET_KEY = 'django-insecure-solo-para-desarrollo-local'

ALLOWED_HOSTS = ['localhost', '127.0.0.1', *env_list('ALLOWED_HOSTS')]
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')

# Render define RENDER_EXTERNAL_HOSTNAME automáticamente (p. ej. bakeandmade.onrender.com).
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS.append(f'https://{RENDER_EXTERNAL_HOSTNAME}')

if not DEBUG:
    # Render termina TLS en su proxy y reenvía la petición por HTTP.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', por_defecto=True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '0'))


# --- Aplicaciones --------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'tienda',
    'usuarios',
    'iot',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'bakeandmade.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'tienda.context_processors.contador_carrito',
            ],
        },
    },
]

WSGI_APPLICATION = 'bakeandmade.wsgi.application'


# --- Base de datos -------------------------------------------------------------
# DATABASE_URL apunta a PostgreSQL en Render; sin ella (o vacía) se usa SQLite en local.
# Se usa parse() y no config() porque config() trata DATABASE_URL="" como
# "sin base de datos" en lugar de aplicar el valor por defecto.

DATABASES = {
    'default': dj_database_url.parse(
        os.environ.get('DATABASE_URL', '').strip() or f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=int(os.environ.get('DB_CONN_MAX_AGE', '600')),
        conn_health_checks=True,
    )
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# --- Contraseñas ---------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LOGIN_REDIRECT_URL = 'inicio'
LOGOUT_REDIRECT_URL = 'inicio'
LOGIN_URL = 'login'


# --- Internacionalización ------------------------------------------------------

LANGUAGE_CODE = 'es-mx'
TIME_ZONE = 'America/Mexico_City'
USE_I18N = True
USE_TZ = True


# --- Archivos estáticos (WhiteNoise) y multimedia (local o AWS S3) -------------

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Con AWS_STORAGE_BUCKET_NAME definido, las imágenes subidas van a S3
# (el disco de Render es efímero). Sin él, se guardan en MEDIA_ROOT.
AWS_STORAGE_BUCKET_NAME = os.environ.get('AWS_STORAGE_BUCKET_NAME', '')
USAR_S3 = bool(AWS_STORAGE_BUCKET_NAME)

if USAR_S3:
    AWS_S3_REGION_NAME = os.environ.get('AWS_S3_REGION_NAME', 'us-east-1')
    AWS_S3_CUSTOM_DOMAIN = os.environ.get('AWS_S3_CUSTOM_DOMAIN') or None
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = env_bool('AWS_QUERYSTRING_AUTH', por_defecto=True)
    AWS_S3_FILE_OVERWRITE = False
    # boto3 lee AWS_ACCESS_KEY_ID y AWS_SECRET_ACCESS_KEY directamente del entorno.
    ALMACENAMIENTO_MEDIA = {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': {'location': 'media'},
    }
else:
    ALMACENAMIENTO_MEDIA = {'BACKEND': 'django.core.files.storage.FileSystemStorage'}

# El almacenamiento con manifiesto exige haber ejecutado collectstatic, así que
# solo se usa en producción (no en DEBUG ni al correr `manage.py test`).
STORAGES = {
    'default': ALMACENAMIENTO_MEDIA,
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage'
            if DEBUG or EJECUTANDO_TESTS
            else 'whitenoise.storage.CompressedManifestStaticFilesStorage'
        ),
    },
}


# --- Membresía VIP (docs/IOT_VIP_SPEC.md) -------------------------------------
# Fracciones como texto para convertirlas a Decimal sin errores de float.
# Son reglas de negocio, no credenciales: viven aquí y no en variables de entorno.

VIP_DESCUENTO = '0.20'          # Sweet Plan vigente
VIP_DESCUENTO_CUMPLE = '0.50'   # Sweet Plan vigente, el día de su cumpleaños


# --- Correo --------------------------------------------------------------------

MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}


# --- Logs (Render muestra la salida estándar) ---------------------------------

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': os.environ.get('LOG_LEVEL', 'INFO')},
}
