"""Variables VIP y del kiosco disponibles en todas las plantillas."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.conf import settings
from django.http import HttpRequest

from iot.sesion import CLAVE_LOGIN_TARJETA, CLAVE_TERMINAL, CLAVE_VERSION
from tienda.models import Pedido
from tienda.peticion import descuento_de_peticion


def vip(request: HttpRequest) -> dict[str, Any]:
    """Estado VIP del usuario y, si el navegador es un kiosco, los datos del polling.

    - vip_activo / vip_descuento / vip_motivo: para la pestaña "Membresía VIP" y
      la etiqueta "VIP −20 %" o "Cumpleaños −50 %".
    - es_kiosco / kiosco_login_tarjeta / kiosco_version / kiosco_poll_ms: para
      cargar polling.js y la barra de "Salir" solo en las computadoras de la tienda.
    """
    descuento, motivo = descuento_de_peticion(request)
    sesion = getattr(request, 'session', {})
    return {
        'vip_activo': descuento > 0,
        'vip_descuento': descuento,
        'vip_porcentaje': int(descuento * Decimal('100')),
        'vip_motivo': motivo,
        'vip_es_cumpleanios': motivo == Pedido.MOTIVO_CUMPLEANIOS,
        'es_kiosco': bool(sesion.get(CLAVE_TERMINAL)),
        'kiosco_login_tarjeta': bool(sesion.get(CLAVE_LOGIN_TARJETA)),
        'kiosco_version': sesion.get(CLAVE_VERSION, 0),
        'kiosco_poll_ms': settings.IOT_POLL_SEGUNDOS * 1000,
    }
