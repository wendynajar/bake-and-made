"""Sincronización de la sesión del navegador del kiosco con su `Terminal`.

El ESP32 no tiene la cookie de sesión del navegador, así que no puede iniciar
sesión por sí mismo: solo cambia el estado de la `Terminal`. La página del kiosco
consulta `/api/iot/estado/` cada pocos segundos y esa petición, que sí trae la
cookie, aplica aquí el cambio (docs/IOT_VIP_SPEC.md, "Sincronización de la sesión").

Claves que usa este módulo en `request.session`:
- CLAVE_TERMINAL: código de la terminal a la que está vinculado el navegador.
- CLAVE_VERSION: última `Terminal.version` que esta sesión ya procesó.
- CLAVE_LOGIN_TARJETA: True si la sesión actual la abrió una tarjeta.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import login, logout
from django.http import HttpRequest

from tienda.carrito import CLAVE_CARRITO, CLAVE_PERSONALIZADOS

from .models import Terminal

CLAVE_TERMINAL = 'terminal'
CLAVE_VERSION = 'iot_version'
CLAVE_LOGIN_TARJETA = 'login_por_tarjeta'

CLAVES_DEL_KIOSCO = (CLAVE_TERMINAL, CLAVE_VERSION)
"""Sobreviven a cualquier cierre de sesión: el navegador sigue vinculado a su terminal."""

CLAVES_DEL_CARRITO = (CLAVE_CARRITO, CLAVE_PERSONALIZADOS)
"""Sobreviven al inicio de sesión por tarjeta (el cliente arma el carrito y luego pasa la tarjeta)."""

BACKEND = 'django.contrib.auth.backends.ModelBackend'


def terminal_de(request: HttpRequest) -> Terminal | None:
    """Terminal vinculada a este navegador, o None si no es un kiosco."""
    codigo = request.session.get(CLAVE_TERMINAL)
    if not codigo:
        return None
    return Terminal.objects.select_related('tarjeta_activa__usuario').filter(codigo=codigo).first()


def vincular(request: HttpRequest, terminal: Terminal) -> None:
    """Vincula el navegador a la terminal y cierra la sesión de quien lo vinculó (staff).

    La versión actual se marca como ya procesada para que un estado anterior
    (una tarjeta activa o un rechazo viejo) no se aplique a este navegador.
    """
    _cerrar_sesion(request)
    request.session[CLAVE_TERMINAL] = terminal.codigo
    request.session[CLAVE_VERSION] = terminal.version


def sincronizar(request: HttpRequest, terminal: Terminal) -> bool:
    """Ajusta la sesión al estado de la terminal y devuelve True si cambió de usuario.

    Reglas (solo se aplican cuando la terminal tiene una versión nueva para esta
    sesión, salvo la 3, que depende del estado):
    1. Tarjeta activa de otro usuario (o sesión anónima): inicia la sesión del
       dueño conservando el carrito y la terminal.
    2. Rechazo (tarjeta desconocida o sin Sweet): cierra cualquier sesión, también
       una iniciada con contraseña.
    3. Sin tarjeta activa y la sesión la abrió una tarjeta (Salir o expiración):
       cierra la sesión; el carrito se vacía a propósito.
    """
    version_nueva = request.session.get(CLAVE_VERSION) != terminal.version
    tarjeta = terminal.tarjeta_activa
    usuario = request.user
    cambio = False

    if tarjeta is not None and tarjeta.usuario is not None:
        if version_nueva:
            if not usuario.is_authenticated or usuario.pk != tarjeta.usuario_id:
                _iniciar_sesion_por_tarjeta(request, tarjeta.usuario)
                cambio = True
            else:
                # El dueño ya estaba dentro con contraseña: ahora su sesión es de tarjeta.
                request.session[CLAVE_LOGIN_TARJETA] = True
    elif usuario.is_authenticated:
        if version_nueva and terminal.ultimo_rechazo:
            _cerrar_sesion(request)
            cambio = True
        elif request.session.get(CLAVE_LOGIN_TARJETA):
            _cerrar_sesion(request)
            cambio = True

    request.session[CLAVE_VERSION] = terminal.version
    return cambio


def cerrar_sesion_en_kiosco(request: HttpRequest) -> None:
    """Cierre de sesión normal (botón de la barra) que no desvincula el kiosco.

    Si la sesión la abrió una tarjeta, también la quita de la terminal para que
    el siguiente polling no vuelva a abrir la misma cuenta.
    """
    terminal = terminal_de(request)
    if terminal is not None and request.session.get(CLAVE_LOGIN_TARJETA):
        terminal.salir()
        request.session[CLAVE_VERSION] = terminal.version
    _cerrar_sesion(request)


def _iniciar_sesion_por_tarjeta(request: HttpRequest, usuario: Any) -> None:
    """login() sin contraseña conservando carrito y terminal.

    Django vacía la sesión al cambiar de usuario (flush), por eso se guardan y
    restauran las claves del carrito y del kiosco.
    """
    conservar = _copiar(request, CLAVES_DEL_KIOSCO + CLAVES_DEL_CARRITO)
    login(request, usuario, backend=BACKEND)
    request.session.update(conservar)
    request.session[CLAVE_LOGIN_TARJETA] = True


def _cerrar_sesion(request: HttpRequest) -> None:
    """logout() que solo conserva la vinculación con la terminal (no el carrito)."""
    conservar = _copiar(request, CLAVES_DEL_KIOSCO)
    logout(request)
    request.session.update(conservar)


def _copiar(request: HttpRequest, claves: tuple[str, ...]) -> dict[str, Any]:
    """Copia de las claves presentes en la sesión."""
    return {clave: request.session[clave] for clave in claves if clave in request.session}
