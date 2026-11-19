"""Rutas raíz del proyecto: cada app declara las suyas en su propio urls.py."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpRequest, HttpResponse
from django.urls import include, path


def healthz(request: HttpRequest) -> HttpResponse:
    """Health check de Render y ping del ESP32 (mantiene despierta la instancia gratuita).

    No toca la base de datos ni la sesión: solo confirma que el proceso responde.
    """
    return HttpResponse('ok', content_type='text/plain')


urlpatterns = [
    path('admin/', admin.site.urls),
    path('healthz', healthz, name='healthz'),
    path('', include('usuarios.urls')),
    path('', include('iot.urls')),
    path('', include('tienda.urls')),
]

# En desarrollo, Django sirve las imágenes subidas desde MEDIA_ROOT.
# En producción se sirven desde S3 (ver settings.USAR_S3).
if settings.DEBUG and not settings.USAR_S3:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
