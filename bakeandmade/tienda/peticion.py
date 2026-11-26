"""Plan y descuento del usuario, calculados una sola vez por petición HTTP.

`Suscripcion.objects.plan_de()` lanza un UPDATE (expira suscripciones vencidas)
y lo necesitan varios lugares en la misma petición: la barra (context
processors), el catálogo y el carrito. Guardar el resultado en el `request`
evita repetir ese UPDATE (hallazgo #11, en parte).
"""

from __future__ import annotations

from decimal import Decimal

from django.http import HttpRequest
from django.utils import timezone

from usuarios.models import SIN_DESCUENTO, PerfilVIP

from .models import PLAN_SWEET, Suscripcion

_ATRIBUTO_PLAN = '_bakeandmade_plan'
_ATRIBUTO_DESCUENTO = '_bakeandmade_descuento'


def plan_de_peticion(request: HttpRequest) -> str:
    """PLAN_SWEET o PLAN_BASIC del usuario de la petición (memorizado)."""
    if not hasattr(request, _ATRIBUTO_PLAN):
        setattr(request, _ATRIBUTO_PLAN, Suscripcion.objects.plan_de(request.user))
    return getattr(request, _ATRIBUTO_PLAN)


def descuento_de_peticion(request: HttpRequest) -> tuple[Decimal, str]:
    """(fracción, motivo) del descuento del usuario de la petición (memorizado).

    Aplica la misma regla que `tienda.models.descuento_para`, reutilizando el plan
    ya calculado para no consultar dos veces la suscripción.
    """
    if not hasattr(request, _ATRIBUTO_DESCUENTO):
        if plan_de_peticion(request) != PLAN_SWEET:
            descuento = SIN_DESCUENTO
        else:
            perfil = (
                PerfilVIP.objects.filter(usuario=request.user).first()
                or PerfilVIP(usuario=request.user)
            )
            descuento = perfil.descuento_vigente(timezone.localdate(), sweet_vigente=True)
        setattr(request, _ATRIBUTO_DESCUENTO, descuento)
    return getattr(request, _ATRIBUTO_DESCUENTO)
