"""Vistas de autenticación propias (login y logout usan las vistas de Django)."""

from django.contrib import messages
from django.contrib.auth import login
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from .forms import RegistroUsuarioForm


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
