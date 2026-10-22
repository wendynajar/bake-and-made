
from decimal import Decimal
import uuid

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db import transaction, IntegrityError
from django.db.models import F

from .models import Menu, Pedido, DetallePedido
from .forms import RegistroUsuarioForm


# =====================================================
# 1. PÁGINA PRINCIPAL Y CATÁLOGO
# =====================================================

def inicio(request):
    productos = Menu.objects.filter(
        disponible=True,
        stock__gt=0
    ).select_related('categoria')

    return render(request, 'tienda/inicio.html', {
        'productos': productos
    })


# =====================================================
# 2. REGISTRO DE CLIENTES
# =====================================================

def registro(request):
    if request.user.is_authenticated:
        return redirect('inicio')

    if request.method == 'POST':
        formulario = RegistroUsuarioForm(request.POST)

        if formulario.is_valid():
            usuario = formulario.save()
            login(request, usuario)

            messages.success(
                request,
                'Tu cuenta se ha creado correctamente. '
                '¡Bienvenido a Bake & Made!'
            )

            return redirect('inicio')
    else:
        formulario = RegistroUsuarioForm()

    return render(request, 'tienda/registro.html', {
        'formulario': formulario
    })


# =====================================================
# 3. INICIO DE SESIÓN
# =====================================================

def iniciar_sesion(request):
    if request.user.is_authenticated:
        return redirect('inicio')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        usuario = authenticate(
            request,
            username=username,
            password=password
        )

        if usuario is not None:
            login(request, usuario)

            messages.success(
                request,
                'Has iniciado sesión correctamente.'
            )

            return redirect('inicio')

        messages.error(
            request,
            'Usuario o contraseña incorrectos.'
        )

    return render(request, 'tienda/login.html')


# =====================================================
# 4. CIERRE DE SESIÓN
# =====================================================

@require_POST
def cerrar_sesion(request):
    logout(request)

    messages.success(
        request,
        'Has cerrado sesión correctamente.'
    )

    return redirect('inicio')


# =====================================================
# 5. AGREGAR PRODUCTOS AL CARRITO
# =====================================================

@require_POST
def agregar_carrito(request, producto_id):
    producto = get_object_or_404(
        Menu,
        id=producto_id,
        disponible=True,
        stock__gt=0
    )

    carrito = request.session.get('carrito', {})
    clave = str(producto.id)

    cantidad_actual = carrito.get(clave, 0)

    if (
        type(cantidad_actual) is not int
        or cantidad_actual < 0
    ):
        messages.error(
            request,
            'La cantidad del producto no es válida.'
        )
        return redirect('ver_carrito')

    if cantidad_actual < producto.stock:
        carrito[clave] = cantidad_actual + 1
        request.session['carrito'] = carrito

        messages.success(
            request,
            f'{producto.nombre_producto} se agregó al carrito.'
        )
    else:
        messages.warning(
            request,
            'No hay suficientes unidades disponibles.'
        )

    return redirect('inicio')


# =====================================================
# 6. MOSTRAR CARRITO
# =====================================================

def ver_carrito(request):
    carrito = request.session.get('carrito', {})

    productos_carrito = []
    total = Decimal('0.00')

    productos = Menu.objects.filter(
        id__in=carrito.keys()
    )

    for producto in productos:
        cantidad = carrito.get(str(producto.id), 0)

        if type(cantidad) is not int or cantidad <= 0:
            continue

        subtotal = producto.precio_base * cantidad
        total += subtotal

        productos_carrito.append({
            'producto': producto,
            'cantidad': cantidad,
            'subtotal': subtotal
        })

    return render(request, 'tienda/carrito.html', {
        'productos_carrito': productos_carrito,
        'total': total
    })


# =====================================================
# 7. ACTUALIZAR CARRITO
# =====================================================

@require_POST
def actualizar_carrito(request, producto_id):
    carrito = request.session.get('carrito', {})
    clave = str(producto_id)

    if clave not in carrito:
        messages.error(
            request,
            'El producto no está en tu carrito.'
        )
        return redirect('ver_carrito')

    producto = get_object_or_404(
        Menu,
        id=producto_id
    )

    accion = request.POST.get('accion')
    cantidad = carrito[clave]

    if type(cantidad) is not int or cantidad <= 0:
        carrito.pop(clave, None)
        request.session['carrito'] = carrito

        messages.error(
            request,
            'Se eliminó una cantidad inválida del carrito.'
        )
        return redirect('ver_carrito')

    if accion == 'aumentar':
        if producto.disponible and cantidad < producto.stock:
            carrito[clave] = cantidad + 1

            messages.success(
                request,
                'Cantidad actualizada.'
            )
        else:
            messages.warning(
                request,
                'No hay más unidades disponibles.'
            )

    elif accion == 'disminuir':
        if cantidad > 1:
            carrito[clave] = cantidad - 1
        else:
            del carrito[clave]

        messages.success(
            request,
            'Carrito actualizado.'
        )

    elif accion == 'eliminar':
        del carrito[clave]

        messages.success(
            request,
            'Producto eliminado del carrito.'
        )

    else:
        messages.error(
            request,
            'Acción no válida.'
        )
        return redirect('ver_carrito')

    request.session['carrito'] = carrito

    return redirect('ver_carrito')


# =====================================================
# 8. CHECKOUT Y REGISTRO DE PEDIDOS
# =====================================================

