"""Modelos de la tienda Bake & Made.

Siguiendo la regla "Fat Models, Skinny Views" de docs/ARCHITECTURE.md, la
lógica de negocio (vigencia de suscripciones, ingredientes visibles por plan,
precio de cupcakes y registro de pedidos) vive aquí, en métodos de modelo y
QuerySets personalizados. Las vistas solo traducen HTTP ↔ estas operaciones.
"""

from __future__ import annotations

import datetime
import secrets
import uuid
from calendar import monthrange
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.apps import apps
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import AnonymousUser, User
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

UsuarioOAnonimo = AbstractBaseUser | AnonymousUser


# =============================================================================
# 1. Suscripciones y recordatorios
# =============================================================================

PRECIO_SWEET_PLAN = Decimal('99.00')
"""Precio mensual del Sweet Plan. Única fuente de verdad del importe."""

PLAN_BASIC = 'basic'
PLAN_SWEET = 'sweet'


def sumar_un_mes(fecha: datetime.date) -> datetime.date:
    """Devuelve la misma fecha del mes siguiente, ajustando meses cortos.

    Por qué: una suscripción iniciada el 31 de enero debe vencer el 28/29 de
    febrero, no fallar ni saltar a marzo.
    """
    if fecha.month == 12:
        anio, mes = fecha.year + 1, 1
    else:
        anio, mes = fecha.year, fecha.month + 1
    dia = min(fecha.day, monthrange(anio, mes)[1])
    return fecha.replace(year=anio, month=mes, day=dia)


class SuscripcionQuerySet(models.QuerySet['Suscripcion']):
    """Consultas de negocio sobre suscripciones."""

    def expirar_vencidas(self, usuario: User) -> int:
        """Marca como 'expirada' toda suscripción del usuario cuya fecha_fin ya pasó.

        Devuelve el número de filas actualizadas.
        """
        hoy = timezone.localdate()
        return (
            self.filter(usuario=usuario, fecha_fin__lt=hoy)
            .exclude(estado=Suscripcion.EXPIRADA)
            .update(estado=Suscripcion.EXPIRADA)
        )

    def vigente_para(self, usuario: UsuarioOAnonimo) -> Suscripcion | None:
        """Devuelve la suscripción que da acceso hoy al usuario, si existe.

        Una suscripción cancelada conserva el acceso hasta su fecha_fin, por eso
        cuenta como vigente junto con las activas.
        """
        if not getattr(usuario, 'is_authenticated', False):
            return None

        self.expirar_vencidas(usuario)
        return (
            self.filter(
                usuario=usuario,
                estado__in=(Suscripcion.ACTIVA, Suscripcion.CANCELADA),
                fecha_fin__gte=timezone.localdate(),
            )
            .order_by('-fecha_inicio', '-pk')
            .first()
        )

    def plan_de(self, usuario: UsuarioOAnonimo) -> str:
        """Devuelve PLAN_SWEET si el usuario tiene acceso vigente; si no, PLAN_BASIC."""
        return PLAN_SWEET if self.vigente_para(usuario) else PLAN_BASIC

    def activa_para(self, usuario: User) -> Suscripcion | None:
        """Devuelve la suscripción activa (no cancelada) y no vencida del usuario."""
        return (
            self.filter(
                usuario=usuario,
                estado=Suscripcion.ACTIVA,
                fecha_fin__gte=timezone.localdate(),
            )
            .order_by('-fecha_inicio', '-pk')
            .first()
        )


