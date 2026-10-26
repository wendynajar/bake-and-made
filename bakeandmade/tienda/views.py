
from decimal import Decimal, InvalidOperation
import uuid

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.db import transaction, IntegrityError
from django.db.models import F

from .models import Menu, Pedido, DetallePedido, CategoriaIngrediente, Ingrediente
from .forms import RegistroUsuarioForm
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from .models import Suscripcion
from .suscripciones import (PRECIO_SWEET_PLAN,plan_actual,suscripcion_vigente,sumar_un_mes,ingredientes_visibles_para)

def obtener_cantidad_carrito(request):
    carrito = request.session.get('carrito', {})
    personalizados = request.session.get('carrito_personalizados', [])

    cantidad_normal = sum(
        cantidad
        for cantidad in carrito.values()
        if type(cantidad) is int and cantidad > 0
    )

    cantidad_personalizada = sum(
        cupcake.get('cantidad', 1)
        for cupcake in personalizados
        if type(cupcake.get('cantidad', 1)) is int
        and cupcake.get('cantidad', 1) > 0
    )

    return cantidad_normal + cantidad_personalizada


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
    personalizados = request.session.get(
        'carrito_personalizados', []
    )

    productos_carrito = []
    total = Decimal('0.00')

    # Productos normales del catálogo
    productos = Menu.objects.filter(id__in=carrito.keys())

    for producto in productos:
        cantidad = carrito.get(str(producto.id), 0)

        if type(cantidad) is not int or cantidad <= 0:
            continue

        subtotal = producto.precio_base * cantidad
        total += subtotal

        productos_carrito.append({
            'tipo': 'normal',
            'producto': producto,
            'cantidad': cantidad,
            'subtotal': subtotal,
        })

    # Cupcakes personalizados
    nombres_pasos = {
        'base': 'Base',
        'relleno': 'Relleno',
        'cobertura': 'Cobertura',
        'topping': 'Topping',
    }

    for indice, cupcake in enumerate(personalizados):
        try:
            precio = Decimal(
                str(cupcake.get('precio_unitario', '0'))
            )
        except (InvalidOperation, TypeError, ValueError):
            continue

        cantidad = cupcake.get('cantidad', 1)

        if type(cantidad) is not int or cantidad <= 0:
            continue

        subtotal = precio * cantidad
        total += subtotal

        ingredientes_guardados = cupcake.get(
            'ingredientes', {}
        )

        ingredientes_lista = []

        if isinstance(ingredientes_guardados, dict):
            for paso, dato in ingredientes_guardados.items():
                if isinstance(dato, dict):
                    ingredientes_lista.append({
                        'paso': nombres_pasos.get(
                            paso, paso.capitalize()
                        ),
                        'nombre': dato.get('nombre', ''),
                    })

        dietas = [
            DIETAS_VALIDAS[d]
            for d in cupcake.get('dietas', [])
            if d in DIETAS_VALIDAS
        ]

        color = COLORES_FROSTING.get(
            cupcake.get('color_frosting', ''),
            cupcake.get('color_frosting', '')
        )

        productos_carrito.append({
            'tipo': 'personalizado',
            'indice_personalizado': indice,
            'nombre': cupcake.get(
                'nombre', 'Cupcake personalizado'
            ),
            'ingredientes': ingredientes_lista,
            'dietas': dietas,
            'color_frosting': color,
            'cantidad': cantidad,
            'precio_unitario': precio,
            'subtotal': subtotal,
        })

    return render(request, 'tienda/carrito.html', {
        'productos_carrito': productos_carrito,
        'total': total,
    })

