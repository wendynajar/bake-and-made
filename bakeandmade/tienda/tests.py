"""Pruebas de la lógica de negocio de la tienda (modelos) y de los flujos HTTP críticos."""

import datetime
import uuid
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    PLAN_BASIC,
    PLAN_SWEET,
    CategoriaIngrediente,
    CupcakePersonalizado,
    ExperienciaQR,
    Ingrediente,
    Menu,
    Pedido,
    PrecioCambiado,
    StockInsuficiente,
    Suscripcion,
    sumar_un_mes,
)


class SumarUnMesTests(TestCase):
    """Reglas de calendario para la fecha de fin de una suscripción."""

    def test_mes_normal(self) -> None:
        self.assertEqual(sumar_un_mes(datetime.date(2026, 3, 15)), datetime.date(2026, 4, 15))

    def test_ajusta_a_fin_de_mes_corto(self) -> None:
        self.assertEqual(sumar_un_mes(datetime.date(2026, 1, 31)), datetime.date(2026, 2, 28))

    def test_cambio_de_anio(self) -> None:
        self.assertEqual(sumar_un_mes(datetime.date(2026, 12, 10)), datetime.date(2027, 1, 10))


class SuscripcionTests(TestCase):
    """Vigencia, expiración y cancelación del Sweet Plan."""

    def setUp(self) -> None:
        self.usuario = User.objects.create_user('ana', password='clave-segura-123')

    def test_sin_suscripcion_es_basic(self) -> None:
        self.assertEqual(Suscripcion.objects.plan_de(self.usuario), PLAN_BASIC)

    def test_contratar_da_plan_sweet(self) -> None:
        Suscripcion.contratar_mes(self.usuario)
        self.assertEqual(Suscripcion.objects.plan_de(self.usuario), PLAN_SWEET)

    def test_cancelada_conserva_acceso_hasta_fecha_fin(self) -> None:
        Suscripcion.contratar_mes(self.usuario).cancelar()
        self.assertEqual(Suscripcion.objects.plan_de(self.usuario), PLAN_SWEET)

    def test_vencida_se_marca_expirada(self) -> None:
        hoy = timezone.localdate()
        suscripcion = Suscripcion.objects.create(
            usuario=self.usuario,
            estado=Suscripcion.ACTIVA,
            fecha_inicio=hoy - datetime.timedelta(days=40),
            fecha_fin=hoy - datetime.timedelta(days=1),
            monto_mensual=Decimal('99.00'),
        )
        self.assertEqual(Suscripcion.objects.plan_de(self.usuario), PLAN_BASIC)
        suscripcion.refresh_from_db()
        self.assertEqual(suscripcion.estado, Suscripcion.EXPIRADA)


class IngredientesVisiblesTests(TestCase):
    """Los ingredientes exclusivos solo se muestran con Sweet Plan."""

    def setUp(self) -> None:
        self.usuario = User.objects.create_user('beto', password='clave-segura-123')
        categoria = CategoriaIngrediente.objects.create(nombre='Topping')
        self.normal = Ingrediente.objects.create(categoria=categoria, nombre='Sprinkles')
        self.exclusivo = Ingrediente.objects.create(
            categoria=categoria, nombre='Oro comestible', solo_suscriptores=True
        )

    def test_basic_no_ve_exclusivos(self) -> None:
        visibles = Ingrediente.objects.de_categoria('topping').visibles_para(self.usuario)
        self.assertQuerySetEqual(visibles, [self.normal], ordered=False)

    def test_sweet_ve_exclusivos(self) -> None:
        Suscripcion.contratar_mes(self.usuario)
        visibles = Ingrediente.objects.de_categoria('topping').visibles_para(self.usuario)
        self.assertQuerySetEqual(visibles, [self.normal, self.exclusivo], ordered=False)


class PrecioCupcakeTests(TestCase):
    """El precio del cupcake se calcula solo en el servidor."""

    def test_precio_base_mas_extras(self) -> None:
        categoria = CategoriaIngrediente.objects.create(nombre='Base')
        chocolate = Ingrediente(categoria=categoria, nombre='Chocolate',
                                precio_adicional=Decimal('5.00'))
        fresa = Ingrediente(categoria=categoria, nombre='Fresa',
                            precio_adicional=Decimal('2.50'))
        precio = CupcakePersonalizado.calcular_precio([chocolate, None, fresa])
        self.assertEqual(precio, CupcakePersonalizado.PRECIO_BASE + Decimal('7.50'))


