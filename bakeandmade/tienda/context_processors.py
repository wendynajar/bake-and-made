"""Variables disponibles en todas las plantillas."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from .carrito import contar_articulos
from .models import PLAN_SWEET, PRECIO_SWEET_PLAN, Suscripcion


def contador_carrito(request: HttpRequest) -> dict[str, Any]:
    """Contador del carrito y plan del usuario para la barra de navegación.

    Nota: consultar el plan expira suscripciones vencidas (un UPDATE por
    petición de usuario autenticado). A futuro conviene moverlo a un cron job.
    """
    plan = Suscripcion.objects.plan_de(request.user)
    return {
        'contador_carrito': contar_articulos(request),
        'plan_usuario': plan,
        'es_plan_sweet': plan == PLAN_SWEET,
        'precio_sweet_plan': PRECIO_SWEET_PLAN,
    }