def actualizar_cupcake_personalizado(request, indice):
    if request.method != 'POST':
        return redirect('ver_carrito')

    personalizados = request.session.get(
        'carrito_personalizados', []
    )

    if not (0 <= indice < len(personalizados)):
        return redirect('ver_carrito')

    accion = request.POST.get('accion')
    cupcake = personalizados[indice]

    try:
        cantidad = int(cupcake.get('cantidad', 1))
    except (TypeError, ValueError):
        cantidad = 1

    if accion == 'sumar':
        cupcake['cantidad'] = cantidad + 1

    elif accion == 'restar':
        cupcake['cantidad'] = max(1, cantidad - 1)

    personalizados[indice] = cupcake
    request.session['carrito_personalizados'] = personalizados
    request.session.modified = True

    return redirect('ver_carrito')


def eliminar_cupcake_personalizado(request, indice):
    if request.method != 'POST':
        return redirect('ver_carrito')

    personalizados = request.session.get(
        'carrito_personalizados', []
    )

    if 0 <= indice < len(personalizados):
        personalizados.pop(indice)

        request.session['carrito_personalizados'] = personalizados
        request.session.modified = True

    return redirect('ver_carrito')


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

# =====================================================
# 10. PERSONALIZACIÓN DE CUPCAKES
# =====================================================
def personalizar(request):
    return render(request, 'tienda/personalizar.html')

PRECIO_BASE_CUPCAKE = Decimal("35.00")

PASOS = [
    {
        "slug": "base",
        "nombre": "Base",
        "categoria": "Base",
        "descripcion": "Elige el sabor de tu bizcocho.",
    },
    {
        "slug": "relleno",
        "nombre": "Relleno",
        "categoria": "Relleno",
        "descripcion": "Elige el centro de tu cupcake.",
    },
    {
        "slug": "cobertura",
        "nombre": "Cobertura",
        "categoria": "Cobertura",
        "descripcion": "Elige el frosting y su color.",
    },
    {
        "slug": "topping",
        "nombre": "Topping",
        "categoria": "Topping",
        "descripcion": "Dale el toque final a tu creación.",
    },
]

CLAVES_SESION = {
    "base": "cupcake_base",
    "relleno": "cupcake_relleno",
    "cobertura": "cupcake_cobertura",
    "topping": "cupcake_topping",
}

#Las preferencias dietarias son modificadores opcionales de la base.
DIETAS_VALIDAS = {
    "sin_gluten": "Sin gluten",
    "sin_lactosa": "Sin lactosa",
    "vegano": "Vegano",
    "bajo_azucar": "Bajo en azúcar",
}

COLORES_FROSTING = {
    "blanco": "Blanco",
    "rosa": "Rosa",
    "azul": "Azul",
    "lila": "Lila",
    "amarillo": "Amarillo",
    "verde": "Verde",
    "chocolate": "Chocolate",
}


def _ingrediente_de_sesion(request, paso_slug):
    """Devuelve una opción activa válida guardada en la sesión."""
    ingrediente_id = request.session.get(
        CLAVES_SESION[paso_slug]
    )

    if not ingrediente_id:
        return None

    paso = next(p for p in PASOS if p["slug"] == paso_slug)

    return ingredientes_visibles_para(
        request.user,
        Ingrediente.objects.filter(
            pk=ingrediente_id,
            activo=True,
            categoria__nombre__iexact=paso["categoria"],
        ),
    ).first()


def _selecciones_actuales(request):
    return {
        paso["slug"]: _ingrediente_de_sesion(
            request, paso["slug"]
        )
        for paso in PASOS
    }


def _precio_total(selecciones):
    total = PRECIO_BASE_CUPCAKE

    for ingrediente in selecciones.values():
        if ingrediente is not None:
            total += ingrediente.precio_adicional

    return total


def _todo_completo(selecciones):
    return all(selecciones[p["slug"]] for p in PASOS)


