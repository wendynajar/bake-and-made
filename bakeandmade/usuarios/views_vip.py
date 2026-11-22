"""Página de la membresía VIP y sus APIs (docs/IOT_VIP_SPEC.md, fase 8).

VIP = Sweet Plan vigente, sin importar si la sesión se abrió con contraseña o
con la tarjeta. Las APIs usan siempre `request.user`: nunca leen un id de
usuario enviado por el navegador. Vistas delgadas: la lógica vive en
`PerfilVIP`, `RecordatorioEvento` y `ExperienciaQR`.
"""

from __future__ import annotations

import datetime
import json
from typing import Any

import segno
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from iot.models import TarjetaRFID
from tienda.models import (
    PLAN_SWEET,
    ExperienciaQR,
    RecordatorioEvento,
    Suscripcion,
    misma_fecha_en_anio,
)
from tienda.peticion import plan_de_peticion

from .models import CumpleYaRegistrado, FechaCumpleInvalida, PerfilVIP

MAX_DIAS_RANGO = 400
"""Rango máximo que puede pedir el calendario (FullCalendar pide ~6 semanas)."""

COLOR_QR = '#582639'


# =============================================================================
# Página /vip/
# =============================================================================

@login_required
def pagina_vip(request: HttpRequest) -> HttpResponse:
    """Membresía VIP: vigencia, descuento de hoy, tarjeta, cumpleaños, calendario y video."""
    if plan_de_peticion(request) != PLAN_SWEET:
        return redirect('suscripcion')

    hoy = timezone.localdate()
    perfil = PerfilVIP.objects.filter(usuario=request.user).first() or PerfilVIP(usuario=request.user)
    experiencia = ExperienciaQR.objects.vigente_de(request.user)
    url_qr = (
        request.build_absolute_uri(reverse('video_qr', args=[experiencia.codigo_unico]))
        if experiencia else ''
    )
    return render(request, 'usuarios/vip.html', {
        'perfil': perfil,
        'suscripcion': Suscripcion.objects.vigente_para(request.user),
        'tarjeta': TarjetaRFID.objects.filter(usuario=request.user).first(),
        'experiencia': experiencia,
        'url_qr': url_qr,
        'qr_svg': _qr_svg(url_qr) if url_qr else '',
        'tipos_fecha': RecordatorioEvento.TIPOS,
        'hoy': hoy,
        'dias_cumple': perfil.dias_para_cumpleanios(hoy),
    })


def _qr_svg(url: str) -> str:
    """SVG en línea del QR que apunta a la URL pública del video."""
    return segno.make(url, error='m').svg_inline(scale=5, dark=COLOR_QR, border=2)


# =============================================================================
# APIs del calendario y del cumpleaños
# =============================================================================

