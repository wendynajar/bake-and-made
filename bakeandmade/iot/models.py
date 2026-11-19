"""Modelos de la capa IoT: tarjetas RFID, terminales del kiosco y bitácora de lecturas.

La tarjeta y el perfil VIP (`usuarios.PerfilVIP`) van separados: la tarjeta existe
antes de tener dueño (inventario) y el perfil existe aunque la tarjeta no haya
llegado. Los UID nunca se escriben en el código; se dan de alta en el admin o con
`registrar_tarjeta` (ver docs/IOT_VIP_SPEC.md).
"""

from __future__ import annotations

import re
from typing import Any

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.utils import timezone

_SEPARADORES_UID = re.compile(r'[\s:\-]')


def normalizar_uid(uid: str) -> str:
    """Deja el UID en mayúsculas y sin espacios, `:` ni `-`.

    El lector, el admin y el comando pueden escribir el mismo UID de formas
    distintas ("a1:b2:c3:d4", "A1 B2 C3 D4"); normalizarlo evita duplicados y
    búsquedas fallidas.
    """
    return _SEPARADORES_UID.sub('', uid or '').upper()


validar_uid = RegexValidator(
    regex=r'^[0-9A-F]{8,20}$',
    message='El UID debe tener de 4 a 10 bytes en hexadecimal (8 a 20 caracteres).',
)
"""Las tarjetas MIFARE tienen UID de 4, 7 o 10 bytes."""


class TarjetaQuerySet(models.QuerySet['TarjetaRFID']):
    """Consultas sobre el inventario de tarjetas."""

    def libres(self) -> TarjetaQuerySet:
        """Tarjetas activas sin dueño, en orden de alta: las disponibles para entregar."""
        return self.filter(activa=True, usuario__isnull=True).order_by('pk')

    def entregar_a(self, usuario: AbstractBaseUser) -> TarjetaRFID | None:
        """Entrega simulada: asigna al usuario la primera tarjeta libre del inventario.

        Si el usuario ya tiene tarjeta (aunque esté inactiva), se devuelve esa y no
        se asigna otra: las renovaciones del Sweet Plan no entregan tarjetas nuevas.
        Devuelve None si no quedan tarjetas libres ("tu tarjeta está en camino").
        `select_for_update(skip_locked=True)` evita que dos compras simultáneas
        reciban la misma tarjeta en PostgreSQL.
        """
        existente = self.filter(usuario=usuario).first()
        if existente is not None:
            return existente

        with transaction.atomic():
            tarjeta = self.libres().select_for_update(skip_locked=True).first()
            if tarjeta is None:
                return None
            tarjeta.usuario = usuario
            tarjeta.entregada_en = timezone.now()
            tarjeta.save(update_fields=['usuario', 'entregada_en'])
            return tarjeta


class TarjetaRFID(models.Model):
    """Tarjeta física del kiosco. Sin dueño significa que está en inventario.

    No da descuentos por sí misma: solo sirve para iniciar sesión en el kiosco
    mientras su dueño tenga el Sweet Plan vigente.
    """

    uid = models.CharField(max_length=20, unique=True, validators=[validar_uid])
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='tarjeta',
    )
    entregada_en = models.DateTimeField(null=True, blank=True)
    activa = models.BooleanField(default=True, help_text='Desmarcar si la tarjeta se pierde.')

    objects = TarjetaQuerySet.as_manager()

    class Meta:
        verbose_name = 'Tarjeta RFID'
        verbose_name_plural = 'Tarjetas RFID'

    def __str__(self) -> str:
        return f'Tarjeta …{self.uid[-4:]}'

    def clean_fields(self, exclude: Any = None) -> None:
        """Normaliza el UID antes de validarlo, para que el admin acepte "a1:b2:c3:d4"."""
        self.uid = normalizar_uid(self.uid)
        super().clean_fields(exclude=exclude)

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Guarda siempre el UID normalizado, aunque no se haya llamado a full_clean()."""
        self.uid = normalizar_uid(self.uid)
        super().save(*args, **kwargs)


class Terminal(models.Model):
    """Una computadora de la tienda con su lector RFID (por ejemplo "caja-1").

    Es la fuente de verdad de qué tarjeta está activa en el kiosco. La página del
    kiosco consulta `version` por polling y se recarga cuando cambia. Las
    operaciones (activar, rechazar, salir, expirar) se agregan en la fase 4.
    """

    codigo = models.SlugField(unique=True)
    tarjeta_activa = models.ForeignKey(
        TarjetaRFID, null=True, blank=True, on_delete=models.SET_NULL
    )
    ultima_actividad = models.DateTimeField(null=True, blank=True)
    ultimo_rechazo = models.CharField(max_length=20, blank=True)
    version = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = 'Terminales'

    def __str__(self) -> str:
        return self.codigo


class LecturaRFID(models.Model):
    """Bitácora de cada lectura del lector, para depurar el hardware y auditar accesos."""

    OK = 'ok'
    DESCONOCIDA = 'desconocida'
    SIN_SWEET = 'sin_sweet'
    RESULTADOS = [
        (OK, 'Aceptada'),
        (DESCONOCIDA, 'Desconocida'),
        (SIN_SWEET, 'Sin Sweet Plan vigente'),
    ]

    terminal = models.ForeignKey(Terminal, on_delete=models.CASCADE)
    uid = models.CharField(max_length=20)
    resultado = models.CharField(max_length=20, choices=RESULTADOS)
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Lectura RFID'
        verbose_name_plural = 'Lecturas RFID'
        ordering = ['-creada']

    def __str__(self) -> str:
        return f'{self.uid} en {self.terminal} → {self.resultado}'
