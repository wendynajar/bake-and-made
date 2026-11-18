"""Modelos de la app usuarios.

El proyecto usa el `User` nativo de Django (nombre, email, contraseña con hash
y fecha de registro). `PerfilVIP` guarda lo que `User` no tiene: el teléfono y
el cumpleaños con el que se calcula el descuento VIP (ver docs/IOT_VIP_SPEC.md).
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models


class PerfilVIP(models.Model):
    """Datos extra del usuario que necesita la membresía VIP.

    Existe aunque el usuario todavía no tenga tarjeta: la tarjeta (`iot.TarjetaRFID`)
    es inventario físico y el perfil es dato de la persona. La lógica de descuento
    y cumpleaños se agrega en la fase 3 de la especificación.
    """

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='perfil_vip',
    )
    telefono = models.CharField(max_length=20, blank=True)
    fecha_nacimiento = models.DateField(
        null=True,
        blank=True,
        help_text='El usuario la registra una sola vez; después solo se corrige aquí.',
    )
    cumple_registrado_en = models.DateField(
        null=True,
        blank=True,
        help_text='Día en que se registró el cumpleaños (ese día no aplica el 50 %).',
    )

    class Meta:
        verbose_name = 'Perfil VIP'
        verbose_name_plural = 'Perfiles VIP'

    def __str__(self) -> str:
        return f'Perfil VIP de {self.usuario}'

    @classmethod
    def de(cls, usuario: AbstractBaseUser) -> PerfilVIP:
        """Devuelve el perfil del usuario y lo crea vacío si aún no existe.

        Se crea de forma perezosa para no depender de una señal en el registro:
        cualquier usuario, incluso los creados antes de esta tabla, tiene perfil.
        """
        perfil, _ = cls.objects.get_or_create(usuario=usuario)
        return perfil
