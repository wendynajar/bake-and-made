"""Configuración de la app de usuarios (registro, inicio y cierre de sesión)."""

from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    """Autenticación de clientes. Usa el modelo User nativo de Django (sin modelos propios)."""

    name = 'usuarios'
    verbose_name = 'Usuarios'
