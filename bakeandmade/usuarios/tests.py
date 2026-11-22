"""Pruebas del registro de usuarios, del perfil VIP y de los usuarios demo."""

import datetime
import json
import os
from io import StringIO
from typing import Any
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from iot.models import TarjetaRFID
from tienda.models import PLAN_SWEET, ExperienciaQR, RecordatorioEvento, Suscripcion

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


class DiasParaCumpleaniosTests(TestCase):
    """Contador de días al próximo cumpleaños que se muestra en /vip/."""

    def setUp(self) -> None:
        self.usuario = User.objects.create_user('ivan', password='x-clave-segura-1')

    def perfil(self, nacimiento: datetime.date | None) -> PerfilVIP:
        return PerfilVIP(usuario=self.usuario, fecha_nacimiento=nacimiento)

    def test_sin_cumpleanios_registrado(self) -> None:
        self.assertIsNone(self.perfil(None).dias_para_cumpleanios(datetime.date(2026, 11, 18)))

    def test_hoy_manana_y_dentro_del_mismo_anio(self) -> None:
        perfil = self.perfil(datetime.date(1995, 3, 14))
        casos = {
            datetime.date(2026, 3, 14): 0,
            datetime.date(2026, 3, 13): 1,
            datetime.date(2026, 3, 4): 10,
        }
        for hoy, dias in casos.items():
            with self.subTest(hoy=hoy):
                self.assertEqual(perfil.dias_para_cumpleanios(hoy), dias)

    def test_si_ya_paso_cuenta_hasta_el_del_anio_siguiente(self) -> None:
        perfil = self.perfil(datetime.date(1995, 3, 14))
        self.assertEqual(perfil.dias_para_cumpleanios(datetime.date(2026, 3, 15)), 364)

    def test_29_de_febrero_se_celebra_el_28_en_anio_no_bisiesto(self) -> None:
        perfil = self.perfil(datetime.date(2000, 2, 29))
        self.assertEqual(perfil.dias_para_cumpleanios(datetime.date(2027, 2, 27)), 1)
        self.assertEqual(perfil.dias_para_cumpleanios(datetime.date(2028, 2, 27)), 2)


# =============================================================================
# Fase 8: página /vip/, calendario, cumpleaños y video del QR
# =============================================================================

class VIPMixin:
    """Ana y Bruno con Sweet vigente; Carla Basic."""

    def setUp(self) -> None:
        self.ana = User.objects.create_user('ana', password='x-clave-segura-1', first_name='Ana')
        self.bruno = User.objects.create_user('bruno', password='x-clave-segura-1')
        self.carla = User.objects.create_user('carla', password='x-clave-segura-1')
        Suscripcion.contratar_mes(self.ana)
        Suscripcion.contratar_mes(self.bruno)

    def crear_fecha(self, **datos: Any) -> Any:
        cuerpo = {'nombre_evento': 'Aniversario', 'fecha_evento': '2026-12-05', 'tipo': 'otro'}
        cuerpo.update(datos)
        return self.client.post(
            reverse('vip_fechas'), data=json.dumps(cuerpo), content_type='application/json'
        )

    def listar(self, start: str = '2026-11-30', end: str = '2027-01-11') -> list[dict[str, Any]]:
        respuesta = self.client.get(reverse('vip_fechas'), {'start': start, 'end': end})
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.json()