class Suscripcion(models.Model):
    """Suscripción mensual al Sweet Plan, que desbloquea ingredientes exclusivos."""

    ACTIVA = 'activa'
    CANCELADA = 'cancelada'
    EXPIRADA = 'expirada'
    ESTADOS = [
        (ACTIVA, 'Activa'),
        (CANCELADA, 'Cancelada'),
        (EXPIRADA, 'Expirada'),
    ]
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    estado = models.CharField(max_length=20, choices=ESTADOS, default=ACTIVA)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    monto_mensual = models.DecimalField(max_digits=10, decimal_places=2)

    objects = SuscripcionQuerySet.as_manager()

    def __str__(self) -> str:
        return f"Suscripción {self.estado} - {self.usuario.username}"

    @classmethod
    def contratar_mes(cls, usuario: User) -> Suscripcion:
        """Crea una suscripción Sweet de un mes a partir de hoy y entrega la tarjeta VIP.

        La entrega de la tarjeta es simulada (docs/IOT_VIP_SPEC.md): se asigna la
        primera tarjeta libre del inventario, o ninguna si no quedan ("en camino").
        Una renovación no entrega otra tarjeta. Todo ocurre en una transacción para
        que no quede una suscripción sin su intento de entrega.

        TODO: integrar la pasarela de pago antes de crear la suscripción real.
        Hoy la confirmación es simulada y no guarda datos bancarios.
        """
        # get_model evita importar iot desde tienda (y el import circular).
        TarjetaRFID = apps.get_model('iot', 'TarjetaRFID')
        inicio = timezone.localdate()
        with transaction.atomic():
            suscripcion = cls.objects.create(
                usuario=usuario,
                estado=cls.ACTIVA,
                fecha_inicio=inicio,
                fecha_fin=sumar_un_mes(inicio),
                monto_mensual=PRECIO_SWEET_PLAN,
            )
            TarjetaRFID.objects.entregar_a(usuario)
        return suscripcion

    def cancelar(self) -> None:
        """Cancela la renovación; el acceso se conserva hasta fecha_fin."""
        self.estado = self.CANCELADA
        self.save(update_fields=['estado'])


class RecordatorioEvento(models.Model):
    """Fecha especial del cliente, mostrada en el calendario de la página VIP.

    `tipo` y `se_repite_cada_anio` permiten pintar cumpleaños y aniversarios
    cada año sin que el usuario los vuelva a capturar.
    """

    CUMPLEANIOS = 'cumpleanios'
    ANIVERSARIO = 'aniversario'
    OTRO = 'otro'
    TIPOS = [
        (CUMPLEANIOS, 'Cumpleaños'),
        (ANIVERSARIO, 'Aniversario'),
        (OTRO, 'Otro'),
    ]

    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    nombre_evento = models.CharField(max_length=100)
    fecha_evento = models.DateField()
    notificado = models.BooleanField(default=False)
    tipo = models.CharField(max_length=20, choices=TIPOS, default=OTRO)
    se_repite_cada_anio = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"{self.nombre_evento} ({self.fecha_evento})"


# =============================================================================
# 2. Ingredientes y menú
# =============================================================================

class CategoriaIngrediente(models.Model):
    """Agrupa ingredientes por paso del asistente (Base, Relleno, Cobertura, Topping)."""

    nombre = models.CharField(max_length=50)

    def __str__(self) -> str:
        return self.nombre


class IngredienteQuerySet(models.QuerySet['Ingrediente']):
    """Consultas de negocio sobre ingredientes."""

    def de_categoria(self, categoria: str) -> IngredienteQuerySet:
        """Ingredientes activos de una categoría (sin distinguir mayúsculas)."""
        return self.filter(activo=True, categoria__nombre__iexact=categoria)

    def visibles_para(self, usuario: UsuarioOAnonimo) -> IngredienteQuerySet:
        """Oculta los ingredientes exclusivos si el usuario no tiene el Sweet Plan.

        Conserva los filtros previos del QuerySet y solo aplica la regla de plan.
        """
        if Suscripcion.objects.plan_de(usuario) == PLAN_SWEET:
            return self
        return self.filter(solo_suscriptores=False)


class Ingrediente(models.Model):
    """Opción elegible en el asistente de cupcakes, con su costo adicional."""

    categoria = models.ForeignKey(CategoriaIngrediente, on_delete=models.CASCADE)
    nombre = models.CharField(max_length=100)
    precio_adicional = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    solo_suscriptores = models.BooleanField(default=False)
    stock_disponible = models.IntegerField(default=0)
    imagen = models.ImageField(upload_to='ingredientes/', blank=True, null=True)
    activo = models.BooleanField(default=True)

    objects = IngredienteQuerySet.as_manager()

    def __str__(self) -> str:
        return self.nombre


class MenuQuerySet(models.QuerySet['Menu']):
    """Consultas de negocio sobre productos del catálogo."""

    def en_venta(self) -> MenuQuerySet:
        """Productos marcados como disponibles y con al menos una unidad en stock."""
        return self.filter(disponible=True, stock__gt=0)


