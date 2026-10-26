from django.contrib import admin
from .models import (
    Suscripcion, RecordatorioEvento, CategoriaIngrediente,
    Ingrediente, Menu, DetallesMenu, CupcakePersonalizado,
    CupcakeIngredientes, Pedido, DetallePedido, ExperienciaQR, CategoriaProducto
)

@admin.register(CategoriaIngrediente)
class CategoriaIngredienteAdmin(admin.ModelAdmin):
    list_display = ('id', 'nombre')
    search_fields = ('nombre',)

@admin.register(Ingrediente)
class IngredienteAdmin(admin.ModelAdmin):
    list_display = (
        'nombre',
        'categoria',
        'precio_adicional',
        'activo',
        'stock_disponible',
    )
    list_filter = ('categoria', 'activo', 'solo_suscriptores')
    search_fields = ('nombre',)
    list_editable = ('activo',)

@admin.register(Menu)
class MenuAdmin(admin.ModelAdmin):
    list_display = (
        'nombre_producto',
        'categoria',
        'precio_base',
        'stock',
        'disponible'
    )

    list_filter = (
        'categoria',
        'disponible'
    )

    search_fields = (
        'nombre_producto',
        'descripcion'
    )

    list_editable = (
        'stock',
        'disponible'
    )

    list_per_page = 20

@admin.register(Suscripcion)
class SuscripcionAdmin(admin.ModelAdmin):
    list_display = (
        'usuario',
        'estado',
        'fecha_inicio',
        'fecha_fin',
        'monto_mensual',
    )
    list_filter = ('estado',)
    search_fields = (
        'usuario__username',
        'usuario__first_name',
        'usuario__last_name',
        'usuario__email',
    )
    list_select_related = ('usuario',)
    
admin.site.register(RecordatorioEvento)
admin.site.register(DetallesMenu)
admin.site.register(CupcakePersonalizado)
admin.site.register(CupcakeIngredientes)
admin.site.register(Pedido)
admin.site.register(DetallePedido)
admin.site.register(ExperienciaQR)
admin.site.register(CategoriaProducto)