"""Configuración de la app iot (lector RFID ESP32 + RC522 y kiosco de la tienda)."""

from django.apps import AppConfig


class IotConfig(AppConfig):
    """Tarjetas VIP, terminales del kiosco y bitácora de lecturas del lector RFID."""

    name = 'iot'
    verbose_name = 'IoT (RFID)'
