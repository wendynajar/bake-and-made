from django.contrib.auth.views import LoginView, LogoutView
from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from tienda import views


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', views.inicio, name='inicio'),
    path('registro/', views.registro, name='registro'),
    
    path(
    'login/',
    LoginView.as_view(template_name='tienda/login.html'),
    name='login'
    ),

    path(
        'carrito/agregar/<int:producto_id>/',
        views.agregar_carrito,
        name='agregar_carrito'
    ),
    
    path('logout/', LogoutView.as_view(next_page='inicio'), name='logout'),
    
    path(
    'carrito/',
    views.ver_carrito,
    name='ver_carrito'
    ),

    path('checkout/', views.checkout, name='checkout'),

    path(
    'carrito/actualizar/<int:producto_id>/',
    views.actualizar_carrito,
    name='actualizar_carrito'
    ),

    path('pedido-confirmado/<int:pedido_id>/', views.pedido_confirmado, name='pedido_confirmado'),

    path(
        "personalizar/",
        views.personalizar_cupcake,
        {"paso": "base"},
        name="personalizar",
    ),
    path(
            "personalizar/agregar/",
            views.agregar_cupcake_personalizado,
            name="agregar_cupcake_personalizado",
        ),
    path(
        "personalizar/<str:paso>/",
        views.personalizar_cupcake,
        name="personalizar_paso",
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

    path('suscripcion/', views.pagina_suscripcion, name='suscripcion'),
    path('suscripcion/confirmar/', views.confirmar_suscripcion, name='confirmar_suscripcion'),
    path('suscripcion/cancelar/', views.cancelar_suscripcion, name='cancelar_suscripcion'),
]


# Mostrar imágenes durante el desarrollo
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )

