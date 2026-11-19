"""Vistas de la app iot: API del lector ESP32, vinculación y estado del kiosco.

Vistas delgadas (docs/ARCHITECTURE.md): validan la petición HTTP y delegan en
`Terminal` (iot/models.py) y en `iot.sesion`.
"""

from __future__ import annotations

import hmac
import json
from typing import Any

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .models import LecturaRFID, Terminal
from . import sesion

ESTADO_HTTP = {
    LecturaRFID.OK: 200,
    LecturaRFID.SIN_SWEET: 403,
    LecturaRFID.DESCONOCIDA: 404,
}

LONGITUD_MAXIMA_UID = 64
"""Límite defensivo del texto recibido antes de normalizarlo."""


def _token_valido(request: HttpRequest) -> bool:
    """Compara `Authorization: Token <valor>` contra IOT_DEVICE_TOKEN en tiempo constante.

    Sin IOT_DEVICE_TOKEN configurado, ningún token es válido.
    """
    esperado = settings.IOT_DEVICE_TOKEN
    tipo, _, recibido = request.headers.get('Authorization', '').partition(' ')
    if not esperado or tipo != 'Token' or not recibido:
        return False
    return hmac.compare_digest(recibido.encode(), esperado.encode())


def _leer_lectura(request: HttpRequest) -> tuple[str, str] | None:
    """Extrae (uid, terminal) del JSON del ESP32, o None si el cuerpo no es válido."""
    try:
        datos: Any = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(datos, dict):
        return None
    uid, terminal = datos.get('uid'), datos.get('terminal')
    if not isinstance(uid, str) or not isinstance(terminal, str):
        return None
    if not uid.strip() or len(uid) > LONGITUD_MAXIMA_UID:
        return None
    return uid, terminal


@csrf_exempt  # El ESP32 no tiene cookie ni token CSRF; se autentica con IOT_DEVICE_TOKEN.
@require_POST
def rfid_scan(request: HttpRequest) -> JsonResponse:
    """POST /api/rfid/scan/: el ESP32 informa qué tarjeta leyó en qué terminal."""
    if not _token_valido(request):
        return JsonResponse({'status': 'no_autorizado'}, status=401)

    lectura = _leer_lectura(request)
    if lectura is None:
        return JsonResponse({'status': 'peticion_invalida'}, status=400)
    uid, codigo = lectura

    terminal = Terminal.objects.filter(codigo=codigo).first()
    if terminal is None:
        return JsonResponse({'status': 'terminal_desconocida'}, status=400)

    resultado, tarjeta = terminal.registrar_lectura(uid)
    respuesta: dict[str, str] = {'status': resultado}
    if tarjeta is not None:
        respuesta['cliente'] = tarjeta.usuario.first_name or tarjeta.usuario.get_username()
    return JsonResponse(respuesta, status=ESTADO_HTTP[resultado])


def kiosco(request: HttpRequest, codigo: str) -> HttpResponse:
    """GET /kiosco/<codigo>/: el staff vincula este navegador a una terminal.

    Al vincular se cierra la sesión del staff, para que la computadora quede
    lista para clientes sin pasos extra.
    """
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    if not request.user.is_staff:
        raise PermissionDenied('Solo el personal de la tienda puede vincular un kiosco.')

    terminal = get_object_or_404(Terminal, codigo=codigo)
    sesion.vincular(request, terminal)
    return redirect('inicio')


@require_GET
def estado(request: HttpRequest) -> JsonResponse:
    """GET /api/iot/estado/: polling del kiosco; aquí ocurre el inicio de sesión por tarjeta."""
    terminal = sesion.terminal_de(request)
    if terminal is None:
        return JsonResponse({'status': 'sin_terminal'}, status=404)

    if terminal.expirar_si_inactiva():
        terminal.refresh_from_db()
    recargar = sesion.sincronizar(request, terminal)
    return JsonResponse({
        'version': terminal.version,
        'recargar': recargar,
        'rechazo': terminal.ultimo_rechazo,
    })


@require_POST
def salir(request: HttpRequest) -> JsonResponse:
    """POST /api/iot/salir/: botón "Salir" del kiosco (con CSRF).

    Quita la tarjeta de la terminal y cierra en el acto la sesión que abrió.
    """
    terminal = sesion.terminal_de(request)
    if terminal is None:
        return JsonResponse({'status': 'sin_terminal'}, status=404)

    terminal.salir()
    recargar = sesion.sincronizar(request, terminal)
    return JsonResponse({'version': terminal.version, 'recargar': recargar})
