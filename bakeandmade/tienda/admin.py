from django.contrib import admin
from .models import (
    Suscripcion, RecordatorioEvento, CategoriaIngrediente,
    Ingrediente, Menu, DetallesMenu, CupcakePersonalizado,
    CupcakeIngredientes, Pedido, DetallePedido, ExperienciaQR, CategoriaProducto
)

admin.site.register(Suscripcion)
admin.site.register(RecordatorioEvento)
admin.site.register(CategoriaIngrediente)
admin.site.register(Ingrediente)

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

admin.site.register(DetallesMenu)
admin.site.register(CupcakePersonalizado)
admin.site.register(CupcakeIngredientes)
admin.site.register(Pedido)
admin.site.register(DetallePedido)
admin.site.register(ExperienciaQR)
admin.site.register(CategoriaProducto)