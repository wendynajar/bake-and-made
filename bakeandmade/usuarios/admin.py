"""Registro de los modelos de usuarios en el panel de administración."""

from django.contrib import admin

from .models import PerfilVIP


@admin.register(PerfilVIP)
class PerfilVIPAdmin(admin.ModelAdmin):
    """El admin es la única vía para corregir un cumpleaños ya registrado."""

    list_display = ('usuario', 'telefono', 'fecha_nacimiento', 'cumple_registrado_en')
    search_fields = ('usuario__username', 'usuario__email', 'usuario__first_name', 'telefono')
    list_select_related = ('usuario',)
    raw_id_fields = ('usuario',)