class Menu(models.Model):
    """Producto predeterminado del catálogo (cupcake, pastel, galleta, paquete)."""

    nombre_producto = models.CharField(max_length=100)
    descripcion = models.TextField()
    precio_base = models.DecimalField(max_digits=10, decimal_places=2)
    disponible = models.BooleanField(default=True)
    ingredientes = models.ManyToManyField(Ingrediente, through='DetallesMenu')
    categoria = models.ForeignKey(
        'CategoriaProducto',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='productos',
    )
    imagen = models.ImageField(upload_to='productos/', blank=True, null=True)
    stock = models.PositiveIntegerField(default=0)

    objects = MenuQuerySet.as_manager()

    def __str__(self) -> str:
        return self.nombre_producto

    def admite_cantidad(self, cantidad: int) -> bool:
        """Indica si se pueden vender `cantidad` unidades ahora mismo."""
        return self.disponible and 0 < cantidad <= self.stock


class DetallesMenu(models.Model):
    """Ingredientes que componen un producto del menú (receta)."""

    menu = models.ForeignKey(Menu, on_delete=models.CASCADE)
    ingrediente = models.ForeignKey(Ingrediente, on_delete=models.CASCADE)
    cantidad = models.IntegerField(default=1)


# =============================================================================
# 3. Cupcakes personalizados
# =============================================================================

@dataclass(frozen=True)
class PasoCupcake:
    """Paso del asistente: slug de URL, nombre visible y categoría de ingrediente."""

    slug: str
    nombre: str
    categoria: str
    descripcion: str

    def as_dict(self) -> dict[str, str]:
        """Representación para las plantillas existentes (acceso por clave)."""
        return {
            'slug': self.slug,
            'nombre': self.nombre,
            'categoria': self.categoria,
            'descripcion': self.descripcion,
        }


class CupcakePersonalizado(models.Model):
    """Cupcake armado por el cliente con el asistente de 4 pasos.

    Hoy el cupcake vive en la sesión mientras está en el carrito; este modelo
    concentra sus reglas (pasos, precio, dietas, colores) y queda listo para
    persistirlo cuando el checkout soporte personalizados.
    """

    PRECIO_BASE = Decimal('35.00')

    PASOS: tuple[PasoCupcake, ...] = (
        PasoCupcake('base', 'Base', 'Base', 'Elige el sabor de tu bizcocho.'),
        PasoCupcake('relleno', 'Relleno', 'Relleno', 'Elige el centro de tu cupcake.'),
        PasoCupcake('cobertura', 'Cobertura', 'Cobertura', 'Elige el frosting y su color.'),
        PasoCupcake('topping', 'Topping', 'Topping', 'Dale el toque final a tu creación.'),
    )

    # Las preferencias dietarias son modificadores opcionales de la base.
    DIETAS: dict[str, str] = {
        'sin_gluten': 'Sin gluten',
        'sin_lactosa': 'Sin lactosa',
        'vegano': 'Vegano',
        'bajo_azucar': 'Bajo en azúcar',
    }

    COLORES_FROSTING: dict[str, str] = {
        'blanco': 'Blanco',
        'rosa': 'Rosa',
        'azul': 'Azul',
        'lila': 'Lila',
        'amarillo': 'Amarillo',
        'verde': 'Verde',
        'chocolate': 'Chocolate',
    }

    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    nombre_custom = models.CharField(max_length=100, blank=True, null=True)
    precio_calculado = models.DecimalField(max_digits=10, decimal_places=2)
    ingredientes = models.ManyToManyField(Ingrediente, through='CupcakeIngredientes')

    def __str__(self) -> str:
        return self.nombre_custom or f"Cupcake Custom #{self.id}"

    @classmethod
    def slugs_pasos(cls) -> list[str]:
        """Slugs de los pasos en orden."""
        return [p.slug for p in cls.PASOS]

    @classmethod
    def indice_paso(cls, slug: str) -> int:
        """Posición (0-based) del paso con ese slug. Lanza ValueError si no existe."""
        return cls.slugs_pasos().index(slug)

    @classmethod
    def paso(cls, slug: str) -> PasoCupcake:
        """Definición del paso con ese slug."""
        return cls.PASOS[cls.indice_paso(slug)]

    @classmethod
    def calcular_precio(cls, ingredientes: Iterable[Ingrediente | None]) -> Decimal:
        """Precio base más los extras de los ingredientes elegidos.

        Se calcula siempre en el servidor; nunca se acepta un precio del navegador.
        """
        total = cls.PRECIO_BASE
        for ingrediente in ingredientes:
            if ingrediente is not None:
                total += ingrediente.precio_adicional
        return total

    @classmethod
    def esta_completo(cls, selecciones: Mapping[str, Ingrediente | None]) -> bool:
        """True si hay un ingrediente elegido para cada paso."""
        return all(selecciones.get(slug) for slug in cls.slugs_pasos())

    @classmethod
    def filtrar_dietas(cls, dietas: Iterable[str]) -> list[str]:
        """Descarta claves de dieta desconocidas enviadas por el cliente."""
        return [d for d in dietas if d in cls.DIETAS]


