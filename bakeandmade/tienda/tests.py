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

from .forms import DireccionEntregaForm
from .models import (
    PLAN_BASIC,
    PLAN_SWEET,
    CategoriaIngrediente,
    CupcakePersonalizado,
    ErrorPedido,
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


# Dirección válida para los POST del checkout (campos de DireccionEntregaForm).
DIRECCION = {
    'calle': 'Av. Siempre Viva',
    'numero_exterior': '742',
    'numero_interior': '',
    'colonia': 'Centro',
    'codigo_postal': '06000',
    'ciudad': 'Cuauhtémoc',
    'estado': 'CDMX',
    'referencias': '',
}


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
            **DIRECCION,
        })

        pedido = Pedido.objects.get()
        self.assertRedirects(respuesta, reverse('pedido_confirmado', args=[pedido.pk]))
        self.assertEqual(self.client.session['carrito'], {})

    def test_token_reutilizado_no_duplica_pedido(self) -> None:
        self.client.post(reverse('agregar_carrito', args=[self.producto.pk]))
        self.client.get(reverse('checkout'))
        token = self.client.session['checkout_token']
        datos = {'checkout_token': token, **DIRECCION}

        self.client.post(reverse('checkout'), datos)
        self.client.post(reverse('agregar_carrito', args=[self.producto.pk]))
        self.client.post(reverse('checkout'), datos)

        self.assertEqual(Pedido.objects.count(), 1)


class DireccionEntregaFormTests(TestCase):
    """La dirección se captura por campos y se guarda como un solo texto legible."""

    def test_arma_la_direccion_con_todos_los_campos(self) -> None:
        form = DireccionEntregaForm({
            **DIRECCION, 'numero_interior': '3B', 'referencias': 'Portón rosa,\n junto a la farmacia',
        })

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.como_texto(),
            'Av. Siempre Viva 742, int. 3B, col. Centro, C.P. 06000, Cuauhtémoc, CDMX. '
            'Referencias: Portón rosa, junto a la farmacia',
        )

    def test_omite_los_campos_opcionales_vacios(self) -> None:
        form = DireccionEntregaForm(DIRECCION)

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.como_texto(), 'Av. Siempre Viva 742, col. Centro, C.P. 06000, Cuauhtémoc, CDMX'
        )

    def test_codigo_postal_debe_tener_5_digitos(self) -> None:
        for codigo in ('0600', '060000', '06A00', ''):
            with self.subTest(codigo=codigo):
                form = DireccionEntregaForm({**DIRECCION, 'codigo_postal': codigo})
                self.assertFalse(form.is_valid())
                self.assertIn('codigo_postal', form.errors)

    def test_campos_obligatorios(self) -> None:
        form = DireccionEntregaForm({**DIRECCION, 'calle': '  ', 'colonia': ''})

        self.assertFalse(form.is_valid())
        self.assertEqual(set(form.errors), {'calle', 'colonia'})

    def test_respeta_las_longitudes_maximas(self) -> None:
        form = DireccionEntregaForm({**DIRECCION, 'referencias': 'x' * 501})

        self.assertFalse(form.is_valid())
        self.assertIn('referencias', form.errors)


