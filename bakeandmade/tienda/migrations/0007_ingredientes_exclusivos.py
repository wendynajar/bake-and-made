"""Marca los ingredientes exclusivos del Sweet Plan en bases ya existentes (hallazgo #9).

`cargar_catalogo` solo fija `solo_suscriptores` al crear un ingrediente, así que en
producción (donde ya existen) hace falta esta migración de datos. Corre una sola
vez; si después el admin cambia un ingrediente, su decisión se respeta.
"""

from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor

EXCLUSIVOS = [
    ('Base', 'Red velvet'),
    ('Relleno', 'Dulce de leche'),
    ('Cobertura', 'Queso crema'),
    ('Topping', 'Fresas'),
]


def marcar_exclusivos(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Pone solo_suscriptores=True en los ingredientes premium, si existen."""
    Ingrediente = apps.get_model('tienda', 'Ingrediente')
    for categoria, nombre in EXCLUSIVOS:
        Ingrediente.objects.filter(categoria__nombre=categoria, nombre=nombre).update(
            solo_suscriptores=True
        )


def desmarcar_exclusivos(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Revierte la marca para que la migración se pueda deshacer."""
    Ingrediente = apps.get_model('tienda', 'Ingrediente')
    for categoria, nombre in EXCLUSIVOS:
        Ingrediente.objects.filter(categoria__nombre=categoria, nombre=nombre).update(
            solo_suscriptores=False
        )


class Migration(migrations.Migration):

    dependencies = [
        ('tienda', '0006_capa_vip'),
    ]

    operations = [
        migrations.RunPython(marcar_exclusivos, desmarcar_exclusivos),
    ]