class CupcakeIngredientes(models.Model):
    """Ingrediente elegido para un cupcake personalizado."""

    cupcake = models.ForeignKey(CupcakePersonalizado, on_delete=models.CASCADE)
    ingrediente = models.ForeignKey(Ingrediente, on_delete=models.CASCADE)
    cantidad = models.IntegerField(default=1)


# =============================================================================
# 4. Pedidos y experiencia QR
# =============================================================================

class ErrorPedido(Exception):
    """Error de negocio al registrar un pedido; `args[0]` es el mensaje para el cliente."""


class StockInsuficiente(ErrorPedido):
    """El inventario no alcanza (o cambió durante la confirmación)."""


class PrecioCambiado(ErrorPedido):
    """El total recalculado no coincide con el que vio el cliente."""


@dataclass(frozen=True)
class LineaCarrito:
    """Producto del catálogo con su cantidad y subtotal calculado en el servidor."""

    producto: Menu
    cantidad: int

    @property
    def subtotal(self) -> Decimal:
        """Precio del producto por la cantidad."""
        return self.producto.precio_base * self.cantidad

    def as_dict(self) -> dict[str, Any]:
        """Representación para las plantillas existentes."""
        return {
            'tipo': 'normal',
            'producto': self.producto,
            'cantidad': self.cantidad,
            'subtotal': self.subtotal,
        }


class PedidoQuerySet(models.QuerySet['Pedido']):
    """Operaciones de negocio sobre pedidos."""

    @staticmethod
    def lineas_validas(carrito: Mapping[str, Any]) -> list[LineaCarrito]:
        """Convierte el carrito de sesión en líneas verificadas contra la BD.

        Lanza ErrorPedido si algún producto ya no existe y StockInsuficiente si
        alguna cantidad es inválida o supera el stock.
        """
        productos = list(Menu.objects.filter(id__in=carrito.keys()))
        if len(productos) != len(carrito):
            raise ErrorPedido('Algunos productos ya no existen.')

        lineas = []
        for producto in productos:
            cantidad = carrito.get(str(producto.id), 0)
            if type(cantidad) is not int or not producto.admite_cantidad(cantidad):
                raise StockInsuficiente(
                    f'Revisa la disponibilidad de {producto.nombre_producto}.'
                )
            lineas.append(LineaCarrito(producto, cantidad))
        return lineas

    @staticmethod
    def total_de(lineas: Iterable[LineaCarrito]) -> Decimal:
        """Suma de subtotales."""
        return sum((linea.subtotal for linea in lineas), Decimal('0.00'))

    def crear_desde_carrito(
        self,
        *,
        usuario: User,
        carrito: Mapping[str, Any],
        direccion: str,
        checkout_token: uuid.UUID | str,
        total_esperado: Decimal,
    ) -> Pedido:
        """Registra el pedido y descuenta el stock de forma atómica.

        Por qué así:
        - Se recalcula el total dentro de la transacción y se rechaza si difiere
          del que vio el cliente (PrecioCambiado).
        - El stock se descuenta con un UPDATE condicional (`stock >= cantidad`)
          para evitar sobreventa entre peticiones concurrentes (StockInsuficiente).
        - `checkout_token` es único: un doble envío del formulario provoca
          IntegrityError en lugar de un pedido duplicado.
        """
        with transaction.atomic():
            lineas = self.lineas_validas(carrito)
            total = self.total_de(lineas)
            if total != total_esperado:
                raise PrecioCambiado('Los precios cambiaron. Revisa nuevamente tu pedido.')

            pedido = self.create(
                usuario=usuario,
                total=total,
                direccion_entrega=direccion,
                estado_pedido=Pedido.PENDIENTE,
                checkout_token=checkout_token,
            )

            for linea in lineas:
                actualizados = Menu.objects.filter(
                    pk=linea.producto.pk,
                    disponible=True,
                    stock__gte=linea.cantidad,
                ).update(stock=F('stock') - linea.cantidad)

                if actualizados != 1:
                    raise StockInsuficiente(
                        'Las existencias cambiaron mientras confirmabas tu pedido. '
                        'Revisa nuevamente tu carrito.'
                    )

                DetallePedido.objects.create(
                    pedido=pedido,
                    menu_item=linea.producto,
                    cantidad=linea.cantidad,
                    precio_unitario=linea.producto.precio_base,
                )
        return pedido