class PedidoTests(TestCase):
    """Registro de pedidos: total, stock e idempotencia."""

    def setUp(self) -> None:
        self.usuario = User.objects.create_user('caro', password='clave-segura-123')
        self.producto = Menu.objects.create(
            nombre_producto='Cupcake de fresa',
            descripcion='-',
            precio_base=Decimal('40.00'),
            stock=3,
        )

    def _crear(self, cantidad: int, total: Decimal, token: uuid.UUID | None = None) -> Pedido:
        return Pedido.objects.crear_desde_carrito(
            usuario=self.usuario,
            carrito={str(self.producto.pk): cantidad},
            direccion='Calle 1',
            checkout_token=token or uuid.uuid4(),
            total_esperado=total,
        )

    def test_crea_pedido_y_descuenta_stock(self) -> None:
        pedido = self._crear(2, Decimal('80.00'))
        self.producto.refresh_from_db()
        self.assertEqual(pedido.total, Decimal('80.00'))
        self.assertEqual(self.producto.stock, 1)
        self.assertEqual(pedido.detallepedido_set.count(), 1)

    def test_rechaza_si_no_hay_stock(self) -> None:
        with self.assertRaises(StockInsuficiente):
            self._crear(5, Decimal('200.00'))
        self.assertFalse(Pedido.objects.exists())

    def test_rechaza_si_cambio_el_precio(self) -> None:
        with self.assertRaises(PrecioCambiado):
            self._crear(1, Decimal('35.00'))
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 3)


class CheckoutVistaTests(TestCase):
    """Flujo HTTP completo del checkout."""

    def setUp(self) -> None:
        self.usuario = User.objects.create_user('dani', password='clave-segura-123')
        self.producto = Menu.objects.create(
            nombre_producto='Brownie', descripcion='-', precio_base=Decimal('45.00'), stock=5
        )
        self.client.force_login(self.usuario)

    def test_checkout_registra_pedido_y_vacia_carrito(self) -> None:
        self.client.post(reverse('agregar_carrito', args=[self.producto.pk]))
        self.client.get(reverse('checkout'))
        token = self.client.session['checkout_token']

        respuesta = self.client.post(reverse('checkout'), {
            'checkout_token': token,
            'direccion_entrega': 'Av. Siempre Viva 742',
        })

        pedido = Pedido.objects.get()
        self.assertRedirects(respuesta, reverse('pedido_confirmado', args=[pedido.pk]))
        self.assertEqual(self.client.session['carrito'], {})

    def test_token_reutilizado_no_duplica_pedido(self) -> None:
        self.client.post(reverse('agregar_carrito', args=[self.producto.pk]))
        self.client.get(reverse('checkout'))
        token = self.client.session['checkout_token']
        datos = {'checkout_token': token, 'direccion_entrega': 'Calle 2'}

        self.client.post(reverse('checkout'), datos)
        self.client.post(reverse('agregar_carrito', args=[self.producto.pk]))
        self.client.post(reverse('checkout'), datos)

        self.assertEqual(Pedido.objects.count(), 1)


class PaginasPublicasTests(TestCase):
    """Las páginas públicas responden sin error."""

    def test_inicio_carrito_y_suscripcion(self) -> None:
        for nombre in ('inicio', 'ver_carrito', 'suscripcion', 'login', 'registro'):
            with self.subTest(nombre=nombre):
                self.assertEqual(self.client.get(reverse(nombre)).status_code, 200)


class CamposVIPTests(TestCase):
    """Valores por defecto de los campos que agrega la capa VIP (fase 1)."""

    def test_pedido_sin_descuento_por_defecto(self) -> None:
        usuario = User.objects.create_user('dani', password='clave-segura-123')
        pedido = Pedido.objects.create(usuario=usuario, total=Decimal('10.00'), direccion_entrega='-')
        self.assertEqual(pedido.descuento_porcentaje, Decimal('0'))
        self.assertEqual(pedido.motivo_descuento, Pedido.SIN_DESCUENTO)

    def test_experiencia_qr_genera_codigos_unicos(self) -> None:
        usuario = User.objects.create_user('eva', password='clave-segura-123')
        datos = {'usuario': usuario, 'video': 'videos/demo.mp4', 'fecha_expiracion': timezone.now()}
        primera = ExperienciaQR.objects.create(**datos)
        segunda = ExperienciaQR.objects.create(**datos)
        self.assertGreaterEqual(len(primera.codigo_unico), 20)
        self.assertNotEqual(primera.codigo_unico, segunda.codigo_unico)
        self.assertIsNone(primera.detalle_pedido)
