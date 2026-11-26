"""Filtros de plantilla para el asistente de cupcakes."""

from typing import Any

from django import template

register = template.Library()


@register.filter
def dict_get(dictionary: dict[str, Any] | None, key: str) -> Any:
    """Permite `{{ selecciones|dict_get:paso.slug }}`: las plantillas de Django no indexan con variables."""
    if not dictionary:
        return None
    return dictionary.get(key)
