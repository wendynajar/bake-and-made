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
from calendar import isleap, monthrange
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.apps import apps
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F
from django.utils import timezone

from usuarios.models import SIN_DESCUENTO, PerfilVIP

UsuarioOAnonimo = AbstractBaseUser | AnonymousUser


# =============================================================================
# 1. Suscripciones y recordatorios
# =============================================================================

PRECIO_SWEET_PLAN = Decimal('99.00')
"""Precio mensual del Sweet Plan. Única fuente de verdad del importe."""

PLAN_BASIC = 'basic'
PLAN_SWEET = 'sweet'

CENTAVO = Decimal('0.01')


def descuento_para(
    usuario: UsuarioOAnonimo, hoy: datetime.date | None = None
) -> tuple[Decimal, str]:
    """Punto único para vistas y checkout: (fracción, motivo) del descuento del usuario.

    Anónimo: sin descuento. Autenticado: lo decide `PerfilVIP.descuento_vigente()`.
    No crea el perfil si no existe (un usuario sin perfil no tiene cumpleaños),
    así consultar el descuento nunca escribe en la base de datos.
    """
    if not getattr(usuario, 'is_authenticated', False):
        return SIN_DESCUENTO
    perfil = PerfilVIP.objects.filter(usuario=usuario).first() or PerfilVIP(usuario=usuario)
    return perfil.descuento_vigente(hoy)


