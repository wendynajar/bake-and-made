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

    
]


# Mostrar imágenes durante el desarrollo
if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )

