"""Modelos de la app usuarios.

El proyecto usa el `User` nativo de Django (nombre, email, contraseña con hash
y fecha de registro). `PerfilVIP` guarda lo que `User` no tiene: el teléfono y
el cumpleaños con el que se calcula el descuento VIP (ver docs/IOT_VIP_SPEC.md).
"""

from __future__ import annotations

import calendar
import datetime
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models
from django.utils import timezone

SIN_DESCUENTO = (Decimal('0'), '')
"""Resultado de `descuento_vigente()` cuando no aplica ningún descuento."""

FECHA_NACIMIENTO_MINIMA = datetime.date(1900, 1, 1)


class CumpleYaRegistrado(Exception):
    """El usuario ya registró su cumpleaños; solo el admin puede cambiarlo."""


class FechaCumpleInvalida(ValueError):
    """La fecha de cumpleaños es futura o imposible."""


class PerfilVIP(models.Model):
    """Datos extra del usuario y su lógica de descuento (fat model).

    Existe aunque el usuario todavía no tenga tarjeta: la tarjeta (`iot.TarjetaRFID`)
    es inventario físico y el perfil es dato de la persona. Este modelo es el único
    que decide qué descuento le toca a un usuario; `tienda.models.descuento_para`
    solo lo expone a vistas y checkout.
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

    # --- Membresía -----------------------------------------------------------

    def es_sweet_vigente(self) -> bool:
        """True si el usuario tiene el Sweet Plan pagado para hoy.

        VIP y Sweet Plan son lo mismo: no importa si inició sesión con contraseña
        o con la tarjeta. Una suscripción cancelada vale hasta su `fecha_fin`.
        """
        # Import local: tienda.models importa este módulo (evita el ciclo).
        from tienda.models import PLAN_SWEET, Suscripcion

        return Suscripcion.objects.plan_de(self.usuario) == PLAN_SWEET

    # --- Cumpleaños ----------------------------------------------------------

    def registrar_cumpleanios(self, fecha: datetime.date, hoy: datetime.date) -> None:
        """Guarda el cumpleaños una sola vez.

        Lanza `CumpleYaRegistrado` si ya existe (solo el admin lo corrige) y
        `FechaCumpleInvalida` si la fecha es futura o anterior a 1900. El UPDATE
        condicionado evita que dos peticiones simultáneas lo registren dos veces.
        """
        if fecha > hoy or fecha < FECHA_NACIMIENTO_MINIMA:
            raise FechaCumpleInvalida('La fecha de cumpleaños no es válida.')
        if self.fecha_nacimiento is not None:
            raise CumpleYaRegistrado('El cumpleaños ya está registrado.')

        if self.pk is None:
            self.save()
        actualizados = PerfilVIP.objects.filter(
            pk=self.pk, fecha_nacimiento__isnull=True
        ).update(fecha_nacimiento=fecha, cumple_registrado_en=hoy)
        if actualizados == 0:
            self.refresh_from_db(fields=['fecha_nacimiento', 'cumple_registrado_en'])
            raise CumpleYaRegistrado('El cumpleaños ya está registrado.')
        self.fecha_nacimiento = fecha
        self.cumple_registrado_en = hoy

    def es_cumpleanios(self, hoy: datetime.date) -> bool:
        """True si hoy es su cumpleaños y no lo registró hoy mismo.

        La excepción del mismo día evita que alguien registre "hoy" solo para
        obtener el 50 %. Quien nació el 29 de febrero lo celebra el 28 en años
        no bisiestos.
        """
        nacimiento = self.fecha_nacimiento
        if nacimiento is None or self.cumple_registrado_en == hoy:
            return False
        if (nacimiento.month, nacimiento.day) == (2, 29) and not calendar.isleap(hoy.year):
            return (hoy.month, hoy.day) == (2, 28)
        return (nacimiento.month, nacimiento.day) == (hoy.month, hoy.day)

    def _cumpleanios_en(self, anio: int) -> datetime.date:
        """Día en que celebra en `anio` (el 29 de febrero pasa al 28 si el año no es bisiesto)."""
        nacimiento = self.fecha_nacimiento
        if (nacimiento.month, nacimiento.day) == (2, 29) and not calendar.isleap(anio):
            return datetime.date(anio, 2, 28)
        return nacimiento.replace(year=anio)

    def dias_para_cumpleanios(self, hoy: datetime.date) -> int | None:
        """Días que faltan para su próximo cumpleaños: 0 si es hoy, None si no lo registró.

        Solo sirve para mostrarlo en /vip/; el descuento lo decide
        `es_cumpleanios()`, que además excluye el día en que se registró.
        Usa la misma regla del 29 de febrero, para que el contador llegue a 0
        justo el día del descuento.
        """
        if self.fecha_nacimiento is None:
            return None
        proximo = self._cumpleanios_en(hoy.year)
        if proximo < hoy:
            proximo = self._cumpleanios_en(hoy.year + 1)
        return (proximo - hoy).days

    # --- Descuento -----------------------------------------------------------

    def descuento_vigente(
        self, hoy: datetime.date | None = None, sweet_vigente: bool | None = None
    ) -> tuple[Decimal, str]:
        """Devuelve (fracción, motivo) del descuento que le toca hoy.

        Sweet vigente: 20 % ("vip"), o 50 % ("cumpleanios") el día de su
        cumpleaños, que reemplaza al 20 %. Sin Sweet vigente: (0, "").
        Los motivos coinciden con `tienda.models.Pedido.MOTIVOS_DESCUENTO`.
        `sweet_vigente` permite reutilizar el plan ya calculado en la petición.
        """
        from tienda.models import Pedido

        hoy = hoy or timezone.localdate()
        if sweet_vigente is None:
            sweet_vigente = self.es_sweet_vigente()
        if not sweet_vigente:
            return SIN_DESCUENTO
        if self.es_cumpleanios(hoy):
            return Decimal(settings.VIP_DESCUENTO_CUMPLE), Pedido.MOTIVO_CUMPLEANIOS
        return Decimal(settings.VIP_DESCUENTO), Pedido.MOTIVO_VIP
