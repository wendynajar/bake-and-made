"""Configuración de la app de usuarios (registro, inicio y cierre de sesión)."""

from django.apps import AppConfig


class UsuariosConfig(AppConfig):
    """Autenticación de clientes con el User nativo de Django, más su perfil VIP."""

    name = 'usuarios'
    verbose_name = 'Usuarios'
