"""Acceso al carrito guardado en la sesión.

El carrito no es un modelo: vive en `request.session` con dos claves:
- CLAVE_CARRITO: {"<id de Menu>": cantidad}
- CLAVE_PERSONALIZADOS: lista de dicts con los cupcakes del asistente
Centralizar las claves aquí evita que vistas y context processors diverjan.
"""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest

CLAVE_CARRITO = 'carrito'
CLAVE_PERSONALIZADOS = 'carrito_personalizados'


def obtener_carrito(request: HttpRequest) -> dict[str, Any]:
    """Productos del catálogo en el carrito ({id: cantidad})."""
    carrito = request.session.get(CLAVE_CARRITO, {})
    return carrito if isinstance(carrito, dict) else {}


def obtener_personalizados(request: HttpRequest) -> list[dict[str, Any]]:
    """Cupcakes personalizados en el carrito."""
    personalizados = request.session.get(CLAVE_PERSONALIZADOS, [])
    return personalizados if isinstance(personalizados, list) else []


def _cantidad_valida(valor: Any) -> int:
    """Devuelve la cantidad si es un entero positivo; 0 en otro caso."""
    return valor if type(valor) is int and valor > 0 else 0


def contar_articulos(request: HttpRequest) -> int:
    """Número total de unidades en el carrito (catálogo + personalizados)."""
    normales = sum(_cantidad_valida(c) for c in obtener_carrito(request).values())
    personalizados = sum(
        _cantidad_valida(cupcake.get('cantidad', 1))
        for cupcake in obtener_personalizados(request)
        if isinstance(cupcake, dict)
    )
    return normales + personalizados
