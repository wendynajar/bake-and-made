"""Pruebas del registro de usuarios, del perfil VIP y de los usuarios demo."""

import datetime
import os
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from iot.models import TarjetaRFID
from tienda.models import PLAN_SWEET, Suscripcion

from .models import CumpleYaRegistrado, FechaCumpleInvalida, PerfilVIP


class RegistroTests(TestCase):
    """Alta de clientes y unicidad del correo."""

    datos = {
        'username': 'eli',
        'first_name': 'Eli',
        'last_name': 'Pérez',
        'email': 'Eli@Ejemplo.com',
        'password1': 'pastel-de-fresa-2026',
        'password2': 'pastel-de-fresa-2026',
    }

    def test_registro_crea_usuario_e_inicia_sesion(self) -> None:
        respuesta = self.client.post(reverse('registro'), self.datos)
        self.assertRedirects(respuesta, reverse('inicio'))
        usuario = User.objects.get(username='eli')
        self.assertEqual(usuario.email, 'eli@ejemplo.com')
        self.assertEqual(int(self.client.session['_auth_user_id']), usuario.pk)

    def test_correo_duplicado_es_rechazado(self) -> None:
        User.objects.create_user('otro', email='eli@ejemplo.com', password='x-clave-segura-1')
        respuesta = self.client.post(reverse('registro'), self.datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(User.objects.filter(username='eli').exists())


class PerfilVIPTests(TestCase):
    """El perfil VIP se crea de forma perezosa y es uno por usuario."""

    def test_de_crea_el_perfil_una_sola_vez(self) -> None:
        usuario = User.objects.create_user('ana', password='x-clave-segura-1')
        primero = PerfilVIP.de(usuario)
        segundo = PerfilVIP.de(usuario)
        self.assertEqual(primero.pk, segundo.pk)
        self.assertEqual(PerfilVIP.objects.count(), 1)
        self.assertEqual(usuario.perfil_vip, primero)


@mock.patch.dict(os.environ, {'DEMO_PASSWORD': 'demo-clave-segura-2026', 'DEMO_VIP_UIDS': ''})
class UsuariosDemoTests(TestCase):
    """`crear_usuarios_demo` crea los 3 usuarios Sweet de la demo sin duplicar nada."""

    UIDS = 'a1:b2:c3:d4,B2C3D4E5,C3D4E5F6'

    def ejecutar(self, uids: str | None = None) -> None:
        argumentos = ['--uids', uids] if uids is not None else []
        call_command('crear_usuarios_demo', *argumentos, stdout=StringIO())

    def test_crea_los_3_usuarios_con_la_tabla_usuarios(self) -> None:
        self.ejecutar(self.UIDS)

        ana = User.objects.get(username='ana.demo@bakeandmade.test')
        self.assertEqual(User.objects.count(), 3)
        self.assertEqual((ana.first_name, ana.last_name), ('Ana', 'López'))
        self.assertEqual(ana.email, 'ana.demo@bakeandmade.test')
        self.assertEqual(timezone.localtime(ana.date_joined).date(), datetime.date(2026, 9, 1))
        self.assertEqual(ana.perfil_vip.telefono, '5510000001')

        esperado = {
            'ana.demo@bakeandmade.test': 'A1B2C3D4',
            'bruno.demo@bakeandmade.test': 'B2C3D4E5',
            'carla.demo@bakeandmade.test': 'C3D4E5F6',
        }
        for usuario in User.objects.all():
            self.assertEqual(Suscripcion.objects.plan_de(usuario), PLAN_SWEET)
            self.assertEqual(usuario.tarjeta.uid, esperado[usuario.username])

    def test_correrlo_dos_veces_no_duplica(self) -> None:
        self.ejecutar(self.UIDS)
        self.ejecutar(self.UIDS)

        self.assertEqual(User.objects.count(), 3)
        self.assertEqual(TarjetaRFID.objects.count(), 3)
        for usuario in User.objects.all():
            self.assertEqual(Suscripcion.objects.filter(usuario=usuario).count(), 1)

    def test_la_contrasena_se_guarda_con_hash(self) -> None:
        self.ejecutar(self.UIDS)

        ana = User.objects.get(username='ana.demo@bakeandmade.test')
        self.assertTrue(ana.check_password('demo-clave-segura-2026'))
        self.assertNotIn('demo-clave-segura-2026', ana.password)

    def test_sin_demo_password_falla_sin_crear_nada(self) -> None:
        with mock.patch.dict(os.environ, {'DEMO_PASSWORD': ''}):
            with self.assertRaises(CommandError):
                self.ejecutar(self.UIDS)
        self.assertFalse(User.objects.exists())
        self.assertFalse(TarjetaRFID.objects.exists())

    def test_lee_los_uid_de_la_variable_de_entorno(self) -> None:
        with mock.patch.dict(os.environ, {'DEMO_VIP_UIDS': self.UIDS}):
            self.ejecutar()
        self.assertEqual(TarjetaRFID.objects.filter(usuario__isnull=False).count(), 3)

    def test_rechaza_si_no_son_3_uid(self) -> None:
        with self.assertRaises(CommandError):
            self.ejecutar('A1B2C3D4,B2C3D4E5')
        self.assertFalse(User.objects.exists())

    def test_rechaza_uid_de_otro_usuario_sin_crear_nada(self) -> None:
        otro = User.objects.create_user('otro', password='x-clave-segura-1')
        TarjetaRFID.objects.create(uid='C3D4E5F6', usuario=otro)

        with self.assertRaises(CommandError):
            self.ejecutar(self.UIDS)
        self.assertEqual(User.objects.count(), 1)

    def test_no_toma_tarjetas_libres_de_otro_orden(self) -> None:
        inventario = TarjetaRFID.objects.create(uid='FFFFFFFF')

        self.ejecutar(self.UIDS)

        inventario.refresh_from_db()
        self.assertIsNone(inventario.usuario)


class CumpleaniosTests(TestCase):
    """El cumpleaños se registra una sola vez y no puede ser futuro."""

    HOY = datetime.date(2026, 11, 18)

    def setUp(self) -> None:
        self.usuario = User.objects.create_user('hugo', password='x-clave-segura-1')

    def test_primer_registro_se_guarda_con_la_fecha_de_registro(self) -> None:
        PerfilVIP.de(self.usuario).registrar_cumpleanios(datetime.date(1995, 3, 14), self.HOY)

        perfil = PerfilVIP.objects.get(usuario=self.usuario)
        self.assertEqual(perfil.fecha_nacimiento, datetime.date(1995, 3, 14))
        self.assertEqual(perfil.cumple_registrado_en, self.HOY)

    def test_funciona_aunque_el_perfil_no_exista_todavia(self) -> None:
        PerfilVIP(usuario=self.usuario).registrar_cumpleanios(datetime.date(1995, 3, 14), self.HOY)
        self.assertEqual(PerfilVIP.objects.get().fecha_nacimiento, datetime.date(1995, 3, 14))

    def test_segundo_intento_no_cambia_nada(self) -> None:
        perfil = PerfilVIP.de(self.usuario)
        perfil.registrar_cumpleanios(datetime.date(1995, 3, 14), self.HOY)

        with self.assertRaises(CumpleYaRegistrado):
            perfil.registrar_cumpleanios(datetime.date(1990, 1, 1), self.HOY)
        perfil.refresh_from_db()
        self.assertEqual(perfil.fecha_nacimiento, datetime.date(1995, 3, 14))

    def test_una_copia_vieja_del_perfil_tampoco_lo_cambia(self) -> None:
        copia_vieja = PerfilVIP.de(self.usuario)
        PerfilVIP.de(self.usuario).registrar_cumpleanios(datetime.date(1995, 3, 14), self.HOY)

        with self.assertRaises(CumpleYaRegistrado):
            copia_vieja.registrar_cumpleanios(datetime.date(1990, 1, 1), self.HOY)
        self.assertEqual(PerfilVIP.objects.get().fecha_nacimiento, datetime.date(1995, 3, 14))

    def test_fecha_futura_o_imposible_es_invalida(self) -> None:
        perfil = PerfilVIP.de(self.usuario)
        for fecha in (self.HOY + datetime.timedelta(days=1), datetime.date(1899, 12, 31)):
            with self.subTest(fecha=fecha), self.assertRaises(FechaCumpleInvalida):
                perfil.registrar_cumpleanios(fecha, self.HOY)
        perfil.refresh_from_db()
        self.assertIsNone(perfil.fecha_nacimiento)
