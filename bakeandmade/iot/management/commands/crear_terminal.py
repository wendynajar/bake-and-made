"""Comando `crear_terminal <codigo>`: da de alta una computadora del kiosco (idempotente).

Se ejecuta en el build de Render (`crear_terminal caja-1`), por eso no falla si
la terminal ya existe.
"""

from argparse import ArgumentParser
from typing import Any

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_slug

from iot.models import Terminal


class Command(BaseCommand):
    """Crea la terminal si no existe."""

    help = 'Crea una terminal del kiosco (por ejemplo: caja-1). Se puede repetir sin duplicar.'

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Recibe el código de la terminal."""
        parser.add_argument('codigo', help='Código de la terminal, en formato slug (caja-1).')

    def handle(self, *args: Any, **opciones: Any) -> None:
        """Valida el código y crea la terminal con get_or_create."""
        codigo: str = opciones['codigo'].strip().lower()
        try:
            validate_slug(codigo)
        except ValidationError as error:
            raise CommandError(f'Código inválido "{codigo}": usa letras, números y guiones.') from error

        _, creada = Terminal.objects.get_or_create(codigo=codigo)
        if creada:
            self.stdout.write(self.style.SUCCESS(f'Terminal "{codigo}" creada.'))
        else:
            self.stdout.write(f'La terminal "{codigo}" ya existía; no se cambió.')