def personalizar_cupcake(request, paso="base"):
    pasos_validos = [p["slug"] for p in PASOS] + ["resumen"]

    if paso not in pasos_validos:
        return redirect("personalizar_paso", paso="base")

    selecciones = _selecciones_actuales(request)
    paso_actual = request.session.get("cupcake_paso_actual", 0)

    # Impide saltarse pasos mediante la URL.
    if paso == "resumen":
        if not _todo_completo(selecciones):
            for indice, p in enumerate(PASOS):
                if not selecciones[p["slug"]]:
                    request.session["cupcake_paso_actual"] = indice
                    return redirect("personalizar_paso", paso=p["slug"])
    else:
        indice_solicitado = next(
            i for i, p in enumerate(PASOS)
            if p["slug"] == paso
        )

        if indice_solicitado > paso_actual:
            destino = (
                PASOS[paso_actual]["slug"]
                if paso_actual < len(PASOS)
                else "resumen"
            )
            return redirect("personalizar_paso", paso=destino)

    if request.method == "POST" and paso != "resumen":
        indice = next(
            i for i, p in enumerate(PASOS)
            if p["slug"] == paso
        )
        definicion = PASOS[indice]

        ingrediente = ingredientes_visibles_para(
            request.user,
            Ingrediente.objects.filter(
                pk=request.POST.get('ingrediente'),
                activo=True,
                categoria__nombre__iexact=definicion["categoria"],
            ),
        ).first()

        if not ingrediente:
            messages.error(
                request,
                "Selecciona una opción válida para continuar."
            )
        else:
            request.session[CLAVES_SESION[paso]] = ingrediente.pk

            if paso == "base":
                dietas = request.POST.getlist("dietas")
                request.session["cupcake_dietas"] = [
                    dieta for dieta in dietas
                    if dieta in DIETAS_VALIDAS
                ]

            if paso == "cobertura":
                color = request.POST.get("color_frosting", "")
                if color not in COLORES_FROSTING:
                    messages.error(
                        request,
                        "Selecciona un color para el frosting."
                    )
                    return redirect(
                        "personalizar_paso", paso="cobertura"
                    )

                request.session["cupcake_color"] = color

            request.session.modified = True

            # Desde el resumen, editar devuelve al resumen.
            if request.POST.get("volver_resumen") == "1":
                return redirect(
                    "personalizar_paso", paso="resumen"
                )

            siguiente_indice = indice + 1
            request.session["cupcake_paso_actual"] = (
                siguiente_indice
            )

            if siguiente_indice >= len(PASOS):
                return redirect(
                    "personalizar_paso", paso="resumen"
                )

            return redirect(
                "personalizar_paso",
                paso=PASOS[siguiente_indice]["slug"],
            )

    selecciones = _selecciones_actuales(request)
    contexto = {
        "pasos": PASOS,
        "paso": paso,
        "selecciones": selecciones,
        "precio_base": PRECIO_BASE_CUPCAKE,
        "precio_total": _precio_total(selecciones),
        "dietas": DIETAS_VALIDAS,
        "dietas_elegidas": request.session.get(
            "cupcake_dietas", []
        ),
        "colores_frosting": COLORES_FROSTING,
        "color_frosting": request.session.get(
            "cupcake_color", ""
        ),
    }

    if paso == "resumen":
        return render(
            request,
            "tienda/personalizar_resumen.html",
            contexto,
        )

    definicion = next(p for p in PASOS if p["slug"] == paso)

    indice_actual = next(
        i for i, p in enumerate(PASOS)
        if p["slug"] == paso
    )

    contexto["paso_anterior"] = (
        PASOS[indice_actual - 1]["slug"]
        if indice_actual > 0 else None
    )

    contexto.update({
        "definicion": definicion,
        "numero_paso": next(
            i for i, p in enumerate(PASOS, start=1)
            if p["slug"] == paso
        ),
        "total_pasos": len(PASOS) + 1,
        "opciones": ingredientes_visibles_para(
            request.user,
            Ingrediente.objects.filter(
                activo=True,
                categoria__nombre__iexact=definicion["categoria"],
            ),
        ).order_by("nombre"),
        "seleccion_actual": selecciones[paso],
        "volver_resumen": (
            request.GET.get("volver") == "resumen"
        ),
    })

    return render(
        request,
        "tienda/personalizar_paso.html",
        contexto,
    )