class DireccionCheckoutVistaTests(TestCase):
    """El checkout muestra los campos de dirección y guarda el texto armado."""

    def setUp(self) -> None:
        self.usuario = User.objects.create_user('dani', password='clave-segura-123')
        self.producto = Menu.objects.create(
            nombre_producto='Brownie', descripcion='-', precio_base=Decimal('45.00'), stock=5
        )
        self.client.force_login(self.usuario)
        self.client.post(reverse('agregar_carrito', args=[self.producto.pk]))

    def test_el_formulario_tiene_los_campos_nuevos_y_no_el_viejo(self) -> None:
        respuesta = self.client.get(reverse('checkout'))

        for campo in ('calle', 'numero_exterior', 'numero_interior', 'colonia',
                      'codigo_postal', 'ciudad', 'estado', 'referencias'):
            self.assertContains(respuesta, f'name="{campo}"')
        self.assertNotContains(respuesta, 'name="direccion_entrega"')

    def test_guarda_la_direccion_armada(self) -> None:
        self.client.get(reverse('checkout'))
        self.client.post(reverse('checkout'), {
            'checkout_token': self.client.session['checkout_token'], **DIRECCION,
        })

        self.assertEqual(
            Pedido.objects.get().direccion_entrega,
            'Av. Siempre Viva 742, col. Centro, C.P. 06000, Cuauhtémoc, CDMX',
        )

    def test_direccion_invalida_no_crea_pedido_y_conserva_lo_escrito(self) -> None:
        self.client.get(reverse('checkout'))
        respuesta = self.client.post(reverse('checkout'), {
            'checkout_token': self.client.session['checkout_token'],
            **DIRECCION, 'codigo_postal': '123',
        })

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Pedido.objects.count(), 0)
        self.assertContains(respuesta, 'value="Av. Siempre Viva"')
        self.assertContains(respuesta, 'value="123"')
        self.assertContains(respuesta, 'El código postal debe tener 5 dígitos.')


class CarritoConCupcakesMixin:
    """Usuario con sesión, un Brownie de $45 e ingredientes que suman un cupcake de $49."""

    def setUp(self) -> None:
        self.usuario = User.objects.create_user('dani', password='clave-segura-123')
        self.client.force_login(self.usuario)
        self.producto = Menu.objects.create(
            nombre_producto='Brownie', descripcion='-', precio_base=Decimal('45.00'), stock=5
        )
        precios = {'Base': '0.00', 'Relleno': '5.00', 'Cobertura': '7.00', 'Topping': '2.00'}
        self.ingredientes = {}
        for categoria, precio in precios.items():
            self.ingredientes[categoria.lower()] = Ingrediente.objects.create(
                categoria=CategoriaIngrediente.objects.create(nombre=categoria),
                nombre=f'{categoria} de prueba',
                precio_adicional=Decimal(precio),
                stock_disponible=10,
            )
        # $35 + 0 + 5 + 7 + 2
        self.precio_cupcake = Decimal('49.00')

    def cupcake(self, cantidad: int = 1, **cambios: Any) -> dict[str, Any]:
        datos = {
            'tipo': 'cupcake_personalizado',
            'nombre': 'Cupcake personalizado',
            'ingredientes': {
                slug: {'id': ingrediente.pk, 'nombre': ingrediente.nombre}
                for slug, ingrediente in self.ingredientes.items()
            },
            'dietas': ['vegano', 'inventada'],
            'color_frosting': 'rosa',
            'precio_unitario': str(self.precio_cupcake),
            'cantidad': cantidad,
        }
        datos.update(cambios)
        return datos

    def con_carrito(self, personalizados: list[dict[str, Any]], productos: int = 0) -> None:
        sesion = self.client.session
        sesion['carrito'] = {str(self.producto.pk): productos} if productos else {}
        sesion['carrito_personalizados'] = personalizados
        sesion.save()

    def comprar(self) -> Any:
        self.client.get(reverse('checkout'))
        return self.client.post(reverse('checkout'), {
            'checkout_token': self.client.session.get('checkout_token', ''),
            **DIRECCION,
        })

    def stock(self, slug: str) -> int:
        return Ingrediente.objects.get(pk=self.ingredientes[slug].pk).stock_disponible


