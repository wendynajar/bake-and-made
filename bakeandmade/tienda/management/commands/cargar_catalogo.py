from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from tienda.models import Menu, CategoriaProducto


PRODUCTOS = [
    ("Cupcake red velvet", "Cupcakes", "45.00",
     "Cupcake de cacao suave con crema de queso y decoración artesanal."),
    ("Cupcake de fresa", "Cupcakes", "40.00",
     "Cupcake esponjoso de vainilla con crema de fresa."),
    ("Cupcake de zanahoria", "Cupcakes", "42.00",
     "Cupcake de zanahoria con especias y betún de queso crema."),
    ("Galleta con chispas de chocolate", "Galletas", "28.00",
     "Galleta artesanal con chispas de chocolate semiamargo."),
    ("Galleta red velvet", "Galletas", "32.00",
     "Galleta suave de cacao con chocolate blanco."),
    ("Galleta de mantequilla", "Galletas", "25.00",
     "Galleta tradicional de mantequilla con textura delicada."),
    ("Brownie de chocolate", "Postres personalizados", "45.00",
     "Brownie de chocolate intenso con interior suave."),
    ("Cheesecake de fresa", "Postres personalizados", "65.00",
     "Cheesecake cremoso con cobertura de fresa."),
    ("Pastel de chocolate", "Pasteles", "450.00",
     "Pastel de chocolate con relleno y cobertura de ganache."),
    ("Pastel de tres leches", "Pasteles", "420.00",
     "Pastel tradicional de tres leches con crema batida."),
    ("Pastel de zanahoria", "Pasteles", "480.00",
     "Pastel de zanahoria con nuez y betún de queso crema."),
    ("Caja de 6 cupcakes", "Paquetes especiales", "210.00",
     "Caja de seis cupcakes artesanales de sabores variados."),
    ("Caja de regalo dulce", "Paquetes especiales", "350.00",
     "Selección de postres artesanales para regalar."),
]


class Command(BaseCommand):
    help = "Carga el catálogo inicial de Bake & Made"

    @transaction.atomic
    def handle(self, *args, **options):
        creados = 0
        existentes = 0

        for nombre, categoria_nombre, precio, descripcion in PRODUCTOS:
            categoria, _ = CategoriaProducto.objects.get_or_create(
                nombre=categoria_nombre
            )

            if Menu.objects.filter(nombre_producto=nombre).exists():
                existentes += 1
                self.stdout.write(f"Ya existe: {nombre}")
                continue

            Menu.objects.create(
                nombre_producto=nombre,
                descripcion=descripcion,
                precio_base=Decimal(precio),
                disponible=True,
                categoria=categoria,
                stock=20
            )

            creados += 1
            self.stdout.write(
                self.style.SUCCESS(f"Creado: {nombre}")
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Catálogo cargado. Nuevos: {creados}. "
                f"Existentes: {existentes}."
            )
        )