@login_required
def checkout(request):
    carrito = request.session.get('carrito', {})

    if not carrito:
        messages.warning(
            request,
            'Tu carrito está vacío.'
        )
        return redirect('ver_carrito')

    productos_carrito = []
    total = Decimal('0.00')

    productos = list(
        Menu.objects.filter(id__in=carrito.keys())
    )

    if len(productos) != len(carrito):
        messages.error(
            request,
            'Algunos productos ya no existen.'
        )
        return redirect('ver_carrito')

    for producto in productos:
        cantidad = carrito.get(str(producto.id), 0)

        if (
            type(cantidad) is not int
            or cantidad <= 0
            or not producto.disponible
            or cantidad > producto.stock
        ):
            messages.error(
                request,
                f'Revisa la disponibilidad de '
                f'{producto.nombre_producto}.'
            )
            return redirect('ver_carrito')

        subtotal = producto.precio_base * cantidad
        total += subtotal

        productos_carrito.append({
            'producto': producto,
            'cantidad': cantidad,
            'subtotal': subtotal
        })

    # Generar un token para el formulario.
    if request.method == 'GET':
        request.session['checkout_token'] = str(uuid.uuid4())
        request.session['checkout_total'] = str(total)

    checkout_token = request.session.get('checkout_token')

    if request.method == 'POST':
        token_enviado = request.POST.get(
            'checkout_token', ''
        )
        token_sesion = request.session.get(
            'checkout_token'
        )

        if not token_sesion or token_enviado != token_sesion:
            messages.error(
                request,
                'La solicitud de compra no es válida '
                'o ya fue procesada.'
            )
            return redirect('ver_carrito')

        direccion = request.POST.get(
            'direccion_entrega', ''
        ).strip()

        if not direccion or len(direccion) > 1000:
            messages.error(
                request,
                'Ingresa una dirección válida '
                'de hasta 1000 caracteres.'
            )

            return render(
                request,
                'tienda/checkout.html',
                {
                    'productos_carrito': productos_carrito,
                    'total': total,
                    'checkout_token': checkout_token
                }
            )

        # Comprobar el importe mostrado al cliente.
        total_mostrado = request.session.get(
            'checkout_total'
        )

        if total_mostrado != str(total):
            messages.warning(
                request,
                'El importe de tu carrito cambió. '
                'Revisa el pedido antes de confirmarlo.'
            )
            return redirect('checkout')

        try:
            with transaction.atomic():
                productos_actualizados = list(
                    Menu.objects.filter(
                        id__in=carrito.keys()
                    )
                )

                if len(productos_actualizados) != len(carrito):
                    messages.error(
                        request,
                        'Algunos productos ya no están disponibles.'
                    )
                    return redirect('ver_carrito')

                total_actualizado = Decimal('0.00')
                detalles_actualizados = []

                for producto in productos_actualizados:
                    cantidad = carrito.get(
                        str(producto.id), 0
                    )

                    if (
                        type(cantidad) is not int
                        or cantidad <= 0
                        or not producto.disponible
                        or cantidad > producto.stock
                    ):
                        messages.error(
                            request,
                            f'No hay suficientes unidades de '
                            f'{producto.nombre_producto}.'
                        )
                        return redirect('ver_carrito')

                    total_actualizado += (
                        producto.precio_base * cantidad
                    )

                    detalles_actualizados.append({
                        'producto': producto,
                        'cantidad': cantidad,
                        'precio_unitario': producto.precio_base
                    })

                # No confirmar precios diferentes.
                if total_actualizado != total:
                    messages.warning(
                        request,
                        'Los precios cambiaron. '
                        'Revisa nuevamente tu pedido.'
                    )
                    return redirect('checkout')

                # Registrar el pedido una sola vez
                # por identificador único.
                pedido = Pedido.objects.create(
                    usuario=request.user,
                    total=total_actualizado,
                    direccion_entrega=direccion,
                    estado_pedido='pendiente',
                    checkout_token=token_sesion
                )

                # Reservar las unidades de manera
                # atómica para evitar sobreventa.
                for item in detalles_actualizados:
                    cantidad = item['cantidad']
                    producto = item['producto']

                    actualizados = Menu.objects.filter(
                        pk=producto.pk,
                        disponible=True,
                        stock__gte=cantidad
                    ).update(
                        stock=F('stock') - cantidad
                    )

                    if actualizados != 1:
                        raise ValueError(
                            'El inventario cambió durante '
                            'la confirmación.'
                        )

                    DetallePedido.objects.create(
                        pedido=pedido,
                        menu_item=producto,
                        cantidad=cantidad,
                        precio_unitario=item['precio_unitario']
                    )

        except IntegrityError:
            messages.error(
                request,
                'No fue posible registrar el pedido. '
                'Comprueba si ya lo confirmaste.'
            )
            return redirect('ver_carrito')

        except ValueError:
            messages.error(
                request,
                'Las existencias cambiaron mientras '
                'confirmabas tu pedido. '
                'Revisa nuevamente tu carrito.'
            )
            return redirect('ver_carrito')

        # Vaciar el carrito solo después de
        # guardar el pedido correctamente.
        request.session['carrito'] = {}
        request.session.pop('checkout_token', None)
        request.session.pop('checkout_total', None)

        messages.success(
            request,
            f'Tu pedido #{pedido.id} se registró correctamente.'
        )

        return redirect('pedido_confirmado', pedido_id=pedido.id)

    return render(
        request,
        'tienda/checkout.html',
        {
            'productos_carrito': productos_carrito,
            'total': total,
            'checkout_token': checkout_token
        }
    )


# =====================================================
# 9. CONFIRMACIÓN DE PEDIDOS
# =====================================================

@login_required
def pedido_confirmado(request, pedido_id):
    pedido = get_object_or_404(
        Pedido,
        id=pedido_id,
        usuario=request.user
    )

    return render(
        request,
        'tienda/pedido_confirmado.html',
        {
            'pedido': pedido
        }
    )