class CheckoutPersonalizadosTests(CarritoConCupcakesMixin, TestCase):
    """Checkout de cupcakes personalizados (hallazgos #7 y #8, fase 6)."""

    def test_solo_personalizados_crea_el_pedido(self) -> None:
        self.con_carrito([self.cupcake(cantidad=2)])

        respuesta = self.comprar()

        pedido = Pedido.objects.get()
        self.assertRedirects(respuesta, reverse('pedido_confirmado', args=[pedido.pk]))
        self.assertEqual(pedido.total, Decimal('98.00'))
        detalle = pedido.detallepedido_set.get()
        self.assertEqual(detalle.cantidad, 2)
        self.assertEqual(detalle.precio_unitario, self.precio_cupcake)
        cupcake = detalle.cupcake_custom
        self.assertEqual(cupcake.usuario, self.usuario)
        self.assertEqual(cupcake.precio_calculado, self.precio_cupcake)
        self.assertEqual(cupcake.dietas, ['vegano'])
        self.assertEqual(cupcake.color_frosting, 'rosa')
        self.assertEqual(
            set(cupcake.ingredientes.values_list('pk', flat=True)),
            {i.pk for i in self.ingredientes.values()},
        )

    def test_descuenta_stock_de_ingredientes_y_vacia_ambos_carritos(self) -> None:
        self.con_carrito([self.cupcake(cantidad=2), self.cupcake(cantidad=1)], productos=1)

        self.comprar()

        for slug in self.ingredientes:
            self.assertEqual(self.stock(slug), 7)
        self.assertEqual(self.client.session['carrito'], {})
        self.assertEqual(self.client.session['carrito_personalizados'], [])

    def test_mezcla_productos_y_personalizados(self) -> None:
        self.con_carrito([self.cupcake()], productos=2)

        self.comprar()

        pedido = Pedido.objects.get()
        self.assertEqual(pedido.total, Decimal('90.00') + self.precio_cupcake)
        self.assertEqual(pedido.detallepedido_set.count(), 2)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 3)

    def test_el_precio_de_la_sesion_no_se_usa_para_cobrar(self) -> None:
        self.con_carrito([self.cupcake(precio_unitario='1.00')])

        respuesta = self.client.get(reverse('checkout'))

        self.assertEqual(respuesta.context['total'], self.precio_cupcake)

    def rechaza_sin_cambios(self, mensaje: str) -> None:
        respuesta = self.comprar()
        self.assertFalse(Pedido.objects.exists())
        self.assertFalse(CupcakePersonalizado.objects.exists())
        self.assertEqual(self.stock('base'), 10)
        self.assertRedirects(respuesta, reverse('ver_carrito'), fetch_redirect_response=False)
        mensajes = [str(m) for m in self.client.get(reverse('ver_carrito')).context['messages']]
        self.assertTrue(any(mensaje in m for m in mensajes), mensajes)

    def test_ingrediente_desactivado(self) -> None:
        self.con_carrito([self.cupcake()])
        Ingrediente.objects.filter(pk=self.ingredientes['relleno'].pk).update(activo=False)
        self.rechaza_sin_cambios('relleno de tu cupcake ya no está disponible')

    def test_ingrediente_exclusivo_sin_sweet(self) -> None:
        self.con_carrito([self.cupcake()])
        Ingrediente.objects.filter(pk=self.ingredientes['topping'].pk).update(solo_suscriptores=True)
        self.rechaza_sin_cambios('topping de tu cupcake ya no está disponible')

    def test_ingrediente_exclusivo_con_sweet_si_se_vende(self) -> None:
        Suscripcion.contratar_mes(self.usuario)
        Ingrediente.objects.filter(pk=self.ingredientes['topping'].pk).update(solo_suscriptores=True)
        self.con_carrito([self.cupcake()])
        self.comprar()
        self.assertTrue(Pedido.objects.exists())

    def test_ingrediente_de_otra_categoria(self) -> None:
        cupcake = self.cupcake()
        cupcake['ingredientes']['base'] = {'id': self.ingredientes['topping'].pk, 'nombre': 'x'}
        self.con_carrito([cupcake])
        self.rechaza_sin_cambios('base de tu cupcake ya no está disponible')

    def test_stock_insuficiente_entre_varios_cupcakes(self) -> None:
        Ingrediente.objects.filter(pk=self.ingredientes['base'].pk).update(stock_disponible=2)
        self.con_carrito([self.cupcake(cantidad=2), self.cupcake(cantidad=1)])

        respuesta = self.comprar()

        self.assertFalse(Pedido.objects.exists())
        self.assertEqual(self.stock('base'), 2)
        self.assertEqual(self.stock('relleno'), 10)
        self.assertRedirects(respuesta, reverse('ver_carrito'), fetch_redirect_response=False)

    def test_datos_corruptos_en_la_sesion(self) -> None:
        for corrupto in ('texto', {'ingredientes': 'x'}, self.cupcake(cantidad=0)):
            with self.subTest(corrupto=corrupto):
                self.con_carrito([corrupto])
                self.rechaza_sin_cambios('no es válido')

    def test_el_modelo_rechaza_un_carrito_vacio(self) -> None:
        with self.assertRaises(ErrorPedido):
            Pedido.objects.crear_desde_carrito(
                usuario=self.usuario, carrito={}, direccion='x',
                checkout_token=uuid.uuid4(), total_esperado=Decimal('0'), personalizados=[],
            )