def aplicar_descuento(precio: Decimal, descuento: Decimal) -> Decimal:
    """Precio final con el descuento aplicado, redondeado a centavos (ROUND_HALF_UP).

    Se redondea por línea y el total es la suma de líneas, para que lo que ve el
    cliente coincida con lo que se guarda en el pedido.
    """
    return (precio * (Decimal('1') - descuento)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


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


def misma_fecha_en_anio(fecha: datetime.date, anio: int) -> datetime.date:
    """La fecha en otro año; el 29 de febrero cae el 28 en años no bisiestos."""
    if (fecha.month, fecha.day) == (2, 29) and not isleap(anio):
        return datetime.date(anio, 2, 28)
    return fecha.replace(year=anio)


class RecordatorioQuerySet(models.QuerySet['RecordatorioEvento']):
    """Consultas del calendario VIP; siempre filtradas por el dueño."""

    def de(self, usuario: User) -> RecordatorioQuerySet:
        """Solo las fechas del usuario: nadie ve ni borra las de otro."""
        return self.filter(usuario=usuario)

    def ocurrencias(
        self, desde: datetime.date, hasta: datetime.date
    ) -> list[tuple[RecordatorioEvento, datetime.date]]:
        """(evento, fecha) de cada aparición dentro de [desde, hasta).

        Los eventos que se repiten cada año aparecen una vez por año del rango,
        así el calendario los muestra sin que el usuario los capture de nuevo.
        """
        resultado = []
        for evento in self.order_by('fecha_evento', 'pk'):
            if not evento.se_repite_cada_anio:
                if desde <= evento.fecha_evento < hasta:
                    resultado.append((evento, evento.fecha_evento))
                continue
            for anio in range(max(desde.year, evento.fecha_evento.year), hasta.year + 1):
                dia = misma_fecha_en_anio(evento.fecha_evento, anio)
                if desde <= dia < hasta:
                    resultado.append((evento, dia))
        return resultado


class RecordatorioEvento(models.Model):
    """Fecha especial del cliente, mostrada en el calendario de la página VIP.

    `tipo` y `se_repite_cada_anio` permiten pintar cumpleaños y aniversarios
    cada año sin que el usuario los vuelva a capturar.
    """

    LONGITUD_NOMBRE = 100

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

    objects = RecordatorioQuerySet.as_manager()

    def __str__(self) -> str:
        return f"{self.nombre_evento} ({self.fecha_evento})"

    @classmethod
    def crear_para(cls, usuario: User, nombre: Any, fecha: Any, tipo: Any) -> RecordatorioEvento:
        """Valida los datos del calendario y crea la fecha del usuario.

        Recibe valores crudos del navegador y lanza ValidationError con mensajes
        para el cliente. Cumpleaños y aniversarios se repiten cada año.
        """
        errores: dict[str, str] = {}
        nombre = nombre.strip() if isinstance(nombre, str) else ''
        if not nombre or len(nombre) > cls.LONGITUD_NOMBRE:
            errores['nombre_evento'] = f'Escribe un nombre de 1 a {cls.LONGITUD_NOMBRE} caracteres.'
        try:
            fecha = datetime.date.fromisoformat(fecha) if isinstance(fecha, str) else None
        except ValueError:
            fecha = None
        if fecha is None:
            errores['fecha_evento'] = 'Elige una fecha válida.'
        if tipo not in dict(cls.TIPOS):
            errores['tipo'] = 'Elige un tipo de fecha válido.'
        if errores:
            raise ValidationError(errores)

        return cls.objects.create(
            usuario=usuario,
            nombre_evento=nombre,
            fecha_evento=fecha,
            tipo=tipo,
            se_repite_cada_anio=tipo in (cls.CUMPLEANIOS, cls.ANIVERSARIO),
        )


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
    """Ingredientes que componen un producto del menú (receta).

    `cargar_catalogo` la llena para los productos del catálogo (RECETAS);
    `cantidad` son porciones del ingrediente por unidad vendida del producto.
    """

    menu = models.ForeignKey(Menu, on_delete=models.CASCADE)
    ingrediente = models.ForeignKey(Ingrediente, on_delete=models.CASCADE)
    cantidad = models.IntegerField(default=1)

    def __str__(self) -> str:
        return f'{self.menu}: {self.ingrediente} x{self.cantidad}'


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
    # Se guardan con el pedido porque la cocina los necesita para prepararlo.
    dietas = models.JSONField(default=list, blank=True)
    color_frosting = models.CharField(max_length=20, blank=True)

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
    def precio_unitario(self) -> Decimal:
        """Precio base del producto, sin descuento."""
        return self.producto.precio_base

    @property
    def subtotal(self) -> Decimal:
        """Precio del producto por la cantidad, sin descuento."""
        return self.precio_unitario * self.cantidad

    def subtotal_con_descuento(self, descuento: Decimal) -> Decimal:
        """Subtotal cobrado: precio unitario redondeado con descuento por la cantidad."""
        return aplicar_descuento(self.precio_unitario, descuento) * self.cantidad

    def as_dict(self, descuento: Decimal = Decimal('0')) -> dict[str, Any]:
        """Representación para las plantillas, con precio base y precio final."""
        return {
            'tipo': 'normal',
            'producto': self.producto,
            'cantidad': self.cantidad,
            'precio_base': self.precio_unitario,
            'precio_unitario': aplicar_descuento(self.precio_unitario, descuento),
            'subtotal_base': self.subtotal,
            'subtotal': self.subtotal_con_descuento(descuento),
        }


@dataclass(frozen=True)
class LineaPersonalizada:
    """Cupcake personalizado del carrito, con ingredientes verificados contra la BD.

    El precio se recalcula con los ingredientes actuales; nunca se usa el precio
    guardado en la sesión.
    """

    nombre: str
    ingredientes: tuple[tuple[PasoCupcake, Ingrediente], ...]
    dietas: tuple[str, ...]
    color_frosting: str
    cantidad: int

    @property
    def precio_unitario(self) -> Decimal:
        """$35 más los extras de los ingredientes (CupcakePersonalizado.calcular_precio)."""
        return CupcakePersonalizado.calcular_precio(ing for _, ing in self.ingredientes)

    @property
    def subtotal(self) -> Decimal:
        """Precio unitario por la cantidad, sin descuento."""
        return self.precio_unitario * self.cantidad

    def subtotal_con_descuento(self, descuento: Decimal) -> Decimal:
        """Subtotal cobrado: precio unitario redondeado con descuento por la cantidad."""
        return aplicar_descuento(self.precio_unitario, descuento) * self.cantidad

    def as_dict(self, descuento: Decimal = Decimal('0')) -> dict[str, Any]:
        """Representación para las plantillas, con precio base y precio final."""
        return {
            'tipo': 'personalizado',
            'nombre': self.nombre,
            'ingredientes': [
                {'paso': paso.nombre, 'nombre': ingrediente.nombre}
                for paso, ingrediente in self.ingredientes
            ],
            'cantidad': self.cantidad,
            'precio_base': self.precio_unitario,
            'precio_unitario': aplicar_descuento(self.precio_unitario, descuento),
            'subtotal_base': self.subtotal,
            'subtotal': self.subtotal_con_descuento(descuento),
        }


LineaPedido = LineaCarrito | LineaPersonalizada


def demanda_de_ingredientes(lineas: Iterable[LineaPersonalizada]) -> dict[int, int]:
    """Unidades de cada ingrediente que consumen los cupcakes (id → unidades).

    Se agrupa por ingrediente porque dos cupcakes distintos pueden compartirlo y
    el stock debe alcanzar para ambos.
    """
    demanda: dict[int, int] = {}
    for linea in lineas:
        for _, ingrediente in linea.ingredientes:
            demanda[ingrediente.pk] = demanda.get(ingrediente.pk, 0) + linea.cantidad
    return demanda


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
    def personalizados_validos(
        personalizados: Iterable[Any], usuario: UsuarioOAnonimo
    ) -> list[LineaPersonalizada]:
        """Convierte los cupcakes personalizados de la sesión en líneas verificadas.

        La sesión solo se usa para saber qué eligió el cliente: cada ingrediente se
        vuelve a buscar en la BD y debe seguir activo, ser de la categoría de su
        paso y ser visible para el usuario (los exclusivos exigen Sweet vigente).
        También se revisa que haya stock para todos los cupcakes juntos.
        Lanza ErrorPedido o StockInsuficiente con un mensaje para el cliente.
        """
        personalizados = list(personalizados)
        ids = {
            dato['id']
            for cupcake in personalizados
            if isinstance(cupcake, dict) and isinstance(cupcake.get('ingredientes'), dict)
            for dato in cupcake['ingredientes'].values()
            if isinstance(dato, dict) and isinstance(dato.get('id'), int)
        }
        disponibles = {
            ingrediente.pk: ingrediente
            for ingrediente in Ingrediente.objects.visibles_para(usuario)
            .filter(activo=True, pk__in=ids)
            .select_related('categoria')
        }

        lineas = []
        for cupcake in personalizados:
            invalido = ErrorPedido(
                'Uno de tus cupcakes personalizados no es válido. Elimínalo y ármalo de nuevo.'
            )
            if not isinstance(cupcake, dict) or not isinstance(cupcake.get('ingredientes'), dict):
                raise invalido
            cantidad = cupcake.get('cantidad', 1)
            if type(cantidad) is not int or cantidad <= 0:
                raise invalido

            elegidos = []
            for paso in CupcakePersonalizado.PASOS:
                dato = cupcake['ingredientes'].get(paso.slug)
                ingrediente = disponibles.get(dato.get('id')) if isinstance(dato, dict) else None
                if ingrediente is None or ingrediente.categoria.nombre.lower() != paso.categoria.lower():
                    raise ErrorPedido(
                        f'La opción de {paso.nombre.lower()} de tu cupcake ya no está disponible. '
                        'Elimínalo del carrito y ármalo de nuevo.'
                    )
                elegidos.append((paso, ingrediente))

            dietas = cupcake.get('dietas')
            color = cupcake.get('color_frosting', '')
            lineas.append(LineaPersonalizada(
                nombre=str(cupcake.get('nombre') or 'Cupcake personalizado')[:100],
                ingredientes=tuple(elegidos),
                dietas=tuple(CupcakePersonalizado.filtrar_dietas(dietas if isinstance(dietas, list) else [])),
                color_frosting=color if color in CupcakePersonalizado.COLORES_FROSTING else '',
                cantidad=cantidad,
            ))

        for ingrediente_id, unidades in demanda_de_ingredientes(lineas).items():
            ingrediente = disponibles[ingrediente_id]
            if ingrediente.stock_disponible < unidades:
                raise StockInsuficiente(
                    f'No hay suficiente {ingrediente.nombre} para tus cupcakes personalizados.'
                )
        return lineas

    @staticmethod
    def total_de(lineas: Iterable[LineaPedido], descuento: Decimal = Decimal('0')) -> Decimal:
        """Total a cobrar: suma de subtotales con descuento (productos y personalizados).

        Se redondea por línea y luego se suma, para que el total coincida con la
        suma de los `DetallePedido.precio_unitario` guardados.
        """
        return sum((linea.subtotal_con_descuento(descuento) for linea in lineas), Decimal('0.00'))

    def crear_desde_carrito(
        self,
        *,
        usuario: User,
        carrito: Mapping[str, Any],
        direccion: str,
        checkout_token: uuid.UUID | str,
        total_esperado: Decimal,
        personalizados: Iterable[Any] = (),
        descuento: Decimal = Decimal('0'),
        motivo: str = '',
    ) -> Pedido:
        """Registra el pedido y descuenta el stock de forma atómica.

        `descuento` y `motivo` vienen de `descuento_para()` (nunca del navegador):
        cada `DetallePedido.precio_unitario` guarda el precio ya descontado y el
        pedido guarda el porcentaje y el motivo para auditar lo cobrado.

        Por qué así:
        - Se recalcula el total dentro de la transacción y se rechaza si difiere
          del que vio el cliente (PrecioCambiado).
        - El stock de productos e ingredientes se descuenta con UPDATE
          condicionales (`stock >= cantidad`) para evitar sobreventa entre
          peticiones concurrentes (StockInsuficiente).
        - `checkout_token` es único: un doble envío del formulario provoca
          IntegrityError en lugar de un pedido duplicado.
        - Cada cupcake personalizado se guarda como `CupcakePersonalizado` con sus
          `CupcakeIngredientes`, y su línea apunta a él (`cupcake_custom`).
        """
        if not Decimal('0') <= descuento < Decimal('1'):
            raise ValueError(f'Descuento fuera de rango: {descuento}')
        if motivo not in dict(Pedido.MOTIVOS_DESCUENTO) or (descuento > 0) != bool(motivo):
            raise ValueError(f'Motivo de descuento inválido: {motivo!r}')

        with transaction.atomic():
            lineas = self.lineas_validas(carrito)
            personalizadas = self.personalizados_validos(personalizados, usuario)
            if not lineas and not personalizadas:
                raise ErrorPedido('Tu carrito está vacío.')
            total = self.total_de([*lineas, *personalizadas], descuento)
            if total != total_esperado:
                raise PrecioCambiado('Los precios cambiaron. Revisa nuevamente tu pedido.')

            pedido = self.create(
                usuario=usuario,
                total=total,
                descuento_porcentaje=descuento,
                motivo_descuento=motivo,
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
                    precio_unitario=aplicar_descuento(linea.precio_unitario, descuento),
                )

            self._descontar_ingredientes(personalizadas)
            for linea in personalizadas:
                cupcake = CupcakePersonalizado.objects.create(
                    usuario=usuario,
                    nombre_custom=linea.nombre,
                    precio_calculado=linea.precio_unitario,
                    dietas=list(linea.dietas),
                    color_frosting=linea.color_frosting,
                )
                CupcakeIngredientes.objects.bulk_create(
                    CupcakeIngredientes(cupcake=cupcake, ingrediente=ingrediente)
                    for _, ingrediente in linea.ingredientes
                )
                DetallePedido.objects.create(
                    pedido=pedido,
                    cupcake_custom=cupcake,
                    cantidad=linea.cantidad,
                    precio_unitario=aplicar_descuento(linea.precio_unitario, descuento),
                )
        return pedido

    @staticmethod
    def _descontar_ingredientes(personalizadas: Iterable[LineaPersonalizada]) -> None:
        """Descuenta el stock de ingredientes con UPDATE condicionales (hallazgo #8).

        Debe llamarse dentro de la transacción del pedido: si un ingrediente se
        agotó entre la validación y este punto, StockInsuficiente revierte todo.
        """
        for ingrediente_id, unidades in demanda_de_ingredientes(personalizadas).items():
            actualizados = Ingrediente.objects.filter(
                pk=ingrediente_id, activo=True, stock_disponible__gte=unidades
            ).update(stock_disponible=F('stock_disponible') - unidades)
            if actualizados != 1:
                raise StockInsuficiente(
                    'Los ingredientes de tus cupcakes cambiaron mientras confirmabas. '
                    'Revisa nuevamente tu carrito.'
                )


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


class ExperienciaQRQuerySet(models.QuerySet['ExperienciaQR']):
    """Consultas de videos VIP."""

    def vigentes(self) -> ExperienciaQRQuerySet:
        """Experiencias cuya fecha de expiración no ha pasado."""
        return self.filter(fecha_expiracion__gt=timezone.now())

    def vigente_de(self, usuario: User) -> ExperienciaQR | None:
        """El video vigente más reciente del usuario, o None ("estará listo pronto")."""
        return self.vigentes().filter(usuario=usuario).order_by('-fecha_expiracion', '-pk').first()


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

    objects = ExperienciaQRQuerySet.as_manager()

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
