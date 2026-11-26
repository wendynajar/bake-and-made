"""Comando `registrar_tarjeta <uid>`: da de alta una tarjeta física en el inventario.

La tarjeta queda libre (sin dueño) hasta la entrega simulada al contratar el
Sweet Plan. Los UID se pasan como argumento para no escribirlos nunca en el código.
"""

from argparse import ArgumentParser
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from iot.models import TarjetaRFID, normalizar_uid


class Command(BaseCommand):
    """Registra una tarjeta libre; si ya existe, informa su estado sin modificarla."""

    help = 'Registra una tarjeta RFID libre en el inventario. Se puede repetir sin duplicar.'

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Recibe el UID tal como lo imprime el monitor serie del ESP32."""
        parser.add_argument('uid', help='UID de la tarjeta, por ejemplo A1B2C3D4 o "a1:b2:c3:d4".')

    def handle(self, *args: Any, **opciones: Any) -> None:
        """Normaliza y valida el UID, y crea la tarjeta si no existe."""
        uid = normalizar_uid(opciones['uid'])

        existente = TarjetaRFID.objects.filter(uid=uid).select_related('usuario').first()
        if existente is not None:
            dueno = existente.usuario or 'sin dueño'
            estado = 'activa' if existente.activa else 'inactiva'
            self.stdout.write(f'La tarjeta {uid} ya estaba registrada ({estado}, {dueno}).')
            return

        tarjeta = TarjetaRFID(uid=uid)
        try:
            tarjeta.full_clean()
        except ValidationError as error:
            raise CommandError('; '.join(error.messages)) from error
        tarjeta.save()
        self.stdout.write(self.style.SUCCESS(f'Tarjeta {uid} registrada como libre.'))