class CheckoutVIPTests(CarritoConCupcakesMixin, TestCase):
    """Checkout con el descuento VIP (fase 7): se cobra y se guarda lo descontado."""

    def hacer_sweet(self) -> None:
        Suscripcion.contratar_mes(self.usuario)

    def test_sweet_guarda_descuento_y_precios_descontados(self) -> None:
        self.hacer_sweet()
        # Brownie $45 x2 -> $36 c/u; cupcake $49 -> $39.20
        self.con_carrito([self.cupcake()], productos=2)

        self.comprar()

        pedido = Pedido.objects.get()
        self.assertEqual(pedido.descuento_porcentaje, Decimal('0.20'))
        self.assertEqual(pedido.motivo_descuento, Pedido.MOTIVO_VIP)
        self.assertEqual(pedido.total, Decimal('111.20'))
        precios = {
            'producto' if d.menu_item_id else 'cupcake': d.precio_unitario
            for d in pedido.detallepedido_set.all()
        }
        self.assertEqual(precios, {'producto': Decimal('36.00'), 'cupcake': Decimal('39.20')})
        self.assertEqual(
            sum(d.precio_unitario * d.cantidad for d in pedido.detallepedido_set.all()),
            pedido.total,
        )
        # El cupcake conserva su precio base calculado; lo cobrado está en la línea.
        self.assertEqual(CupcakePersonalizado.objects.get().precio_calculado, Decimal('49.00'))

    def test_cumpleanios_cobra_50(self) -> None:
        self.hacer_sweet()
        hoy = timezone.localdate()
        PerfilVIP.objects.create(
            usuario=self.usuario,
            fecha_nacimiento=hoy.replace(year=1995) if (hoy.month, hoy.day) != (2, 29)
            else datetime.date(1996, 2, 29),
            cumple_registrado_en=hoy - datetime.timedelta(days=30),
        )
        self.con_carrito([self.cupcake()])

        self.comprar()

        pedido = Pedido.objects.get()
        self.assertEqual(pedido.descuento_porcentaje, Decimal('0.50'))
        self.assertEqual(pedido.motivo_descuento, Pedido.MOTIVO_CUMPLEANIOS)
        self.assertEqual(pedido.total, Decimal('24.50'))

    def test_basic_sin_descuento(self) -> None:
        self.con_carrito([self.cupcake()], productos=1)

        self.comprar()

        pedido = Pedido.objects.get()
        self.assertEqual(pedido.descuento_porcentaje, Decimal('0'))
        self.assertEqual(pedido.motivo_descuento, '')
        self.assertEqual(pedido.total, Decimal('94.00'))

    def test_desglose_en_el_checkout_y_en_la_confirmacion(self) -> None:
        self.hacer_sweet()
        self.con_carrito([self.cupcake()], productos=2)

        resumen = self.client.get(reverse('checkout'))

        self.assertEqual(resumen.context['subtotal'], Decimal('139.00'))
        self.assertEqual(resumen.context['ahorro'], Decimal('27.80'))
        self.assertEqual(resumen.context['total'], Decimal('111.20'))
        self.assertContains(resumen, 'Descuento VIP')

        respuesta = self.client.post(reverse('checkout'), {
            'checkout_token': self.client.session['checkout_token'],
            **DIRECCION,
        }, follow=True)
        self.assertContains(respuesta, 'Descuento aplicado')
        self.assertContains(respuesta, 'VIP')
        self.assertContains(respuesta, '−20 %')

    def test_token_reutilizado_no_duplica_el_pedido(self) -> None:
        self.hacer_sweet()
        self.con_carrito([self.cupcake()])
        self.client.get(reverse('checkout'))
        datos = {'checkout_token': self.client.session['checkout_token'], **DIRECCION}

        self.client.post(reverse('checkout'), datos)
        self.con_carrito([self.cupcake()])
        self.client.post(reverse('checkout'), datos)

        self.assertEqual(Pedido.objects.count(), 1)

    def test_si_el_descuento_cambia_entre_get_y_post_no_cobra(self) -> None:
        self.hacer_sweet()
        self.con_carrito([self.cupcake()])
        self.client.get(reverse('checkout'))
        token = self.client.session['checkout_token']

        # El Sweet vence antes de confirmar: el total cambia de $39.20 a $49.00.
        Suscripcion.objects.filter(usuario=self.usuario).update(
            fecha_fin=timezone.localdate() - datetime.timedelta(days=1)
        )
        respuesta = self.client.post(reverse('checkout'), {
            'checkout_token': token, **DIRECCION,
        })

        self.assertRedirects(respuesta, reverse('checkout'), fetch_redirect_response=False)
        self.assertFalse(Pedido.objects.exists())

    def test_el_modelo_valida_descuento_y_motivo(self) -> None:
        argumentos = {
            'usuario': self.usuario, 'carrito': {str(self.producto.pk): 1},
            'direccion': 'x', 'checkout_token': uuid.uuid4(), 'total_esperado': Decimal('45.00'),
        }
        for descuento, motivo in ((Decimal('1.5'), 'vip'), (Decimal('0.20'), ''), (Decimal('0'), 'vip'),
                                  (Decimal('0.20'), 'inventado')):
            with self.subTest(descuento=descuento, motivo=motivo), self.assertRaises(ValueError):
                Pedido.objects.crear_desde_carrito(**argumentos, descuento=descuento, motivo=motivo)
        self.assertFalse(Pedido.objects.exists())


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


