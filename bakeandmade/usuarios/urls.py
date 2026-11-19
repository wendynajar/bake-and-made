"""Rutas de autenticación y de la membresía VIP. Sin namespace: las plantillas usan {% url 'login' %}."""

from django.contrib.auth.views import LoginView
from django.urls import path

from . import views, views_vip

urlpatterns = [
    path('registro/', views.registro, name='registro'),
    path('login/', LoginView.as_view(template_name='usuarios/login.html'), name='login'),
    path('logout/', views.CerrarSesionView.as_view(next_page='inicio'), name='logout'),

    # Membresía VIP (Sweet Plan vigente)
    path('vip/', views_vip.pagina_vip, name='vip'),
    path('vip/v/<str:codigo>/', views_vip.video_qr, name='video_qr'),
    path('api/vip/fechas/', views_vip.api_fechas, name='vip_fechas'),
    path('api/vip/fechas/<int:pk>/', views_vip.api_fecha, name='vip_fecha'),
    path('api/vip/cumpleanios/', views_vip.api_cumpleanios, name='vip_cumpleanios'),
]
