"""Variables disponibles en todas las plantillas."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest

from .carrito import contar_articulos
from .models import PLAN_SWEET, PRECIO_SWEET_PLAN
from .peticion import plan_de_peticion


def contador_carrito(request: HttpRequest) -> dict[str, Any]:
    """Contador del carrito y plan del usuario para la barra de navegación.

    El plan se calcula una sola vez por petición (`tienda.peticion`), aunque
    también lo usen el context processor VIP y las vistas.
    """
    plan = plan_de_peticion(request)
    return {
        'contador_carrito': contar_articulos(request),
        'plan_usuario': plan,
        'es_plan_sweet': plan == PLAN_SWEET,
        'precio_sweet_plan': PRECIO_SWEET_PLAN,
    }