class Pedido(models.Model):
    """Compra confirmada por un cliente, con su estado de preparación y entrega."""

    PENDIENTE = 'pendiente'
    ESTADOS_PEDIDO = [
        (PENDIENTE, 'Pendiente'),
        ('en_preparacion', 'En Preparación'),
        ('enviado', 'Enviado'),
        ('entregado', 'Entregado'),
    ]
    # Motivo del descuento cobrado; se guarda para auditar el precio de cada pedido.
    SIN_DESCUENTO = ''
    MOTIVO_VIP = 'vip'
    MOTIVO_CUMPLEANIOS = 'cumpleanios'
    MOTIVOS_DESCUENTO = [
        (SIN_DESCUENTO, 'Sin descuento'),
        (MOTIVO_VIP, 'VIP'),
        (MOTIVO_CUMPLEANIOS, 'Cumpleaños'),
    ]

    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    fecha_pedido = models.DateTimeField(auto_now_add=True)
    estado_pedido = models.CharField(max_length=20, choices=ESTADOS_PEDIDO, default=PENDIENTE)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    descuento_porcentaje = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal('0'),
        help_text='Fracción descontada: 0.20 = 20 %.',
    )
    motivo_descuento = models.CharField(
        max_length=20, choices=MOTIVOS_DESCUENTO, default=SIN_DESCUENTO, blank=True
    )
    direccion_entrega = models.TextField()
    checkout_token = models.UUIDField(unique=True, null=True, blank=True, editable=False)

    objects = PedidoQuerySet.as_manager()

    def __str__(self) -> str:
        return f"Pedido #{self.id} - {self.usuario.username}"


class DetallePedido(models.Model):
    """Línea de un pedido: producto del menú o cupcake personalizado, con precio congelado."""

    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE)
    cupcake_custom = models.ForeignKey(
        CupcakePersonalizado, on_delete=models.SET_NULL, null=True, blank=True
    )
    menu_item = models.ForeignKey(Menu, on_delete=models.SET_NULL, null=True, blank=True)
    cantidad = models.IntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)


def generar_codigo_qr() -> str:
    """Token aleatorio y no adivinable para la URL pública del QR (/vip/v/<codigo>/)."""
    return secrets.token_urlsafe(16)


class ExperienciaQR(models.Model):
    """Video personal de un usuario VIP, que se abre al escanear su código QR.

    El archivo vive en el almacenamiento por defecto (S3 en producción), porque
    el disco de Render es efímero. `detalle_pedido` es opcional: el video es del
    usuario, no de una línea de pedido.
    """

    usuario = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,  # Solo para filas previas a la capa VIP; el admin lo exige.
        related_name='experiencias_qr',
    )
    detalle_pedido = models.OneToOneField(
        DetallePedido, on_delete=models.SET_NULL, null=True, blank=True
    )
    codigo_unico = models.CharField(max_length=100, unique=True, default=generar_codigo_qr)
    video = models.FileField(upload_to='videos/', max_length=255)
    mensaje_texto = models.TextField(blank=True, null=True)
    fecha_expiracion = models.DateTimeField()

    def __str__(self) -> str:
        return f"QR {self.codigo_unico}"


# =============================================================================
# 5. Categorías de productos
# =============================================================================

class CategoriaProducto(models.Model):
    """Sección del catálogo (Cupcakes, Pasteles, Galletas, ...)."""

    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.nombre

    class Meta:
        verbose_name = "Categoría de producto"
        verbose_name_plural = "Categorías de productos"