class FechasVIPTests(VIPMixin, TestCase):
    """Cada usuario Sweet agrega, ve y borra solo sus propias fechas."""

    def test_crear_y_listar(self) -> None:
        self.client.force_login(self.ana)

        respuesta = self.crear_fecha()

        self.assertEqual(respuesta.status_code, 201)
        self.assertEqual(respuesta.json()['title'], 'Aniversario')
        self.assertEqual([e['start'] for e in self.listar()], ['2026-12-05'])

    def test_b_no_ve_ni_borra_las_fechas_de_a(self) -> None:
        self.client.force_login(self.ana)
        evento_id = self.crear_fecha().json()['id']

        self.client.force_login(self.bruno)
        self.assertEqual(self.listar(), [])
        borrar = self.client.delete(reverse('vip_fecha', args=[evento_id]))

        self.assertEqual(borrar.status_code, 404)
        self.assertTrue(RecordatorioEvento.objects.filter(pk=evento_id).exists())

    def test_el_duenio_la_borra(self) -> None:
        self.client.force_login(self.ana)
        evento_id = self.crear_fecha().json()['id']

        respuesta = self.client.delete(reverse('vip_fecha', args=[evento_id]))

        self.assertEqual(respuesta.status_code, 204)
        self.assertFalse(RecordatorioEvento.objects.exists())

    def test_basic_y_anonimo_reciben_403(self) -> None:
        self.assertEqual(self.client.get(reverse('vip_fechas')).status_code, 403)
        self.client.force_login(self.carla)
        self.assertEqual(self.client.get(reverse('vip_fechas')).status_code, 403)
        self.assertEqual(self.crear_fecha().status_code, 403)
        self.assertFalse(RecordatorioEvento.objects.exists())

    def test_datos_invalidos_400(self) -> None:
        self.client.force_login(self.ana)
        for datos in ({'nombre_evento': ''}, {'fecha_evento': '2026-13-40'}, {'tipo': 'boda'},
                      {'nombre_evento': 'x' * 101}):
            with self.subTest(datos=datos):
                respuesta = self.crear_fecha(**datos)
                self.assertEqual(respuesta.status_code, 400)
                self.assertIn('errores', respuesta.json())
        self.assertFalse(RecordatorioEvento.objects.exists())

    def test_aniversario_se_repite_cada_anio(self) -> None:
        self.client.force_login(self.ana)
        self.crear_fecha(tipo='aniversario', fecha_evento='2020-01-03')

        fechas = [e['start'] for e in self.listar('2027-01-01', '2028-01-05')]

        self.assertEqual(fechas, ['2027-01-03', '2028-01-03'])

    def test_mi_cumpleanios_aparece_fijo_y_no_borrable(self) -> None:
        PerfilVIP.objects.create(usuario=self.ana, fecha_nacimiento=datetime.date(1995, 12, 14))
        self.client.force_login(self.ana)

        cumple = [e for e in self.listar() if e['extendedProps']['tipo'] == 'mi_cumpleanios']

        self.assertEqual(len(cumple), 1)
        self.assertEqual(cumple[0]['start'], '2026-12-14')
        self.assertFalse(cumple[0]['extendedProps']['borrable'])

    def test_rango_invalido_400(self) -> None:
        self.client.force_login(self.ana)
        respuesta = self.client.get(reverse('vip_fechas'), {'start': '2026-01-01', 'end': '2030-01-01'})
        self.assertEqual(respuesta.status_code, 400)


class CumpleaniosAPITests(VIPMixin, TestCase):
    """POST /api/vip/cumpleanios/: 201 la primera vez, 409 después, 400 si es inválida."""

    def registrar(self, fecha: Any) -> Any:
        return self.client.post(
            reverse('vip_cumpleanios'), data=json.dumps({'fecha': fecha}),
            content_type='application/json',
        )

    def test_primer_registro_luego_409(self) -> None:
        self.client.force_login(self.ana)

        self.assertEqual(self.registrar('1995-03-14').status_code, 201)
        segundo = self.registrar('1990-01-01')

        self.assertEqual(segundo.status_code, 409)
        self.assertEqual(PerfilVIP.objects.get(usuario=self.ana).fecha_nacimiento,
                         datetime.date(1995, 3, 14))

    def test_fecha_futura_o_invalida_400(self) -> None:
        self.client.force_login(self.ana)
        futura = (timezone.localdate() + datetime.timedelta(days=1)).isoformat()
        for fecha in (futura, 'ayer', None, 123):
            with self.subTest(fecha=fecha):
                self.assertEqual(self.registrar(fecha).status_code, 400)
        self.assertFalse(PerfilVIP.objects.filter(fecha_nacimiento__isnull=False).exists())

    def test_basic_403(self) -> None:
        self.client.force_login(self.carla)
        self.assertEqual(self.registrar('1995-03-14').status_code, 403)


URL_FIRMADA = 'https://bucket.s3.amazonaws.com/media/videos/ana.mp4?X-Amz-Signature=abc'


@mock.patch('django.db.models.fields.files.FieldFile.url', new_callable=mock.PropertyMock,
            return_value=URL_FIRMADA)
