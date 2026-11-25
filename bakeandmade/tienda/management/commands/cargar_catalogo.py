from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from tienda.models import Menu, CategoriaProducto, CategoriaIngrediente, Ingrediente


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

# nombre del producto -> ruta dentro de media/
IMAGENES = {
    "Cupcake red velvet": "productos/descarga_3.jpg",
    "Cupcake de fresa": "productos/descarga_11.jpg",
    "Cupcake de zanahoria": "productos/Soft_Carrot_Cake_Cupcakes_With_Cream_Cheese_Frosting.jpg",

    "Galleta con chispas de chocolate": "productos/Better_than_a_Bakery_Chocolate_Chip_Cookies.jpg",
    "Galleta red velvet": "productos/descarga_4.jpg",
    "Galleta de mantequilla": "productos/Pastisetas_con_Mantequilla.jpg",

    "Brownie de chocolate": "productos/descarga_5.jpg",
    "Cheesecake de fresa": "productos/descarga_6.jpg",

    "Pastel de chocolate": "productos/Chocolate_Ganache_Cake.jpg",
    "Pastel de tres leches": "productos/descarga_7.jpg",
    "Pastel de zanahoria": "productos/descarga_8.jpg",

    "Caja de 6 cupcakes": "productos/descarga_9.jpg",
    "Caja de regalo dulce": "productos/A_Sweet_Story_to_Share.jpg",
}

CATEGORIAS_INGREDIENTES = [
    "Base",
    "Relleno",
    "Cobertura",
    "Topping",
]

INGREDIENTES = [
    # Categoría, nombre, precio adicional
    ("Base", "Vainilla", "0.00"),
    ("Base", "Chocolate", "5.00"),
    ("Base", "Red velvet", "8.00"),
    ("Base", "Zanahoria", "6.00"),
    # ("Base", "Naranja", "6.00"),  # descomenta y pon el precio real si la quieres

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

# (categoría, nombre) -> ruta dentro de media/
IMAGENES_INGREDIENTES = {
    ("Base", "Vainilla"): "ingredientes/base_vainilla.jpg",
    ("Base", "Chocolate"): "ingredientes/base_chocolate.jpg",
    ("Base", "Red velvet"): "ingredientes/base_red_velvet.jpg",
    # ("Base", "Naranja"): "ingredientes/base_naranja.jpg",

    ("Relleno", "Crema de vainilla"): "ingredientes/relleno_vainilla.jpg",
    ("Relleno", "Chocolate"): "ingredientes/relleno_chocolate.jpg",
    ("Relleno", "Dulce de leche"): "ingredientes/relleno_dulce_de_leche.jpg",
    ("Relleno", "Fresa"): "ingredientes/relleno_fresas.jpeg",

    ("Cobertura", "Buttercream de vainilla"): "ingredientes/cobertura_buttercream_de_vainilla.jpg",
    ("Cobertura", "Buttercream de chocolate"): "ingredientes/cobertura_buttercream_de_chocolate.jpg",
    ("Cobertura", "Queso crema"): "ingredientes/cobertura_queso_crema.jpg",

    ("Topping", "Chispas de chocolate"): "ingredientes/topping_chispas_de_chocolate.jpg",
    ("Topping", "Galleta triturada"): "ingredientes/topping_galleta_triturada.jpg",
    ("Topping", "Sprinkles de colores"): "ingredientes/topping_sprinkles.png",
    ("Topping", "Fresas"): "ingredientes/topping_fresas.jpg",
}


def asignar_imagen(objeto, ruta):
    """Asigna la imagen solo si el archivo existe, para no dejar rutas rotas."""
    if not ruta:
        return False
    if not (settings.MEDIA_ROOT / ruta).exists():
        return False
    if objeto.imagen.name != ruta:
        objeto.imagen = ruta
        objeto.save()
    return True


class Command(BaseCommand):
    help = "Carga el catálogo inicial de Bake & Made"

    @transaction.atomic
    def handle(self, *args, **options):
        creados = 0
        existentes = 0
        categorias_creadas = 0

        # --- Categorías de ingredientes ---
        for nombre in CATEGORIAS_INGREDIENTES:
            categoria, creada = CategoriaIngrediente.objects.get_or_create(
                nombre=nombre
            )

            if creada:
                categorias_creadas += 1
                self.stdout.write(
                    self.style.SUCCESS(f"Categoría de ingrediente creada: {nombre}")
                )
            else:
                self.stdout.write(f"La categoría de ingrediente ya existe: {nombre}")

        # --- Ingredientes ---
        ingredientes_creados = 0

        for categoria_nombre, nombre, precio in INGREDIENTES:
            categoria = CategoriaIngrediente.objects.get(nombre=categoria_nombre)

            ingrediente, creado = Ingrediente.objects.get_or_create(
                categoria=categoria,
                nombre=nombre,
                defaults={
                    "precio_adicional": Decimal(precio),
                    "stock_disponible": 100,
                    "solo_suscriptores": False,
                    "activo": True,
                },
            )

            if creado:
                ingredientes_creados += 1
                self.stdout.write(self.style.SUCCESS(f"Ingrediente creado: {nombre}"))
            else:
                self.stdout.write(f"Ingrediente ya existente: {nombre}")

            ruta = IMAGENES_INGREDIENTES.get((categoria_nombre, nombre))
            if ruta and not asignar_imagen(ingrediente, ruta):
                self.stdout.write(
                    self.style.WARNING(f"  Falta el archivo de imagen: {ruta}")
                )

        self.stdout.write(f"Ingredientes nuevos: {ingredientes_creados}")

        # --- Productos ---
        for nombre, categoria_nombre, precio, descripcion in PRODUCTOS:
            categoria, _ = CategoriaProducto.objects.get_or_create(
                nombre=categoria_nombre
            )

            producto, creado = Menu.objects.get_or_create(
                nombre_producto=nombre,
                defaults={
                    "descripcion": descripcion,
                    "precio_base": Decimal(precio),
                    "disponible": True,
                    "categoria": categoria,
                    "stock": 20,
                },
            )

            ruta = IMAGENES.get(nombre)
            if ruta and not asignar_imagen(producto, ruta):
                self.stdout.write(
                    self.style.WARNING(f"  Falta el archivo de imagen: {ruta}")
                )

            if creado:
                creados += 1
                self.stdout.write(self.style.SUCCESS(f"Creado: {nombre}"))
            else:
                existentes += 1
                self.stdout.write(f"Ya existe: {nombre}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Catálogo cargado. Nuevos: {creados}. Existentes: {existentes}."
            )
        )