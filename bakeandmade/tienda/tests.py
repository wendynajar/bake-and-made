"""Pruebas de la lógica de negocio de la tienda (modelos) y de los flujos HTTP críticos."""

import datetime
import uuid
from decimal import Decimal
from io import StringIO
from typing import Any
from unittest import mock

from django.contrib.auth.models import AnonymousUser, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from iot.models import TarjetaRFID
from usuarios.models import PerfilVIP

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
    aplicar_descuento,
    descuento_para,
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


class IngredientesExclusivosTests(TestCase):
    """`cargar_catalogo` deja un ingrediente premium por categoría solo para Sweet (#9)."""

    def test_cargar_catalogo_marca_los_exclusivos(self) -> None:
        call_command('cargar_catalogo', stdout=StringIO())

        exclusivos = set(
            Ingrediente.objects.filter(solo_suscriptores=True)
            .values_list('categoria__nombre', 'nombre')
        )
        self.assertEqual(exclusivos, {
            ('Base', 'Red velvet'),
            ('Relleno', 'Dulce de leche'),
            ('Cobertura', 'Queso crema'),
            ('Topping', 'Fresas'),
        })
        self.assertEqual(Ingrediente.objects.filter(solo_suscriptores=False).count(), 11)

    def test_basic_no_ve_los_exclusivos_y_sweet_si(self) -> None:
        call_command('cargar_catalogo', stdout=StringIO())
        usuario = User.objects.create_user('fer', password='clave-segura-123')

        bases_basic = set(Ingrediente.objects.de_categoria('Base').visibles_para(usuario).values_list('nombre', flat=True))
        Suscripcion.contratar_mes(usuario)
        bases_sweet = set(Ingrediente.objects.de_categoria('Base').visibles_para(usuario).values_list('nombre', flat=True))

        self.assertNotIn('Red velvet', bases_basic)
        self.assertIn('Red velvet', bases_sweet)


class DescuentoVIPTests(TestCase):
    """Reglas de descuento: 20 % Sweet, 50 % en su cumpleaños, 0 % sin Sweet."""

    HOY = datetime.date(2026, 11, 18)

    def setUp(self) -> None:
        self.usuario = User.objects.create_user('gabi', password='clave-segura-123')

    def con_cumple(self, nacimiento: datetime.date, registrado: datetime.date) -> None:
        PerfilVIP.objects.update_or_create(
            usuario=self.usuario,
            defaults={'fecha_nacimiento': nacimiento, 'cumple_registrado_en': registrado},
        )

    def test_anonimo_sin_descuento(self) -> None:
        self.assertEqual(descuento_para(AnonymousUser(), self.HOY), (Decimal('0'), ''))

    def test_basic_sin_descuento_y_sin_crear_perfil(self) -> None:
        self.assertEqual(descuento_para(self.usuario, self.HOY), (Decimal('0'), ''))
        self.assertFalse(PerfilVIP.objects.exists())

    def test_sweet_vigente_20(self) -> None:
        Suscripcion.contratar_mes(self.usuario)
        self.assertEqual(descuento_para(self.usuario, self.HOY), (Decimal('0.20'), Pedido.MOTIVO_VIP))

    def test_sweet_cancelado_antes_de_fecha_fin_sigue_con_20(self) -> None:
        Suscripcion.contratar_mes(self.usuario).cancelar()
        self.assertEqual(descuento_para(self.usuario, self.HOY)[0], Decimal('0.20'))

    def test_sweet_vencido_sin_descuento(self) -> None:
        hoy = timezone.localdate()
        Suscripcion.objects.create(
            usuario=self.usuario,
            estado=Suscripcion.ACTIVA,
            fecha_inicio=hoy - datetime.timedelta(days=40),
            fecha_fin=hoy - datetime.timedelta(days=10),
            monto_mensual=Decimal('99.00'),
        )
        self.assertEqual(descuento_para(self.usuario, self.HOY), (Decimal('0'), ''))

    def test_cumpleanios_de_sweet_50(self) -> None:
        Suscripcion.contratar_mes(self.usuario)
        self.con_cumple(datetime.date(1995, 11, 18), registrado=datetime.date(2026, 10, 1))
        self.assertEqual(
            descuento_para(self.usuario, self.HOY), (Decimal('0.50'), Pedido.MOTIVO_CUMPLEANIOS)
        )

    def test_cumpleanios_registrado_hoy_mismo_queda_en_20(self) -> None:
        Suscripcion.contratar_mes(self.usuario)
        self.con_cumple(datetime.date(1995, 11, 18), registrado=self.HOY)
        self.assertEqual(descuento_para(self.usuario, self.HOY), (Decimal('0.20'), Pedido.MOTIVO_VIP))

    def test_cumpleanios_sin_sweet_no_da_descuento(self) -> None:
        self.con_cumple(datetime.date(1995, 11, 18), registrado=datetime.date(2026, 10, 1))
        self.assertEqual(descuento_para(self.usuario, self.HOY), (Decimal('0'), ''))

    def test_nacido_29_feb_celebra_el_28_en_anio_no_bisiesto(self) -> None:
        Suscripcion.contratar_mes(self.usuario)
        self.con_cumple(datetime.date(2000, 2, 29), registrado=datetime.date(2026, 1, 5))
        casos = [
            (datetime.date(2027, 2, 28), Decimal('0.50')),
            (datetime.date(2027, 3, 1), Decimal('0.20')),
            (datetime.date(2028, 2, 28), Decimal('0.20')),
            (datetime.date(2028, 2, 29), Decimal('0.50')),
        ]
        for dia, esperado in casos:
            with self.subTest(dia=dia):
                self.assertEqual(descuento_para(self.usuario, dia)[0], esperado)


