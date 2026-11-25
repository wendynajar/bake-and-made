"""Comando `cargar_catalogo`: datos iniciales del catálogo (se puede ejecutar varias veces).

Usa get_or_create, por lo que es seguro incluirlo en el build de Render.
Crea lo que falte y no modifica lo existente; las únicas excepciones son
completar la imagen y la receta (`DetallesMenu`) de un producto que no tenga.
"""

from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from tienda.models import (
    CategoriaIngrediente,
    CategoriaProducto,
    DetallesMenu,
    Ingrediente,
    Menu,
)


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

IMAGENES = {
    "Cupcake red velvet": "productos/crv.jpg",
    "Cupcake de fresa": "productos/cf1.jpg",
    "Cupcake de zanahoria": "productos/cz.jpg",

    "Galleta con chispas de chocolate": "productos/gcc.jpg",
    "Galleta red velvet": "productos/grv.jpg",
    "Galleta de mantequilla": "productos/gm.jpg",

    "Brownie de chocolate": "productos/bc.jpg",
    "Cheesecake de fresa": "productos/cf.jpg",

    "Pastel de chocolate": "productos/pc.jpg",
    "Pastel de tres leches": "productos/ptl.jpg",
    "Pastel de zanahoria": "productos/pz.jpg",

    "Caja de 6 cupcakes": "productos/csc.jpg",
    "Caja de regalo dulce": "productos/crd.jpg",
}
CATEGORIAS_INGREDIENTES = [
    "Base",
    "Relleno",
    "Cobertura",
    "Topping",
]

INGREDIENTES_EXCLUSIVOS = {
    ("Base", "Red velvet"),
    ("Relleno", "Dulce de leche"),
    ("Cobertura", "Queso crema"),
    ("Topping", "Fresas"),
}
"""Un ingrediente premium por categoría, solo para el Sweet Plan (hallazgo #9).

Solo se aplica al crear el ingrediente; después el admin manda. La migración
tienda.0007 los marca en las bases que ya existían.
"""

INGREDIENTES = [
    # Categoría, nombre, precio adicional
    ("Base", "Vainilla", "0.00"),
    ("Base", "Chocolate", "5.00"),
    ("Base", "Red velvet", "8.00"),
    ("Base", "Zanahoria", "6.00"),

    ("Relleno", "Crema de vainilla", "0.00"),
    ("Relleno", "Chocolate", "5.00"),
    ("Relleno", "Dulce de leche", "6.00"),
    ("Relleno", "Fresa", "5.00"),

    ("Cobertura", "Buttercream de vainilla", "0.00"),
    ("Cobertura", "Buttercream de chocolate", "5.00"),
    ("Cobertura", "Queso crema", "7.00"),

    ("Topping", "Chispas de chocolate", "2.00"),
    ("Topping", "Galleta triturada", "3.00"),
    ("Topping", "Sprinkles de colores", "2.00"),
    ("Topping", "Fresas", "5.00"),
]

RECETAS: dict[str, list[tuple[str, str, int]]] = {
    # Producto: [(categoría del ingrediente, ingrediente, cantidad), ...]
    # Solo usa ingredientes de INGREDIENTES; "Chocolate" existe como Base y como
    # Relleno, por eso cada uno se identifica con su categoría. La cantidad está
    # en porciones de ingrediente: 1 por pieza individual, 10 por pastel y 6 por caja.
    "Cupcake red velvet": [
        ("Base", "Red velvet", 1),
        ("Cobertura", "Queso crema", 1),
    ],
    "Cupcake de fresa": [
        ("Base", "Vainilla", 1),
        ("Relleno", "Fresa", 1),
        ("Topping", "Fresas", 1),
    ],
    "Cupcake de zanahoria": [
        ("Base", "Zanahoria", 1),
        ("Cobertura", "Queso crema", 1),
    ],
    "Galleta con chispas de chocolate": [
        ("Base", "Vainilla", 1),
        ("Topping", "Chispas de chocolate", 1),
    ],
    "Galleta red velvet": [
        ("Base", "Red velvet", 1),
    ],
    "Galleta de mantequilla": [
        ("Base", "Vainilla", 1),
    ],
    "Brownie de chocolate": [
        ("Base", "Chocolate", 1),
        ("Relleno", "Chocolate", 1),
    ],
    "Cheesecake de fresa": [
        ("Topping", "Galleta triturada", 1),
        ("Cobertura", "Queso crema", 1),
        ("Relleno", "Fresa", 1),
    ],
    "Pastel de chocolate": [
        ("Base", "Chocolate", 10),
        ("Relleno", "Chocolate", 10),
        ("Cobertura", "Buttercream de chocolate", 10),
    ],
    "Pastel de tres leches": [
        ("Base", "Vainilla", 10),
        ("Relleno", "Crema de vainilla", 10),
        ("Cobertura", "Buttercream de vainilla", 10),
    ],
    "Pastel de zanahoria": [
        ("Base", "Zanahoria", 10),
        ("Cobertura", "Queso crema", 10),
    ],
    "Caja de 6 cupcakes": [
        ("Base", "Vainilla", 3),
        ("Base", "Chocolate", 3),
        ("Cobertura", "Buttercream de vainilla", 3),
        ("Cobertura", "Buttercream de chocolate", 3),
        ("Topping", "Sprinkles de colores", 6),
    ],
    "Caja de regalo dulce": [
        ("Base", "Vainilla", 2),
        ("Base", "Chocolate", 2),
        ("Topping", "Chispas de chocolate", 2),
        ("Topping", "Sprinkles de colores", 2),
    ],
}
"""Receta de cada producto del catálogo (tabla `DetallesMenu`).

Solo se aplica a productos sin receta: si alguien edita la receta en el admin,
`cargar_catalogo` ya no la toca.
"""


