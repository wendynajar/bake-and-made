from django.db import models
from django.contrib.auth.models import User

# --- 1. Módulo de Suscripciones y Recordatorios ---
class Suscripcion(models.Model):
    ESTADOS = [
        ('activa', 'Activa'),
        ('cancelada', 'Cancelada'),
        ('expirada', 'Expirada'),
    ]
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='activa')
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    monto_mensual = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"Suscripción {self.estado} - {self.usuario.username}"


class RecordatorioEvento(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    nombre_evento = models.CharField(max_length=100)
    fecha_evento = models.DateField()
    notificado = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.nombre_evento} ({self.fecha_evento})"


# --- 2. Módulo de Ingredientes y Menú Predeterminado ---
class CategoriaIngrediente(models.Model):
    nombre = models.CharField(max_length=50)

    def __str__(self):
        return self.nombre


class Ingrediente(models.Model):
    categoria = models.ForeignKey(CategoriaIngrediente, on_delete=models.CASCADE)
    nombre = models.CharField(max_length=100)
    precio_adicional = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    solo_suscriptores = models.BooleanField(default=False)
    stock_disponible = models.IntegerField(default=0)

    def __str__(self):
        return self.nombre


class Menu(models.Model):
    nombre_producto = models.CharField(max_length=100)
    descripcion = models.TextField()
    precio_base = models.DecimalField(max_digits=10, decimal_places=2)
    disponible = models.BooleanField(default=True)
    ingredientes = models.ManyToManyField(Ingrediente, through='DetallesMenu')

    def __str__(self):
        return self.nombre_producto


class DetallesMenu(models.Model):
    menu = models.ForeignKey(Menu, on_delete=models.CASCADE)
    ingrediente = models.ForeignKey(Ingrediente, on_delete=models.CASCADE)
    cantidad = models.IntegerField(default=1)


# --- 3. Módulo de Cupcakes Personalizados ---
class CupcakePersonalizado(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    nombre_custom = models.CharField(max_length=100, blank=True, null=True)
    precio_calculado = models.DecimalField(max_digits=10, decimal_places=2)
    ingredientes = models.ManyToManyField(Ingrediente, through='CupcakeIngredientes')

    def __str__(self):
        return self.nombre_custom or f"Cupcake Custom #{self.id}"


class CupcakeIngredientes(models.Model):
    cupcake = models.ForeignKey(CupcakePersonalizado, on_delete=models.CASCADE)
    ingrediente = models.ForeignKey(Ingrediente, on_delete=models.CASCADE)
    cantidad = models.IntegerField(default=1)


# --- 4. Módulo de Pedidos y Experiencia QR ---
class Pedido(models.Model):
    ESTADOS_PEDIDO = [
        ('pendiente', 'Pendiente'),
        ('en_preparacion', 'En Preparación'),
        ('enviado', 'Enviado'),
        ('entregado', 'Entregado'),
    ]
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    fecha_pedido = models.DateTimeField(auto_now_add=True)
    estado_pedido = models.CharField(max_length=20, choices=ESTADOS_PEDIDO, default='pendiente')
    total = models.DecimalField(max_digits=10, decimal_places=2)
    direccion_entrega = models.TextField()

    def __str__(self):
        return f"Pedido #{self.id} - {self.usuario.username}"


class DetallePedido(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE)
    cupcake_custom = models.ForeignKey(CupcakePersonalizado, on_delete=models.SET_NULL, null=True, blank=True)
    menu_item = models.ForeignKey(Menu, on_delete=models.SET_NULL, null=True, blank=True)
    cantidad = models.IntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)


class ExperienciaQR(models.Model):
    detalle_pedido = models.OneToOneField(DetallePedido, on_delete=models.CASCADE)
    codigo_unico = models.CharField(max_length=100, unique=True)
    url_video = models.CharField(max_length=255)
    mensaje_texto = models.TextField(blank=True, null=True)
    fecha_expiracion = models.DateTimeField()

    def __str__(self):
        return f"QR {self.codigo_unico}"