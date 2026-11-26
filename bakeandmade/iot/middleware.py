"""Middleware que mide la actividad del cliente en el kiosco."""

from __future__ import annotations

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from .models import Terminal
from .sesion import CLAVE_TERMINAL

PREFIJOS_SIN_ACTIVIDAD = ('/api/', '/static/', '/media/', '/healthz')
"""El polling (/api/) y los archivos no son actividad del cliente."""


class ActividadKioscoMiddleware:
    """Actualiza `Terminal.ultima_actividad` cada vez que el kiosco navega una página.

    Decisión de la especificación: solo cuentan las páginas navegadas. Si contara
    el polling, la sesión abierta por tarjeta nunca expiraría a los 5 minutos.
    Debe ir después de SessionMiddleware.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        """Registra la actividad antes de atender la petición."""
        codigo = request.session.get(CLAVE_TERMINAL) if hasattr(request, 'session') else None
        if codigo and not request.path.startswith(PREFIJOS_SIN_ACTIVIDAD):
            terminal = Terminal.objects.filter(codigo=codigo).first()
            if terminal is not None:
                terminal.registrar_actividad()
        return self.get_response(request)