def _rechazo_si_no_es_sweet(request: HttpRequest) -> JsonResponse | None:
    """403 si no hay sesión o el Sweet Plan no está vigente; None si puede pasar."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Inicia sesión para usar tu membresía VIP.'}, status=403)
    if plan_de_peticion(request) != PLAN_SWEET:
        return JsonResponse({'error': 'Tu Sweet Plan no está vigente.'}, status=403)
    return None


def _leer_json(request: HttpRequest) -> dict[str, Any] | None:
    """Cuerpo JSON como diccionario, o None si no es válido."""
    try:
        datos = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return datos if isinstance(datos, dict) else None


def _fecha_de_parametro(valor: str | None) -> datetime.date | None:
    """Fecha de los parámetros start/end de FullCalendar ("2026-10-26T00:00:00-06:00")."""
    try:
        return datetime.date.fromisoformat(valor[:10]) if valor else None
    except ValueError:
        return None


def _evento_json(evento: RecordatorioEvento, dia: datetime.date) -> dict[str, Any]:
    """Formato de evento que entiende FullCalendar."""
    return {
        'id': str(evento.pk),
        'title': evento.nombre_evento,
        'start': dia.isoformat(),
        'allDay': True,
        'classNames': [f'vip-evento-{evento.tipo}'],
        'extendedProps': {'tipo': evento.tipo, 'borrable': True},
    }


def _cumpleanios_json(perfil: PerfilVIP | None, desde: datetime.date, hasta: datetime.date) -> list[dict[str, Any]]:
    """El cumpleaños del usuario como evento fijo (no se puede borrar) en cada año del rango."""
    if perfil is None or perfil.fecha_nacimiento is None:
        return []
    eventos = []
    for anio in range(desde.year, hasta.year + 1):
        dia = misma_fecha_en_anio(perfil.fecha_nacimiento, anio)
        if desde <= dia < hasta:
            eventos.append({
                'id': f'cumple-{anio}',
                'title': 'Mi cumpleaños',
                'start': dia.isoformat(),
                'allDay': True,
                'classNames': ['vip-evento-mi-cumple'],
                'extendedProps': {'tipo': 'mi_cumpleanios', 'borrable': False},
            })
    return eventos


@require_http_methods(['GET', 'POST'])
def api_fechas(request: HttpRequest) -> JsonResponse:
    """GET: fechas del usuario en el rango pedido. POST: crea una fecha (201)."""
    rechazo = _rechazo_si_no_es_sweet(request)
    if rechazo is not None:
        return rechazo

    if request.method == 'POST':
        datos = _leer_json(request)
        if datos is None:
            return JsonResponse({'error': 'Petición inválida.'}, status=400)
        try:
            evento = RecordatorioEvento.crear_para(
                request.user, datos.get('nombre_evento'), datos.get('fecha_evento'), datos.get('tipo'),
            )
        except ValidationError as error:
            return JsonResponse({'errores': error.message_dict}, status=400)
        return JsonResponse(_evento_json(evento, evento.fecha_evento), status=201)

    hoy = timezone.localdate()
    desde = _fecha_de_parametro(request.GET.get('start')) or hoy.replace(month=1, day=1)
    hasta = _fecha_de_parametro(request.GET.get('end')) or hoy.replace(month=12, day=31)
    if not desde < hasta or (hasta - desde).days > MAX_DIAS_RANGO:
        return JsonResponse({'error': 'Rango de fechas inválido.'}, status=400)

    eventos = [
        _evento_json(evento, dia)
        for evento, dia in RecordatorioEvento.objects.de(request.user).ocurrencias(desde, hasta)
    ]
    perfil = PerfilVIP.objects.filter(usuario=request.user).first()
    return JsonResponse(eventos + _cumpleanios_json(perfil, desde, hasta), safe=False)


@require_http_methods(['DELETE'])
def api_fecha(request: HttpRequest, pk: int) -> HttpResponse:
    """DELETE: borra la fecha solo si es del usuario con sesión (404 si no)."""
    rechazo = _rechazo_si_no_es_sweet(request)
    if rechazo is not None:
        return rechazo
    borrados, _ = RecordatorioEvento.objects.de(request.user).filter(pk=pk).delete()
    if not borrados:
        return JsonResponse({'error': 'No existe esa fecha.'}, status=404)
    return HttpResponse(status=204)


@require_POST
def api_cumpleanios(request: HttpRequest) -> JsonResponse:
    """POST {"fecha": "AAAA-MM-DD"}: registra el cumpleaños una sola vez."""
    rechazo = _rechazo_si_no_es_sweet(request)
    if rechazo is not None:
        return rechazo

    datos = _leer_json(request)
    try:
        fecha = datetime.date.fromisoformat(datos['fecha']) if datos else None
    except (KeyError, TypeError, ValueError):
        fecha = None
    if fecha is None:
        return JsonResponse({'error': 'Elige una fecha válida.'}, status=400)

    try:
        PerfilVIP.de(request.user).registrar_cumpleanios(fecha, timezone.localdate())
    except CumpleYaRegistrado:
        return JsonResponse(
            {'error': 'Tu cumpleaños ya está registrado. Para corregirlo, pídelo en tienda.'},
            status=409,
        )
    except FechaCumpleInvalida:
        return JsonResponse({'error': 'La fecha no puede ser futura.'}, status=400)
    return JsonResponse({'fecha': fecha.isoformat()}, status=201)


# =============================================================================
# Video del QR (público: se abre desde el celular que escanea el código)
# =============================================================================

@require_GET
def video_qr(request: HttpRequest, codigo: str) -> HttpResponse:
    """Redirige a la URL firmada del video en S3 (vence en 1 h); 404 si expiró.

    No exige sesión: el código es un token aleatorio y no adivinable.
    """
    experiencia = ExperienciaQR.objects.vigentes().filter(codigo_unico=codigo).first()
    if experiencia is None or not experiencia.video:
        raise Http404('El video no existe o ya expiró.')
    return redirect(experiencia.video.url)
