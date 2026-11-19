"""Pruebas de la app iot (fases 1, 2 y 4 de docs/IOT_VIP_SPEC.md)."""

import datetime
import json
from decimal import Decimal
from io import StringIO
from typing import Any

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tienda.models import PLAN_SWEET, Suscripcion

from .models import LecturaRFID, TarjetaRFID, Terminal, normalizar_uid


class NormalizarUidTests(TestCase):
    """El mismo UID escrito de distintas formas debe ser una sola tarjeta."""

    def test_quita_separadores_y_pasa_a_mayusculas(self) -> None:
        self.assertEqual(normalizar_uid(' a1:b2-c3 d4 '), 'A1B2C3D4')

    def test_save_guarda_el_uid_normalizado(self) -> None:
        tarjeta = TarjetaRFID.objects.create(uid='a1:b2:c3:d4')
        self.assertEqual(tarjeta.uid, 'A1B2C3D4')

    def test_no_permite_duplicados_escritos_distinto(self) -> None:
        TarjetaRFID.objects.create(uid='A1B2C3D4')
        with self.assertRaises(IntegrityError):
            TarjetaRFID.objects.create(uid='a1 b2 c3 d4')

    def test_full_clean_rechaza_uid_que_no_es_hexadecimal(self) -> None:
        with self.assertRaises(ValidationError):
            TarjetaRFID(uid='HOLA1234').full_clean()

    def test_full_clean_acepta_uid_de_7_bytes(self) -> None:
        tarjeta = TarjetaRFID(uid='04:a1:b2:c3:d4:e5:f6')
        tarjeta.full_clean()
        self.assertEqual(tarjeta.uid, '04A1B2C3D4E5F6')


class TarjetasLibresTests(TestCase):
    """Inventario: solo cuentan las tarjetas activas y sin dueño, en orden de alta."""

    def test_libres_excluye_asignadas_e_inactivas(self) -> None:
        dueno = User.objects.create_user('ana', password='x')
        primera = TarjetaRFID.objects.create(uid='00000001')
        TarjetaRFID.objects.create(uid='00000002', usuario=dueno)
        TarjetaRFID.objects.create(uid='00000003', activa=False)
        ultima = TarjetaRFID.objects.create(uid='00000004')

        self.assertEqual(list(TarjetaRFID.objects.libres()), [primera, ultima])


class ComandosIotTests(TestCase):
    """`crear_terminal` y `registrar_tarjeta` se pueden repetir sin duplicar."""

    def ejecutar(self, *argumentos: str) -> str:
        salida = StringIO()
        call_command(*argumentos, stdout=salida)
        return salida.getvalue()

    def test_crear_terminal_es_idempotente(self) -> None:
        self.ejecutar('crear_terminal', 'caja-1')
        mensaje = self.ejecutar('crear_terminal', 'caja-1')
        self.assertEqual(Terminal.objects.filter(codigo='caja-1').count(), 1)
        self.assertIn('ya existía', mensaje)

    def test_crear_terminal_rechaza_codigo_invalido(self) -> None:
        with self.assertRaises(CommandError):
            self.ejecutar('crear_terminal', 'caja 1!')
        self.assertFalse(Terminal.objects.exists())

    def test_registrar_tarjeta_normaliza_y_no_duplica(self) -> None:
        self.ejecutar('registrar_tarjeta', 'a1:b2:c3:d4')
        mensaje = self.ejecutar('registrar_tarjeta', 'A1B2C3D4')
        tarjeta = TarjetaRFID.objects.get()
        self.assertEqual(tarjeta.uid, 'A1B2C3D4')
        self.assertIsNone(tarjeta.usuario)
        self.assertIn('ya estaba registrada', mensaje)

    def test_registrar_tarjeta_rechaza_uid_invalido(self) -> None:
        with self.assertRaises(CommandError):
            self.ejecutar('registrar_tarjeta', 'XYZ')
        self.assertFalse(TarjetaRFID.objects.exists())


