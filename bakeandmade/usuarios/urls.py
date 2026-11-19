"""Rutas de autenticación. Sin namespace: las plantillas usan {% url 'login' %}."""

from django.contrib.auth.views import LoginView
from django.urls import path

from . import views

urlpatterns = [
    path('registro/', views.registro, name='registro'),
    path('login/', LoginView.as_view(template_name='usuarios/login.html'), name='login'),
    path('logout/', views.CerrarSesionView.as_view(next_page='inicio'), name='logout'),
]