class AplicarDescuentoTests(TestCase):
    """Redondeo a centavos con Decimal, como en la tabla de la especificación."""

    def test_redondea_a_centavos_y_devuelve_decimal(self) -> None:
        precio = aplicar_descuento(Decimal('99.99'), Decimal('0.20'))
        self.assertEqual(precio, Decimal('79.99'))
        self.assertIsInstance(precio, Decimal)

    def test_tabla_de_la_especificacion(self) -> None:
        casos = [
            (Decimal('100.00'), Decimal('0'), Decimal('100.00')),
            (Decimal('100.00'), Decimal('0.20'), Decimal('80.00')),
            (Decimal('100.00'), Decimal('0.50'), Decimal('50.00')),
            (Decimal('35.00'), Decimal('0.20'), Decimal('28.00')),
            (Decimal('35.00'), Decimal('0.50'), Decimal('17.50')),
        ]
        for precio, descuento, esperado in casos:
            with self.subTest(precio=precio, descuento=descuento):
                self.assertEqual(aplicar_descuento(precio, descuento), esperado)

    def test_redondeo_half_up(self) -> None:
        # 0.25 x 0.5 = 0.125, que con ROUND_HALF_UP queda en 0.13 (no redondeo bancario).
        self.assertEqual(aplicar_descuento(Decimal('0.25'), Decimal('0.50')), Decimal('0.13'))