class EntregaTarjetaTests(TestCase):
    """Entrega simulada de la tarjeta al contratar el Sweet Plan."""

    def setUp(self) -> None:
        self.usuario = User.objects.create_user('ana', password='x')

    def test_contratar_asigna_la_primera_tarjeta_libre(self) -> None:
        primera = TarjetaRFID.objects.create(uid='00000001')
        TarjetaRFID.objects.create(uid='00000002')

        Suscripcion.contratar_mes(self.usuario)

        primera.refresh_from_db()
        self.assertEqual(primera.usuario, self.usuario)
        self.assertIsNotNone(primera.entregada_en)
        self.assertEqual(TarjetaRFID.objects.libres().count(), 1)

    def test_renovar_no_asigna_otra_tarjeta(self) -> None:
        TarjetaRFID.objects.create(uid='00000001')
        TarjetaRFID.objects.create(uid='00000002')

        Suscripcion.contratar_mes(self.usuario)
        Suscripcion.contratar_mes(self.usuario)

        self.assertEqual(TarjetaRFID.objects.filter(usuario=self.usuario).count(), 1)
        self.assertEqual(TarjetaRFID.objects.libres().count(), 1)

    def test_sin_tarjetas_libres_la_suscripcion_sigue(self) -> None:
        Suscripcion.contratar_mes(self.usuario)

        self.assertEqual(Suscripcion.objects.plan_de(self.usuario), PLAN_SWEET)
        self.assertFalse(TarjetaRFID.objects.filter(usuario=self.usuario).exists())

    def test_tarjeta_inactiva_no_se_reemplaza_sola(self) -> None:
        TarjetaRFID.objects.create(uid='00000001', usuario=self.usuario, activa=False)
        TarjetaRFID.objects.create(uid='00000002')

        tarjeta = TarjetaRFID.objects.entregar_a(self.usuario)

        self.assertEqual(tarjeta.uid, '00000001')
        self.assertEqual(TarjetaRFID.objects.libres().count(), 1)


# =============================================================================
# Fase 4: API del lector e inicio de sesión por tarjeta
# =============================================================================

TOKEN = 'token-de-prueba-esp32'


class EscenarioKioscoMixin:
    """Terminal caja-1, dos clientes Sweet con tarjeta (Ana y Bruno) y un Basic."""

    def setUp(self) -> None:
        self.terminal = Terminal.objects.create(codigo='caja-1')
        self.ana = self.crear_cliente('ana', 'Ana', 'A1B2C3D4', sweet=True)
        self.bruno = self.crear_cliente('bruno', 'Bruno', 'B2C3D4E5', sweet=True)
        self.vencido = self.crear_cliente('vero', 'Vero', 'C3D4E5F6', sweet=False)
        self.esp32 = Client()

    def crear_cliente(self, username: str, nombre: str, uid: str, sweet: bool) -> User:
        usuario = User.objects.create_user(username, password='clave-segura-123', first_name=nombre)
        TarjetaRFID.objects.create(uid=uid, usuario=usuario)
        if sweet:
            Suscripcion.contratar_mes(usuario)
        else:
            hoy = timezone.localdate()
            Suscripcion.objects.create(
                usuario=usuario,
                estado=Suscripcion.ACTIVA,
                fecha_inicio=hoy - datetime.timedelta(days=40),
                fecha_fin=hoy - datetime.timedelta(days=10),
                monto_mensual=Decimal('99.00'),
            )
        return usuario

    def escanear(self, uid: str, token: str = TOKEN, terminal: str = 'caja-1') -> Any:
        return self.esp32.post(
            reverse('rfid_scan'),
            data=json.dumps({'uid': uid, 'terminal': terminal}),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {token}',
        )


@override_settings(IOT_DEVICE_TOKEN=TOKEN)
class ScanAPITests(EscenarioKioscoMixin, TestCase):
    """POST /api/rfid/scan/ tal como lo llama el ESP32."""

    def test_tarjeta_de_sweet_vigente(self) -> None:
        respuesta = self.escanear('A1B2C3D4')

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json(), {'status': 'ok', 'cliente': 'Ana'})
        self.terminal.refresh_from_db()
        self.assertEqual(self.terminal.tarjeta_activa.usuario, self.ana)
        self.assertEqual(self.terminal.version, 1)

    def test_mes_no_pagado_no_valida(self) -> None:
        respuesta = self.escanear('C3D4E5F6')

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(respuesta.json(), {'status': 'sin_sweet'})
        self.terminal.refresh_from_db()
        self.assertIsNone(self.terminal.tarjeta_activa)
        self.assertEqual(self.terminal.ultimo_rechazo, 'sin_sweet')

    def test_desconocida_libre_o_inactiva_da_404_y_queda_en_bitacora(self) -> None:
        TarjetaRFID.objects.create(uid='DDDDDDDD')
        TarjetaRFID.objects.filter(uid='B2C3D4E5').update(activa=False)

        for uid in ('FFFFFFFF', 'DDDDDDDD', 'B2C3D4E5'):
            with self.subTest(uid=uid):
                respuesta = self.escanear(uid)
                self.assertEqual(respuesta.status_code, 404)
                self.assertEqual(respuesta.json(), {'status': 'desconocida'})
        self.assertEqual(LecturaRFID.objects.filter(resultado='desconocida').count(), 3)

    def test_uid_en_minusculas_o_con_espacios(self) -> None:
        self.assertEqual(self.escanear(' a1 b2:c3 d4 ').status_code, 200)

    def test_sin_token_o_token_incorrecto(self) -> None:
        sin_token = self.esp32.post(
            reverse('rfid_scan'),
            data=json.dumps({'uid': 'A1B2C3D4', 'terminal': 'caja-1'}),
            content_type='application/json',
        )
        self.assertEqual(sin_token.status_code, 401)
        self.assertEqual(self.escanear('A1B2C3D4', token='otro').status_code, 401)
        self.terminal.refresh_from_db()
        self.assertEqual(self.terminal.version, 0)
        self.assertFalse(LecturaRFID.objects.exists())

    @override_settings(IOT_DEVICE_TOKEN='')
    def test_sin_token_configurado_rechaza_todo(self) -> None:
        self.assertEqual(self.escanear('A1B2C3D4', token='').status_code, 401)
        self.assertEqual(self.escanear('A1B2C3D4', token='cualquiera').status_code, 401)

    def test_cuerpo_invalido_o_terminal_desconocida(self) -> None:
        malo = self.esp32.post(
            reverse('rfid_scan'), data='no es json', content_type='application/json',
            HTTP_AUTHORIZATION=f'Token {TOKEN}',
        )
        self.assertEqual(malo.status_code, 400)
        self.assertEqual(self.escanear('A1B2C3D4', terminal='caja-9').status_code, 400)
        self.assertEqual(self.escanear('A' * 100).status_code, 400)

    def test_solo_acepta_post(self) -> None:
        self.assertEqual(self.esp32.get(reverse('rfid_scan')).status_code, 405)