class ImagenesCatalogoTests(TestCase):
    """`cargar_catalogo` pone la imagen de cada producto sin pisar la del admin."""

    def test_crea_los_productos_con_su_imagen(self) -> None:
        call_command('cargar_catalogo', stdout=StringIO())

        producto = Menu.objects.get(nombre_producto='Cupcake red velvet')
        self.assertEqual(producto.imagen.name, 'productos/crv.jpg')

    def test_completa_la_imagen_de_un_producto_existente_sin_imagen(self) -> None:
        Menu.objects.create(nombre_producto='Cupcake red velvet', descripcion='-', precio_base=Decimal('45.00'))

        call_command('cargar_catalogo', stdout=StringIO())

        producto = Menu.objects.get(nombre_producto='Cupcake red velvet')
        self.assertEqual(producto.imagen.name, 'productos/crv.jpg')

    def test_no_reemplaza_la_imagen_puesta_en_el_admin(self) -> None:
        Menu.objects.create(
            nombre_producto='Cupcake red velvet', descripcion='-',
            precio_base=Decimal('45.00'), imagen='productos/nueva.jpg',
        )

        call_command('cargar_catalogo', stdout=StringIO())

        producto = Menu.objects.get(nombre_producto='Cupcake red velvet')
        self.assertEqual(producto.imagen.name, 'productos/nueva.jpg')