@require_POST
def agregar_cupcake_personalizado(request):
    selecciones = _selecciones_actuales(request)

    if not _todo_completo(selecciones):
        messages.error(
            request,
            "Completa todos los pasos antes de agregar tu cupcake."
        )
        return redirect("personalizar_paso", paso="base")

    # Se vuelve a calcular en el servidor; no se acepta
    # ningún precio enviado por el navegador.
    total = _precio_total(selecciones)

    cupcake_carrito = {
        "tipo": "cupcake_personalizado",
        "nombre": "Cupcake personalizado",
        "ingredientes": {
            paso: {
                "id": ingrediente.pk,
                "nombre": ingrediente.nombre,
            }
            for paso, ingrediente in selecciones.items()
        },
        "dietas": request.session.get("cupcake_dietas", []),
        "color_frosting": request.session.get(
            "cupcake_color", ""
        ),
        "precio_unitario": str(total),
        "cantidad": 1,
    }

    carrito = request.session.get("carrito_personalizados", [])
    carrito.append(cupcake_carrito)
    request.session["carrito_personalizados"] = carrito
    request.session.modified = True

    # Limpia el asistente para permitir crear otro cupcake.
    for clave in CLAVES_SESION.values():
        request.session.pop(clave, None)

    request.session.pop("cupcake_paso_actual", None)
    request.session.pop("cupcake_dietas", None)
    request.session.pop("cupcake_color", None)

    messages.success(
        request,
        "¡Tu cupcake personalizado se agregó al carrito!"
    )

    return redirect("ver_carrito")

def pagina_suscripcion(request):
    suscripcion = suscripcion_vigente(request.user)
    return render(request, 'tienda/suscripcion.html', {
        'suscripcion_usuario': suscripcion,
        'plan_usuario_actual': plan_actual(request.user),
        'precio_sweet_plan': PRECIO_SWEET_PLAN,
    })


@login_required
def confirmar_suscripcion(request):
    if plan_actual(request.user) == 'sweet':
        messages.info(
            request,
            'Ya tienes acceso al Sweet Plan hasta la fecha indicada.',
        )
        return redirect('suscripcion')

    if request.method == 'POST':
        fecha_inicio = timezone.localdate()
        fecha_fin = sumar_un_mes(fecha_inicio)

        # TODO: integrar pasarela de pago antes de crear la suscripción real.
        # Esta confirmación es simulada y no guarda datos bancarios.
        Suscripcion.objects.create(
            usuario=request.user,
            estado='activa',
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            monto_mensual=PRECIO_SWEET_PLAN,
        )
        messages.success(
            request,
            '¡Tu Sweet Plan está activo! Disfruta tus ingredientes exclusivos.',
        )
        return redirect('suscripcion')

    return render(request, 'tienda/confirmar_suscripcion.html', {
        'precio_sweet_plan': PRECIO_SWEET_PLAN,
    })


@login_required
@require_POST
def cancelar_suscripcion(request):
    hoy = timezone.localdate()
    suscripcion = Suscripcion.objects.filter(
        usuario=request.user,
        estado='activa',
        fecha_fin__gte=hoy,
    ).order_by('-fecha_inicio', '-pk').first()

    if suscripcion is None:
        vigente = suscripcion_vigente(request.user)
        if vigente and vigente.estado == 'cancelada':
            messages.info(
                request,
                'Tu suscripción ya está cancelada. Conservas el acceso hasta '
                f'el {vigente.fecha_fin:%d/%m/%Y}.',
            )
        else:
            messages.warning(request, 'No tienes una suscripción activa que cancelar.')
        return redirect('suscripcion')

    Suscripcion.objects.filter(
        usuario=request.user,
        estado='activa',
        fecha_fin__gte=hoy,
    ).update(estado='cancelada')

    messages.success(
        request,
        'Tu Sweet Plan fue cancelado. Mantendrás el acceso hasta '
        f'el {suscripcion.fecha_fin:%d/%m/%Y}.',
    )
    return redirect('suscripcion')
