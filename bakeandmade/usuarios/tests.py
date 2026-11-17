"""Pruebas del registro de usuarios."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


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
