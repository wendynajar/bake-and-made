"""Configuración de la app tienda (catálogo, carrito, pedidos, personalización, suscripciones)."""

from django.apps import AppConfig


class TiendaConfig(AppConfig):
    """App principal de comercio electrónico de Bake & Made."""

    name = 'tienda'
    verbose_name = 'Tienda'
