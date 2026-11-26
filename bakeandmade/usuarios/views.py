"""Vistas de autenticación propias (login usa la vista de Django)."""

from typing import Any

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LogoutView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from iot import sesion as sesion_kiosco

from .forms import RegistroUsuarioForm


class CerrarSesionView(LogoutView):
    """Cierre de sesión que, en un kiosco, conserva la vinculación con su terminal.

    El LogoutView de Django vacía toda la sesión, lo que desvincularía la
    computadora de la tienda. Fuera del kiosco se comporta igual que el original.
    """

    def post(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        """Cierra la sesión; si es un kiosco, conserva la terminal."""
        if sesion_kiosco.terminal_de(request) is None:
            return super().post(request, *args, **kwargs)
        sesion_kiosco.cerrar_sesion_en_kiosco(request)
        return redirect(self.get_success_url())


def registro(request: HttpRequest) -> HttpResponse:
    """Crea la cuenta del cliente e inicia su sesión automáticamente."""
    if request.user.is_authenticated:
        return redirect('inicio')

    if request.method == 'POST':
        formulario = RegistroUsuarioForm(request.POST)
        if formulario.is_valid():
            usuario = formulario.save()
            login(request, usuario)
            messages.success(
                request,
                'Tu cuenta se ha creado correctamente. ¡Bienvenido a Bake & Made!',
            )
            return redirect('inicio')
    else:
        formulario = RegistroUsuarioForm()

    return render(request, 'usuarios/registro.html', {'formulario': formulario})
