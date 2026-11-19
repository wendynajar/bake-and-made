"""Comando `simular_scan <uid> --terminal caja-1`: hace lo mismo que el ESP32, sin hardware.

Sirve para probar el kiosco en local: con el navegador vinculado a la terminal,
el siguiente polling aplica el inicio de sesión (o el rechazo).
"""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand, CommandError

from iot.models import LecturaRFID, Terminal


class Command(BaseCommand):
    """Procesa una lectura como si llegara a /api/rfid/scan/."""

    help = 'Simula pasar una tarjeta RFID por el lector de una terminal.'

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Recibe el UID y la terminal (por defecto caja-1)."""
        parser.add_argument('uid', help='UID de la tarjeta, por ejemplo A1B2C3D4.')
        parser.add_argument('--terminal', default='caja-1', help='Código de la terminal.')

    def handle(self, *args: Any, **opciones: Any) -> None:
        """Registra la lectura en la terminal e imprime el resultado."""
        terminal = Terminal.objects.filter(codigo=opciones['terminal']).first()
        if terminal is None:
            raise CommandError(
                f'No existe la terminal "{opciones["terminal"]}". Créala con crear_terminal.'
            )

        resultado, tarjeta = terminal.registrar_lectura(opciones['uid'])
        if resultado == LecturaRFID.OK:
            self.stdout.write(self.style.SUCCESS(
                f'OK: {tarjeta.usuario} activo en {terminal} (versión {terminal.version}).'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'Rechazada ({resultado}) en {terminal} (versión {terminal.version}).'
            ))
