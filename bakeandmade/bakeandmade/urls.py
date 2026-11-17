"""Rutas raíz del proyecto: cada app declara las suyas en su propio urls.py."""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('usuarios.urls')),
    path('', include('tienda.urls')),
]

# En desarrollo, Django sirve las imágenes subidas desde MEDIA_ROOT.
# En producción se sirven desde S3 (ver settings.USAR_S3).
if settings.DEBUG and not settings.USAR_S3:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
