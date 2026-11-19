"""Campos de la capa VIP (docs/IOT_VIP_SPEC.md, fase 1).

- Pedido: descuento cobrado (porcentaje y motivo).
- RecordatorioEvento: tipo de fecha y si se repite cada año.
- ExperienciaQR: pasa a ser el video del usuario. `url_video` se renombra a
  `video` (FileField en S3) en lugar de borrarse, para no perder datos.
"""

import django.db.models.deletion
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models

import tienda.models


class Migration(migrations.Migration):

    dependencies = [
        ('tienda', '0005_ingrediente_activo_ingrediente_imagen'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='pedido',
            name='descuento_porcentaje',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0'),
                help_text='Fracción descontada: 0.20 = 20 %.',
                max_digits=3,
            ),
        ),
        migrations.AddField(
            model_name='pedido',
            name='motivo_descuento',
            field=models.CharField(
                blank=True,
                choices=[('', 'Sin descuento'), ('vip', 'VIP'), ('cumpleanios', 'Cumpleaños')],
                default='',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='recordatorioevento',
            name='tipo',
            field=models.CharField(
                choices=[
                    ('cumpleanios', 'Cumpleaños'),
                    ('aniversario', 'Aniversario'),
                    ('otro', 'Otro'),
                ],
                default='otro',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='recordatorioevento',
            name='se_repite_cada_anio',
            field=models.BooleanField(default=False),
        ),
        migrations.RenameField(
            model_name='experienciaqr',
            old_name='url_video',
            new_name='video',
        ),
        migrations.AlterField(
            model_name='experienciaqr',
            name='video',
            field=models.FileField(max_length=255, upload_to='videos/'),
        ),
        migrations.AlterField(
            model_name='experienciaqr',
            name='detalle_pedido',
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='tienda.detallepedido',
            ),
        ),
        migrations.AlterField(
            model_name='experienciaqr',
            name='codigo_unico',
            field=models.CharField(
                default=tienda.models.generar_codigo_qr, max_length=100, unique=True
            ),
        ),
        migrations.AddField(
            model_name='experienciaqr',
            name='usuario',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='experiencias_qr',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
