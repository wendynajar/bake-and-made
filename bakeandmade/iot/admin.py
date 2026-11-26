"""Registro de los modelos IoT en el panel de administración."""

from django.contrib import admin

from .models import LecturaRFID, TarjetaRFID, Terminal


@admin.register(TarjetaRFID)
class TarjetaRFIDAdmin(admin.ModelAdmin):
    """Inventario de tarjetas: aquí se reasigna o desactiva una tarjeta perdida."""

    list_display = ('uid', 'usuario', 'activa', 'entregada_en')
    list_filter = ('activa',)
    search_fields = ('uid', 'usuario__username', 'usuario__email')
    list_select_related = ('usuario',)
    raw_id_fields = ('usuario',)


@admin.register(Terminal)
class TerminalAdmin(admin.ModelAdmin):
    """Estado de cada computadora del kiosco."""

    list_display = ('codigo', 'tarjeta_activa', 'ultima_actividad', 'ultimo_rechazo', 'version')
    readonly_fields = ('version',)


@admin.register(LecturaRFID)
class LecturaRFIDAdmin(admin.ModelAdmin):
    """Bitácora de solo lectura: las filas las escribe la API del lector."""

    list_display = ('creada', 'terminal', 'uid', 'resultado')
    list_filter = ('resultado', 'terminal')
    search_fields = ('uid',)

    def has_add_permission(self, request: object) -> bool:
        """Nadie crea lecturas a mano."""
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        """La bitácora no se edita."""
        return False
