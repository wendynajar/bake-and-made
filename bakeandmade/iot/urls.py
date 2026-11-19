"""Rutas de la app iot. Sin namespace, como el resto del proyecto."""

from django.urls import path

from . import views

urlpatterns = [
    path('api/rfid/scan/', views.rfid_scan, name='rfid_scan'),
    path('api/iot/estado/', views.estado, name='iot_estado'),
    path('api/iot/salir/', views.salir, name='iot_salir'),
    path('kiosco/<slug:codigo>/', views.kiosco, name='kiosco'),
]
