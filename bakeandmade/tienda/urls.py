"""Rutas de la tienda. Los nombres no llevan namespace porque las plantillas
usan `{% url 'inicio' %}`, `{% url 'ver_carrito' %}`, etc."""

from django.urls import path

from . import views

urlpatterns = [
    path('', views.inicio, name='inicio'),

    # Carrito
    path('carrito/', views.ver_carrito, name='ver_carrito'),
    path('carrito/agregar/<int:producto_id>/', views.agregar_carrito, name='agregar_carrito'),
    path(
        'carrito/actualizar/<int:producto_id>/',
        views.actualizar_carrito,
        name='actualizar_carrito',
    ),
    path(
        'carrito/personalizado/<int:indice>/actualizar/',
        views.actualizar_cupcake_personalizado,
        name='actualizar_cupcake_personalizado',
    ),
    path(
        'carrito/personalizado/<int:indice>/eliminar/',
        views.eliminar_cupcake_personalizado,
        name='eliminar_cupcake_personalizado',
    ),

    # Checkout
    path('checkout/', views.checkout, name='checkout'),
    path(
        'pedido-confirmado/<int:pedido_id>/',
        views.pedido_confirmado,
        name='pedido_confirmado',
    ),

    # Asistente de cupcakes ("agregar/" va antes de "<str:paso>/" para no capturarlo)
    path('personalizar/', views.personalizar_cupcake, {'paso': 'base'}, name='personalizar'),
    path(
        'personalizar/agregar/',
        views.agregar_cupcake_personalizado,
        name='agregar_cupcake_personalizado',
    ),
    path('personalizar/<str:paso>/', views.personalizar_cupcake, name='personalizar_paso'),

    # Suscripciones
    path('suscripcion/', views.pagina_suscripcion, name='suscripcion'),
    path(
        'suscripcion/confirmar/',
        views.confirmar_suscripcion,
        name='confirmar_suscripcion',
    ),
    path(
        'suscripcion/cancelar/',
        views.cancelar_suscripcion,
        name='cancelar_suscripcion',
    ),
]