class VideoQRTests(VIPMixin, TestCase):
    """/vip/v/<codigo_unico>/ redirige a la URL firmada de S3 si el video sigue vigente."""

    def crear_experiencia(self, horas: int) -> ExperienciaQR:
        return ExperienciaQR.objects.create(
            usuario=self.ana, video='videos/ana.mp4', mensaje_texto='¡Gracias, Ana!',
            fecha_expiracion=timezone.now() + datetime.timedelta(hours=horas),
        )

    def test_vigente_redirige_a_s3_sin_sesion(self, _url: Any) -> None:
        experiencia = self.crear_experiencia(horas=24)

        respuesta = self.client.get(reverse('video_qr', args=[experiencia.codigo_unico]))

        self.assertRedirects(respuesta, URL_FIRMADA, fetch_redirect_response=False)

    def test_expirado_o_inexistente_404(self, _url: Any) -> None:
        experiencia = self.crear_experiencia(horas=-1)
        self.assertEqual(
            self.client.get(reverse('video_qr', args=[experiencia.codigo_unico])).status_code, 404
        )
        self.assertEqual(self.client.get(reverse('video_qr', args=['no-existe'])).status_code, 404)

    def test_la_pagina_vip_muestra_el_qr(self, _url: Any) -> None:
        experiencia = self.crear_experiencia(horas=24)
        self.client.force_login(self.ana)

        respuesta = self.client.get(reverse('vip'))

        self.assertContains(respuesta, '<svg')
        self.assertContains(respuesta, f'/vip/v/{experiencia.codigo_unico}/')
        self.assertContains(respuesta, '¡Gracias, Ana!')

    def test_el_qr_no_muestra_la_url_como_texto(self, _url: Any) -> None:
        experiencia = self.crear_experiencia(horas=24)
        self.client.force_login(self.ana)

        respuesta = self.client.get(reverse('vip'))

        # La URL solo va en el enlace del QR (href), no escrita en la página.
        self.assertNotContains(respuesta, f'/vip/v/{experiencia.codigo_unico}/</a>')
        self.assertContains(respuesta, 'Escanéalo con tu celular para ver tu video.')


class PaginaVIPTests(VIPMixin, TestCase):
    """Acceso y contenido de /vip/."""

    def test_anonimo_va_al_login_y_basic_a_planes(self) -> None:
        respuesta = self.client.get(reverse('vip'))
        self.assertIn(reverse('login'), respuesta['Location'])

        self.client.force_login(self.carla)
        self.assertRedirects(self.client.get(reverse('vip')), reverse('suscripcion'))

    def test_sweet_ve_su_membresia(self) -> None:
        TarjetaRFID.objects.create(uid='A1B2C3D4', usuario=self.ana)
        self.client.force_login(self.ana)

        respuesta = self.client.get(reverse('vip'))

        self.assertContains(respuesta, 'VIP — <em>Ana</em>', html=False)
        self.assertContains(respuesta, 'termina en …D4')
        self.assertContains(respuesta, '20 %')
        self.assertContains(respuesta, 'Tu video estará listo pronto.')
        self.assertContains(respuesta, 'id="form-cumple"')

    def test_sin_tarjeta_esta_en_camino(self) -> None:
        self.client.force_login(self.bruno)
        self.assertContains(self.client.get(reverse('vip')), 'En camino')

    def test_cumpleanios_registrado_ya_no_es_editable(self) -> None:
        PerfilVIP.objects.create(usuario=self.ana, fecha_nacimiento=datetime.date(1995, 3, 14),
                                 cumple_registrado_en=datetime.date(2026, 1, 1))
        self.client.force_login(self.ana)

        respuesta = self.client.get(reverse('vip'))

        self.assertNotContains(respuesta, 'id="form-cumple"')
        self.assertContains(respuesta, 'Para corregirla, pídelo en tienda.')

    @mock.patch('usuarios.views_vip.timezone.localdate', return_value=datetime.date(2026, 3, 4))
    def test_cumpleanios_muestra_dia_mes_y_dias_que_faltan(self, _hoy: Any) -> None:
        PerfilVIP.objects.create(usuario=self.ana, fecha_nacimiento=datetime.date(1995, 3, 14),
                                 cumple_registrado_en=datetime.date(2026, 1, 1))
        self.client.force_login(self.ana)

        respuesta = self.client.get(reverse('vip'))

        self.assertContains(respuesta, '<span class="vip-cumple-dia">14</span>', html=True)
        self.assertContains(respuesta, '<span class="vip-cumple-mes">Marzo</span>', html=True)
        self.assertContains(respuesta, 'Faltan <strong>10</strong> días')

    @mock.patch('usuarios.views_vip.timezone.localdate', return_value=datetime.date(2026, 3, 14))
    def test_el_dia_del_cumpleanios_lo_dice_en_vez_del_contador(self, _hoy: Any) -> None:
        PerfilVIP.objects.create(usuario=self.ana, fecha_nacimiento=datetime.date(1995, 3, 14),
                                 cumple_registrado_en=datetime.date(2026, 1, 1))
        self.client.force_login(self.ana)

        self.assertContains(self.client.get(reverse('vip')), '¡Es hoy!')

    def test_la_pestana_vip_apunta_a_la_pagina(self) -> None:
        self.client.force_login(self.ana)
        self.assertContains(self.client.get(reverse('inicio')), f'href="{reverse("vip")}" class="nav-vip"')
