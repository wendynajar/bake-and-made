"""Comando `crear_usuarios_demo`: los 3 usuarios Sweet de la demo VIP (idempotente).

Crea cada usuario con los campos de la tabla `Usuarios` del diagrama ER (nombre,
email, contraseña con hash, teléfono y fecha de registro), le registra y entrega
su tarjeta en el orden dado y le contrata el Sweet Plan si no lo tiene vigente.

La contraseña sale de la variable de entorno DEMO_PASSWORD y los UID de --uids o
de DEMO_VIP_UIDS: ninguno se escribe en el código (docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import datetime
import os
from argparse import ArgumentParser
from dataclasses import dataclass
from typing import Any

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from iot.models import TarjetaRFID, normalizar_uid
from tienda.models import PLAN_SWEET, Suscripcion
from usuarios.models import PerfilVIP


@dataclass(frozen=True)
class UsuarioDemo:
    """Una fila de la tabla de usuarios demo de docs/IOT_VIP_SPEC.md."""

    nombre: str
    apellido: str
    email: str
    telefono: str
    fecha_registro: datetime.date


USUARIOS_DEMO: tuple[UsuarioDemo, ...] = (
    UsuarioDemo('Ana', 'López', 'ana.demo@bakeandmade.test', '5510000001', datetime.date(2026, 9, 1)),
    UsuarioDemo('Bruno', 'García', 'bruno.demo@bakeandmade.test', '5510000002', datetime.date(2026, 9, 15)),
    UsuarioDemo('Carla', 'Méndez', 'carla.demo@bakeandmade.test', '5510000003', datetime.date(2026, 10, 1)),
)


class Command(BaseCommand):
    """Crea o actualiza los usuarios demo sin duplicar usuarios, tarjetas ni suscripciones."""

    help = (
        'Crea los 3 usuarios Sweet de la demo con su tarjeta VIP. '
        'Requiere DEMO_PASSWORD y los UID en --uids o DEMO_VIP_UIDS.'
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        """Permite pasar los UID por argumento (tienen prioridad sobre DEMO_VIP_UIDS)."""
        parser.add_argument(
            '--uids',
            help='3 UID separados por comas, en el orden Ana, Bruno, Carla.',
        )

    def handle(self, *args: Any, **opciones: Any) -> None:
        """Valida todo antes de escribir y luego crea los usuarios en una transacción."""
        password = os.environ.get('DEMO_PASSWORD', '')
        if not password:
            raise CommandError('Define la variable de entorno DEMO_PASSWORD con la contraseña demo.')

        uids = self._leer_uids(opciones.get('uids') or os.environ.get('DEMO_VIP_UIDS', ''))
        self._validar_tarjetas_libres_o_propias(uids)

        with transaction.atomic():
            for datos, uid in zip(USUARIOS_DEMO, uids, strict=True):
                self._crear_usuario(datos, uid, password)

        self.stdout.write(self.style.SUCCESS('Usuarios demo listos.'))

    def _leer_uids(self, texto: str) -> list[str]:
        """Normaliza y valida que vengan exactamente 3 UID distintos y bien formados."""
        uids = [normalizar_uid(uid) for uid in texto.split(',') if uid.strip()]
        if len(uids) != len(USUARIOS_DEMO):
            raise CommandError(
                f'Se necesitan {len(USUARIOS_DEMO)} UID separados por comas '
                '(--uids o DEMO_VIP_UIDS).'
            )
        if len(set(uids)) != len(uids):
            raise CommandError('Los UID de la demo no pueden repetirse.')
        for uid in uids:
            try:
                TarjetaRFID(uid=uid).clean_fields(exclude=['usuario'])
            except ValidationError as error:
                raise CommandError(f'UID inválido "{uid}": {"; ".join(error.messages)}') from error
        return uids

    def _validar_tarjetas_libres_o_propias(self, uids: list[str]) -> None:
        """Falla sin escribir nada si un UID ya pertenece a alguien que no es su usuario demo."""
        for datos, uid in zip(USUARIOS_DEMO, uids, strict=True):
            tarjeta = TarjetaRFID.objects.filter(uid=uid).select_related('usuario').first()
            if tarjeta and tarjeta.usuario and tarjeta.usuario.username != datos.email:
                raise CommandError(
                    f'La tarjeta {uid} ya pertenece a {tarjeta.usuario}; no se puede dar a {datos.email}.'
                )

    def _crear_usuario(self, datos: UsuarioDemo, uid: str, password: str) -> None:
        """Crea o actualiza un usuario demo, su perfil, su tarjeta y su Sweet Plan."""
        usuario, creado = User.objects.get_or_create(username=datos.email)
        usuario.email = datos.email
        usuario.first_name = datos.nombre
        usuario.last_name = datos.apellido
        usuario.date_joined = timezone.make_aware(
            datetime.datetime.combine(datos.fecha_registro, datetime.time())
        )
        # set_password guarda el hash; DEMO_PASSWORD sigue siendo la fuente de verdad.
        usuario.set_password(password)
        usuario.save()

        perfil = PerfilVIP.de(usuario)
        perfil.telefono = datos.telefono
        perfil.save(update_fields=['telefono'])

        # Se asigna la tarjeta de su posición antes de contratar el plan, para que
        # la entrega simulada no le dé otra tarjeta libre del inventario.
        tarjeta, _ = TarjetaRFID.objects.get_or_create(uid=uid)
        if tarjeta.usuario_id is None and not TarjetaRFID.objects.filter(usuario=usuario).exists():
            tarjeta.usuario = usuario
            tarjeta.entregada_en = timezone.now()
            tarjeta.save(update_fields=['usuario', 'entregada_en'])
        elif tarjeta.usuario_id != usuario.pk:
            self.stdout.write(
                self.style.WARNING(f'{datos.email} ya tenía otra tarjeta; {uid} queda libre.')
            )

        if Suscripcion.objects.plan_de(usuario) != PLAN_SWEET:
            Suscripcion.contratar_mes(usuario)

        accion = 'creado' if creado else 'actualizado'
        self.stdout.write(f'{datos.nombre} {datos.apellido} ({datos.email}): {accion}, tarjeta {uid}.')
