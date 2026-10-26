"""Reglas de negocio para los planes Basic y Sweet."""

from calendar import monthrange
from decimal import Decimal

from django.utils import timezone

from .models import Ingrediente, Suscripcion


# Única fuente de verdad para el precio mensual de Sweet.
PRECIO_SWEET_PLAN = Decimal("99.00")


def sumar_un_mes(fecha):
    """Devuelve la misma fecha del mes siguiente, ajustando meses cortos."""
    if fecha.month == 12:
        anio_siguiente = fecha.year + 1
        mes_siguiente = 1
    else:
        anio_siguiente = fecha.year
        mes_siguiente = fecha.month + 1

    dia_siguiente = min(
        fecha.day,
        monthrange(anio_siguiente, mes_siguiente)[1],
    )
    return fecha.replace(
        year=anio_siguiente,
        month=mes_siguiente,
        day=dia_siguiente,
    )


def suscripcion_vigente(usuario):
    """Devuelve la suscripción con acceso vigente, si existe.

    Las suscripciones canceladas conservan el acceso hasta fecha_fin.
    Cualquier suscripción que ya pasó su fecha_fin queda marcada como expirada.
    """
    if not getattr(usuario, "is_authenticated", False):
        return None

    hoy = timezone.localdate()

    Suscripcion.objects.filter(
        usuario=usuario,
        fecha_fin__lt=hoy,
    ).exclude(
        estado="expirada",
    ).update(estado="expirada")

    return Suscripcion.objects.filter(
        usuario=usuario,
        estado__in=("activa", "cancelada"),
        fecha_fin__gte=hoy,
    ).order_by("-fecha_inicio", "-pk").first()


def plan_actual(usuario):
    """Devuelve 'sweet' si tiene acceso vigente; de lo contrario, 'basic'."""
    return "sweet" if suscripcion_vigente(usuario) else "basic"


def ingredientes_visibles_para(usuario, queryset=None):
    """Filtra ingredientes exclusivos para usuarios sin acceso Sweet.

    Puede recibir un queryset ya filtrado por categoría/estado para conservar
    esos filtros y aplicar únicamente la regla de suscripción.
    """
    if queryset is None:
        queryset = Ingrediente.objects.all()

    if plan_actual(usuario) == "sweet":
        return queryset

    return queryset.filter(solo_suscriptores=False)
