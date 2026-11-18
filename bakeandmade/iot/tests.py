"""Pruebas de los modelos y comandos de la app iot (fase 1 de docs/IOT_VIP_SPEC.md)."""

from io import StringIO

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import TestCase

from .models import TarjetaRFID, Terminal, normalizar_uid


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
