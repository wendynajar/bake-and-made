from django.contrib import admin
from .models import (
    Suscripcion, RecordatorioEvento, CategoriaIngrediente,
    Ingrediente, Menu, DetallesMenu, CupcakePersonalizado,
    CupcakeIngredientes, Pedido, DetallePedido, ExperienciaQR
)

admin.site.register(Suscripcion)
admin.site.register(RecordatorioEvento)
admin.site.register(CategoriaIngrediente)
admin.site.register(Ingrediente)
admin.site.register(Menu)
admin.site.register(DetallesMenu)
admin.site.register(CupcakePersonalizado)
admin.site.register(CupcakeIngredientes)
admin.site.register(Pedido)
admin.site.register(DetallePedido)
admin.site.register(ExperienciaQR)