class Command(BaseCommand):
    """Carga el catálogo inicial de Bake & Made."""

    help = "Carga el catálogo inicial de Bake & Made"

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        """Crea categorías, ingredientes y productos que falten; no modifica los existentes."""
        creados = 0
        existentes = 0

        categorias_creadas = 0

        for nombre in CATEGORIAS_INGREDIENTES:
            categoria, creada = (
                CategoriaIngrediente.objects.get_or_create(
                    nombre=nombre
                )
            )

            if creada:
                categorias_creadas += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Categoría de ingrediente creada: {nombre}"
                    )
                )
            else:
                self.stdout.write(
                    f"La categoría de ingrediente ya existe: {nombre}"
                )

        ingredientes_creados = 0

        for categoria_nombre, nombre, precio in INGREDIENTES:
            categoria = CategoriaIngrediente.objects.get(
                nombre=categoria_nombre
            )

            ingrediente, creado = Ingrediente.objects.get_or_create(
                categoria=categoria,
                nombre=nombre,
                defaults={
                    "precio_adicional": Decimal(precio),
                    "stock_disponible": 100,
                    "solo_suscriptores": (
                        (categoria_nombre, nombre) in INGREDIENTES_EXCLUSIVOS
                    ),
                    "activo": True,
                },
            )

            if creado:
                ingredientes_creados += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Ingrediente creado: {nombre}"
                    )
                )
            else:
                self.stdout.write(
                    f"Ingrediente ya existente: {nombre}"
                )

        self.stdout.write(
            f"Ingredientes nuevos: {ingredientes_creados}"
        )

        for nombre, categoria_nombre, precio, descripcion in PRODUCTOS:
            categoria, _ = CategoriaProducto.objects.get_or_create(
                nombre=categoria_nombre
            )

            imagen = IMAGENES.get(nombre, "")
            producto = Menu.objects.filter(nombre_producto=nombre).first()

            if producto:
                # Solo completa la imagen si falta: la que se ponga en el admin manda.
                if imagen and not producto.imagen:
                    producto.imagen = imagen
                    producto.save(update_fields=["imagen"])
                    self.stdout.write(f"Imagen asignada: {nombre}")

                existentes += 1
                self.stdout.write(f"Ya existe: {nombre}")
                continue

            Menu.objects.create(
                nombre_producto=nombre,
                descripcion=descripcion,
                precio_base=Decimal(precio),
                disponible=True,
                categoria=categoria,
                stock=20,
                imagen=imagen,
            )

            creados += 1
            self.stdout.write(
                self.style.SUCCESS(f"Creado: {nombre}")
            )

        recetas_creadas = self._cargar_recetas()

        self.stdout.write(
            self.style.SUCCESS(
                f"Catálogo cargado. Nuevos: {creados}. "
                f"Existentes: {existentes}. Recetas nuevas: {recetas_creadas}."
            )
        )

    def _cargar_recetas(self) -> int:
        """Crea la receta (`DetallesMenu`) de cada producto que todavía no tenga.

        Un producto que ya tiene al menos un renglón de receta se deja como está,
        para no pisar lo que se haya editado en el admin. Si falta un ingrediente
        (por ejemplo, se borró en el admin), se omite ese renglón con un aviso.
        Devuelve cuántas recetas se crearon.
        """
        ingredientes = {
            (ingrediente.categoria.nombre, ingrediente.nombre): ingrediente
            for ingrediente in Ingrediente.objects.select_related("categoria")
        }
        recetas_creadas = 0

        for nombre, renglones in RECETAS.items():
            producto = Menu.objects.filter(nombre_producto=nombre).first()
            if producto is None or DetallesMenu.objects.filter(menu=producto).exists():
                continue

            detalles = []
            for categoria_nombre, ingrediente_nombre, cantidad in renglones:
                ingrediente = ingredientes.get((categoria_nombre, ingrediente_nombre))
                if ingrediente is None:
                    self.stdout.write(self.style.WARNING(
                        f"Receta de {nombre}: no existe el ingrediente "
                        f"{ingrediente_nombre} ({categoria_nombre}); se omite."
                    ))
                    continue
                detalles.append(DetallesMenu(menu=producto, ingrediente=ingrediente, cantidad=cantidad))

            if detalles:
                DetallesMenu.objects.bulk_create(detalles)
                recetas_creadas += 1
                self.stdout.write(f"Receta creada: {nombre}")

        return recetas_creadas