@override_settings(IOT_DEVICE_TOKEN=TOKEN)
class LoginTarjetaTests(EscenarioKioscoMixin, TestCase):
    """Sincronización de la sesión del kiosco con /api/iot/estado/."""

    def setUp(self) -> None:
        super().setUp()
        sesion = self.client.session
        sesion['terminal'] = 'caja-1'
        sesion['iot_version'] = 0
        sesion['carrito'] = {'1': 2}
        sesion.save()

    def estado(self) -> dict[str, Any]:
        respuesta = self.client.get(reverse('iot_estado'))
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.json()

    def usuario_en_sesion(self) -> int | None:
        valor = self.client.session.get('_auth_user_id')
        return int(valor) if valor else None

    def test_escaneo_inicia_sesion_y_conserva_el_carrito(self) -> None:
        self.escanear('A1B2C3D4')
        estado = self.estado()

        self.assertTrue(estado['recargar'])
        self.assertEqual(self.usuario_en_sesion(), self.ana.pk)
        self.assertEqual(self.client.session['carrito'], {'1': 2})
        self.assertTrue(self.client.session['login_por_tarjeta'])

    def test_sin_cambios_no_recarga(self) -> None:
        self.escanear('A1B2C3D4')
        self.estado()
        self.assertFalse(self.estado()['recargar'])
        self.assertEqual(self.usuario_en_sesion(), self.ana.pk)

    def test_tarjeta_a_y_luego_b(self) -> None:
        self.escanear('A1B2C3D4')
        self.estado()
        self.escanear('B2C3D4E5')
        self.assertTrue(self.estado()['recargar'])

        self.assertEqual(self.usuario_en_sesion(), self.bruno.pk)
        self.assertEqual(self.client.session['carrito'], {'1': 2})
        self.assertEqual(self.client.session['terminal'], 'caja-1')

    def test_salir_cierra_la_sesion_y_vacia_el_carrito(self) -> None:
        self.escanear('A1B2C3D4')
        self.estado()

        respuesta = self.client.post(reverse('iot_salir'))

        self.assertTrue(respuesta.json()['recargar'])
        self.assertIsNone(self.usuario_en_sesion())
        self.assertNotIn('carrito', self.client.session)
        self.assertEqual(self.client.session['terminal'], 'caja-1')
        self.terminal.refresh_from_db()
        self.assertIsNone(self.terminal.tarjeta_activa)

    def test_cinco_minutos_sin_navegar_cierran_la_sesion(self) -> None:
        self.escanear('A1B2C3D4')
        self.estado()
        hace_6_min = timezone.now() - datetime.timedelta(minutes=6)
        Terminal.objects.filter(pk=self.terminal.pk).update(ultima_actividad=hace_6_min)

        self.assertTrue(self.estado()['recargar'])
        self.assertIsNone(self.usuario_en_sesion())
        self.assertEqual(self.client.session['terminal'], 'caja-1')

    def test_navegar_cuenta_como_actividad_y_el_polling_no(self) -> None:
        self.escanear('A1B2C3D4')
        self.estado()
        hace_4_min = timezone.now() - datetime.timedelta(minutes=4)

        Terminal.objects.filter(pk=self.terminal.pk).update(ultima_actividad=hace_4_min)
        self.estado()
        self.terminal.refresh_from_db()
        self.assertEqual(self.terminal.ultima_actividad, hace_4_min)

        self.client.get(reverse('inicio'))
        self.terminal.refresh_from_db()
        self.assertGreater(self.terminal.ultima_actividad, hace_4_min)

    def test_tarjeta_invalida_cierra_tambien_la_sesion_con_contrasena(self) -> None:
        self.client.force_login(self.bruno)
        self.escanear('FFFFFFFF')

        estado = self.estado()

        self.assertTrue(estado['recargar'])
        self.assertEqual(estado['rechazo'], 'desconocida')
        self.assertIsNone(self.usuario_en_sesion())

    def test_tarjeta_vencida_no_inicia_sesion(self) -> None:
        self.escanear('C3D4E5F6')
        estado = self.estado()

        self.assertEqual(estado['rechazo'], 'sin_sweet')
        self.assertIsNone(self.usuario_en_sesion())

    def test_un_rechazo_viejo_no_saca_a_quien_entra_despues(self) -> None:
        self.escanear('FFFFFFFF')
        self.estado()
        self.client.force_login(self.bruno)

        self.assertFalse(self.estado()['recargar'])
        self.assertEqual(self.usuario_en_sesion(), self.bruno.pk)

    def test_la_expiracion_no_saca_a_quien_entro_con_contrasena(self) -> None:
        self.client.force_login(self.bruno)
        self.estado()
        self.assertEqual(self.usuario_en_sesion(), self.bruno.pk)

    def test_cerrar_sesion_de_la_barra_conserva_el_kiosco(self) -> None:
        self.escanear('A1B2C3D4')
        self.estado()

        self.client.post(reverse('logout'))

        self.assertIsNone(self.usuario_en_sesion())
        self.assertEqual(self.client.session['terminal'], 'caja-1')
        self.terminal.refresh_from_db()
        self.assertIsNone(self.terminal.tarjeta_activa)
        self.assertFalse(self.estado()['recargar'])
        self.assertIsNone(self.usuario_en_sesion())

    def test_navegador_sin_terminal_no_inicia_sesion(self) -> None:
        self.escanear('A1B2C3D4')
        otro_navegador = Client()

        respuesta = otro_navegador.get(reverse('iot_estado'))

        self.assertEqual(respuesta.status_code, 404)
        self.assertNotIn('_auth_user_id', otro_navegador.session)