class EncabezadoComunTests(TestCase):
    """Todas las páginas de la tienda usan el mismo encabezado (el de "Mi carrito")."""

    def setUp(self) -> None:
        self.usuario = User.objects.create_user('lia', password='clave-segura-123', first_name='Lía')
        self.producto = Menu.objects.create(
            nombre_producto='Brownie', descripcion='-', precio_base=Decimal('45.00'), stock=5
        )

    def test_las_paginas_incluyen_el_encabezado_comun(self) -> None:
        self.client.force_login(self.usuario)
        self.client.post(reverse('agregar_carrito', args=[self.producto.pk]))
        Suscripcion.contratar_mes(self.usuario)

        for nombre in ('inicio', 'ver_carrito', 'checkout', 'suscripcion', 'personalizar', 'vip'):
            with self.subTest(pagina=nombre):
                respuesta = self.client.get(reverse(nombre))
                self.assertTemplateUsed(respuesta, 'tienda/_encabezado.html')
                self.assertContains(respuesta, 'class="premium-header"', count=1)
                self.assertContains(respuesta, 'Hola, Lía')

    def test_el_carrito_muestra_el_contador(self) -> None:
        self.client.post(reverse('agregar_carrito', args=[self.producto.pk]))
        self.client.post(reverse('agregar_carrito', args=[self.producto.pk]))

        respuesta = self.client.get(reverse('inicio'))

        self.assertContains(respuesta, '<span class="cart-count">2</span>', html=True)
        self.assertContains(respuesta, 'Mi cuenta')


class ImagenFaltanteTests(TestCase):
    """Si el archivo de la imagen no existe, el navegador muestra el logo en su lugar."""

    def test_la_tarjeta_trae_el_logo_de_respaldo(self) -> None:
        Menu.objects.create(
            nombre_producto='Brownie', descripcion='-', precio_base=Decimal('45.00'),
            stock=5, imagen='productos/no-existe.jpg',
        )

        respuesta = self.client.get(reverse('inicio'))

        self.assertContains(respuesta, '<template><div class="product-no-image">Bake & Made</div></template>')
        self.assertContains(respuesta, 'onerror="this.replaceWith(this.previousElementSibling.content.cloneNode(true))"')


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
        self.assertNotContains(respuesta, 'class="nav-vip"')
        self.assertNotContains(respuesta, '<del')
        self.assertEqual(self.carrito().context['total'], Decimal('135.00'))

    def test_sweet_ve_pestana_vip_y_precio_tachado(self) -> None:
        Suscripcion.contratar_mes(self.usuario)
        self.client.force_login(self.usuario)

        respuesta = self.client.get(reverse('inicio'))

        self.assertContains(respuesta, 'class="nav-vip">VIP</a>')
        self.assertNotContains(respuesta, 'Membresía VIP')
        self.assertNotContains(respuesta, 'VIP −20 %')
        self.assertContains(respuesta, '<del aria-label="Precio normal">$100.00</del>')
        self.assertContains(respuesta, '$80.00 MXN')

    def test_pestana_vip_va_entre_el_carrito_y_el_saludo(self) -> None:
        Suscripcion.contratar_mes(self.usuario)
        self.client.force_login(self.usuario)

        for pagina in ('inicio', 'ver_carrito', 'suscripcion'):
            with self.subTest(pagina=pagina):
                html = self.client.get(reverse(pagina)).content.decode()
                nav = html[html.index('<nav class="premium-nav"'):html.index('</nav>')]
                carrito = nav.index(reverse('ver_carrito'))
                vip = nav.index('class="nav-vip"')
                saludo = nav.index('user-greeting')
                self.assertLess(carrito, vip)
                self.assertLess(vip, saludo)

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
        self.assertTrue(respuesta.context['vip_es_cumpleanios'])

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