class TiendaVIPTests(TestCase):
    """Catálogo, carrito y barra con el descuento VIP (fase 5)."""

    def setUp(self) -> None:
        self.producto = Menu.objects.create(
            nombre_producto='Pastel de prueba', descripcion='-',
            precio_base=Decimal('100.00'), stock=5,
        )
        self.usuario = User.objects.create_user(
            'ana', password='clave-segura-123', first_name='Ana'
        )
        sesion = self.client.session
        sesion['carrito'] = {str(self.producto.pk): 1}
        sesion['carrito_personalizados'] = [{
            'nombre': 'Cupcake personalizado',
            'precio_unitario': '35.00',
            'cantidad': 1,
            'ingredientes': {},
        }]
        sesion.save()

    def carrito(self) -> Any:
        respuesta = self.client.get(reverse('ver_carrito'))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta

    def test_mismo_carrito_anonimo_y_luego_sweet(self) -> None:
        anonimo = self.carrito()
        self.assertEqual(anonimo.context['total'], Decimal('135.00'))
        self.assertFalse(anonimo.context['vip_activo'])

        Suscripcion.contratar_mes(self.usuario)
        self.client.force_login(self.usuario)
        sweet = self.carrito()

        lineas = {item['tipo']: item for item in sweet.context['productos_carrito']}
        self.assertEqual(lineas['normal']['precio_unitario'], Decimal('80.00'))
        self.assertEqual(lineas['personalizado']['precio_unitario'], Decimal('28.00'))
        self.assertEqual(sweet.context['subtotal'], Decimal('135.00'))
        self.assertEqual(sweet.context['ahorro'], Decimal('27.00'))
        self.assertEqual(sweet.context['total'], Decimal('108.00'))
        self.assertContains(sweet, 'Descuento VIP')

    def test_basic_ve_la_tienda_como_hoy(self) -> None:
        self.client.force_login(self.usuario)
        respuesta = self.client.get(reverse('inicio'))
        self.assertNotContains(respuesta, 'Membresía VIP')
        self.assertNotContains(respuesta, '<del')
        self.assertEqual(self.carrito().context['total'], Decimal('135.00'))

    def test_sweet_ve_pestana_vip_y_precio_tachado(self) -> None:
        Suscripcion.contratar_mes(self.usuario)
        self.client.force_login(self.usuario)

        respuesta = self.client.get(reverse('inicio'))

        self.assertContains(respuesta, 'Membresía VIP')
        self.assertContains(respuesta, 'VIP −20 %')
        self.assertContains(respuesta, '<del aria-label="Precio normal">$100.00</del>')
        self.assertContains(respuesta, '$80.00 MXN')

    def test_cumpleanios_muestra_50(self) -> None:
        Suscripcion.contratar_mes(self.usuario)
        hoy = timezone.localdate()
        PerfilVIP.objects.create(
            usuario=self.usuario,
            fecha_nacimiento=hoy.replace(year=1995) if (hoy.month, hoy.day) != (2, 29)
            else datetime.date(1996, 2, 29),
            cumple_registrado_en=hoy - datetime.timedelta(days=30),
        )
        self.client.force_login(self.usuario)

        respuesta = self.carrito()

        self.assertEqual(respuesta.context['total'], Decimal('67.50'))
        self.assertContains(respuesta, 'Cumpleaños −50 %')

    def test_el_plan_se_consulta_una_sola_vez_por_peticion(self) -> None:
        Suscripcion.contratar_mes(self.usuario)
        self.client.force_login(self.usuario)
        original = Suscripcion.objects.plan_de

        with mock.patch.object(
            type(Suscripcion.objects), 'plan_de', autospec=True, side_effect=lambda qs, u: original(u)
        ) as plan_de:
            self.carrito()

        self.assertEqual(plan_de.call_count, 1)


class KioscoPlantillaTests(TestCase):
    """polling.js y la barra del kiosco solo aparecen en navegadores vinculados."""

    def test_sin_terminal_no_hay_polling(self) -> None:
        respuesta = self.client.get(reverse('inicio'))
        self.assertNotContains(respuesta, 'iot/polling.js')

    def test_kiosco_anonimo_invita_a_pasar_la_tarjeta(self) -> None:
        sesion = self.client.session
        sesion['terminal'] = 'caja-1'
        sesion.save()

        respuesta = self.client.get(reverse('inicio'))

        self.assertContains(respuesta, 'iot/polling.js')
        self.assertContains(respuesta, 'Pasa tu tarjeta VIP')
        self.assertNotContains(respuesta, 'kiosco-salir')

    def test_sesion_por_tarjeta_muestra_saludo_y_salir(self) -> None:
        usuario = User.objects.create_user('ana', password='clave-segura-123', first_name='Ana')
        self.client.force_login(usuario)
        sesion = self.client.session
        sesion['terminal'] = 'caja-1'
        sesion['login_por_tarjeta'] = True
        sesion.save()

        respuesta = self.client.get(reverse('ver_carrito'))

        self.assertContains(respuesta, 'kiosco-salir')
        self.assertContains(respuesta, 'Hola, Ana')


class EntregaTarjetaMensajeTests(TestCase):
    """Al contratar el Sweet Plan la página confirma la entrega simulada de la tarjeta."""

    def setUp(self) -> None:
        self.usuario = User.objects.create_user('ana', password='clave-segura-123')
        self.client.force_login(self.usuario)

    def mensajes_al_contratar(self) -> list[str]:
        respuesta = self.client.post(reverse('confirmar_suscripcion'), follow=True)
        return [str(m) for m in respuesta.context['messages']]

    def test_con_tarjeta_libre_muestra_la_terminacion(self) -> None:
        TarjetaRFID.objects.create(uid='A1B2C3D4')
        mensajes = self.mensajes_al_contratar()
        self.assertTrue(any('termina en …D4' in m for m in mensajes), mensajes)

    def test_sin_tarjetas_libres_esta_en_camino(self) -> None:
        mensajes = self.mensajes_al_contratar()
        self.assertIn('Tu tarjeta VIP está en camino.', mensajes)