class KioscoTests(TestCase):
    """Vinculación de una computadora con /kiosco/<codigo>/."""

    def setUp(self) -> None:
        self.terminal = Terminal.objects.create(codigo='caja-1', version=7)

    def test_sin_staff_403(self) -> None:
        self.client.force_login(User.objects.create_user('cliente', password='x'))
        self.assertEqual(self.client.get(reverse('kiosco', args=['caja-1'])).status_code, 403)
        self.assertNotIn('terminal', self.client.session)

    def test_anonimo_va_al_login(self) -> None:
        respuesta = self.client.get(reverse('kiosco', args=['caja-1']))
        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse('login'), respuesta['Location'])

    def test_staff_vincula_y_su_sesion_se_cierra(self) -> None:
        self.client.force_login(User.objects.create_user('staff', password='x', is_staff=True))

        respuesta = self.client.get(reverse('kiosco', args=['caja-1']))

        self.assertRedirects(respuesta, reverse('inicio'))
        self.assertEqual(self.client.session['terminal'], 'caja-1')
        self.assertEqual(self.client.session['iot_version'], 7)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_terminal_inexistente_404(self) -> None:
        self.client.force_login(User.objects.create_user('staff', password='x', is_staff=True))
        self.assertEqual(self.client.get(reverse('kiosco', args=['caja-9'])).status_code, 404)


class HealthzTests(TestCase):
    """/healthz responde 200 aunque esté activa la redirección a HTTPS."""

    @override_settings(SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=[r'^healthz$'])
    def test_responde_ok_sin_redirigir(self) -> None:
        respuesta = self.client.get('/healthz')
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.content, b'ok')
        self.assertEqual(self.client.get('/').status_code, 301)


class SimularScanTests(EscenarioKioscoMixin, TestCase):
    """`simular_scan` hace lo mismo que el ESP32."""

    def test_activa_la_tarjeta(self) -> None:
        call_command('simular_scan', 'a1b2c3d4', '--terminal', 'caja-1', stdout=StringIO())
        self.terminal.refresh_from_db()
        self.assertEqual(self.terminal.tarjeta_activa.usuario, self.ana)

    def test_terminal_inexistente(self) -> None:
        with self.assertRaises(CommandError):
            call_command('simular_scan', 'A1B2C3D4', '--terminal', 'caja-9', stdout=StringIO())
