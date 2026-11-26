"""Vistas HTTP de la tienda: catálogo, carrito, checkout, asistente y suscripciones.

Las vistas solo leen la petición, delegan la lógica de negocio en los modelos
(ver tienda/models.py) y deciden qué plantilla o redirección devolver.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .carrito import (
    CLAVE_CARRITO,
    CLAVE_PERSONALIZADOS,
    obtener_carrito,
    obtener_personalizados,
)
from .forms import DireccionEntregaForm
from .models import (
    PLAN_BASIC,
    PLAN_SWEET,
    PRECIO_SWEET_PLAN,
    CupcakePersonalizado,
    ErrorPedido,
    Ingrediente,
    Menu,
    Pedido,
    PrecioCambiado,
    Suscripcion,
    aplicar_descuento,
)
from .peticion import descuento_de_peticion


def _entero_o_none(valor: Any) -> int | None:
    """Convierte un ID recibido por formulario o sesión a int; None si no es válido."""
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None

# =====================================================
# 1. CATÁLOGO
# =====================================================


def inicio(request: HttpRequest) -> HttpResponse:
    """Página principal con los productos en venta y su precio final.

    `producto.precio_final` ya trae el descuento VIP del usuario (igual al
    precio base si no tiene).
    """
    descuento, _ = descuento_de_peticion(request)
    productos = list(Menu.objects.en_venta().select_related('categoria'))
    for producto in productos:
        producto.precio_final = aplicar_descuento(producto.precio_base, descuento)
    return render(request, 'tienda/inicio.html', {'productos': productos})


# =====================================================
# 2. CARRITO
# =====================================================


@require_POST
def agregar_carrito(request: HttpRequest, producto_id: int) -> HttpResponse:
    """Suma una unidad del producto al carrito sin superar su stock."""
    producto = get_object_or_404(Menu.objects.en_venta(), id=producto_id)

    carrito = obtener_carrito(request)
    clave = str(producto.id)
    cantidad_actual = carrito.get(clave, 0)

    if type(cantidad_actual) is not int or cantidad_actual < 0:
        messages.error(request, 'La cantidad del producto no es válida.')
        return redirect('ver_carrito')

    if cantidad_actual < producto.stock:
        carrito[clave] = cantidad_actual + 1
        request.session[CLAVE_CARRITO] = carrito
        messages.success(request, f'{producto.nombre_producto} se agregó al carrito.')
    else:
        messages.warning(request, 'No hay suficientes unidades disponibles.')

    return redirect('inicio')


def _linea_personalizada(
    indice: int, cupcake: dict[str, Any], descuento: Decimal = Decimal('0')
) -> dict[str, Any] | None:
    """Prepara un cupcake personalizado de la sesión para mostrarlo en el carrito.

    `precio_base` es el calculado al armarlo ($35 + extras) y `precio_unitario`
    el final con el descuento VIP. Devuelve None si los datos guardados están
    corruptos (precio o cantidad inválidos).
    """
    if not isinstance(cupcake, dict):
        return None
    try:
        precio = Decimal(str(cupcake.get('precio_unitario', '0')))
    except (InvalidOperation, TypeError, ValueError):
        return None

    cantidad = cupcake.get('cantidad', 1)
    if type(cantidad) is not int or cantidad <= 0:
        return None

    nombres_pasos = {p.slug: p.nombre for p in CupcakePersonalizado.PASOS}
    ingredientes_guardados = cupcake.get('ingredientes', {})
    ingredientes = [
        {'paso': nombres_pasos.get(paso, paso.capitalize()), 'nombre': dato.get('nombre', '')}
        for paso, dato in (
            ingredientes_guardados.items() if isinstance(ingredientes_guardados, dict) else []
        )
        if isinstance(dato, dict)
    ]

    color = cupcake.get('color_frosting', '')
    precio_final = aplicar_descuento(precio, descuento)
    return {
        'tipo': 'personalizado',
        'indice_personalizado': indice,
        'nombre': cupcake.get('nombre', 'Cupcake personalizado'),
        'ingredientes': ingredientes,
        'dietas': [
            CupcakePersonalizado.DIETAS[d]
            for d in cupcake.get('dietas', [])
            if d in CupcakePersonalizado.DIETAS
        ],
        'color_frosting': CupcakePersonalizado.COLORES_FROSTING.get(color, color),
        'cantidad': cantidad,
        'precio_base': precio,
        'precio_unitario': precio_final,
        'subtotal_base': precio * cantidad,
        'subtotal': precio_final * cantidad,
    }


def ver_carrito(request: HttpRequest) -> HttpResponse:
    """Muestra productos del catálogo y cupcakes personalizados con su total.

    Cada línea lleva su precio base y su precio final con el descuento VIP; el
    total es la suma de líneas ya redondeadas, como se cobrará en el checkout.
    """
    descuento, _ = descuento_de_peticion(request)
    carrito = obtener_carrito(request)
    productos_carrito: list[dict[str, Any]] = []

    for producto in Menu.objects.filter(id__in=carrito.keys()):
        cantidad = carrito.get(str(producto.id), 0)
        if type(cantidad) is int and cantidad > 0:
            precio_final = aplicar_descuento(producto.precio_base, descuento)
            productos_carrito.append({
                'tipo': 'normal',
                'producto': producto,
                'cantidad': cantidad,
                'precio_base': producto.precio_base,
                'precio_unitario': precio_final,
                'subtotal_base': producto.precio_base * cantidad,
                'subtotal': precio_final * cantidad,
            })

    for indice, cupcake in enumerate(obtener_personalizados(request)):
        linea = _linea_personalizada(indice, cupcake, descuento)
        if linea is not None:
            productos_carrito.append(linea)

    subtotal = sum((item['subtotal_base'] for item in productos_carrito), Decimal('0.00'))
    total = sum((item['subtotal'] for item in productos_carrito), Decimal('0.00'))
    return render(request, 'tienda/carrito.html', {
        'productos_carrito': productos_carrito,
        'subtotal': subtotal,
        'ahorro': subtotal - total,
        'total': total,
    })


@require_POST
def actualizar_carrito(request: HttpRequest, producto_id: int) -> HttpResponse:
    """Aumenta, disminuye o elimina un producto del catálogo en el carrito."""
    carrito = obtener_carrito(request)
    clave = str(producto_id)

    if clave not in carrito:
        messages.error(request, 'El producto no está en tu carrito.')
        return redirect('ver_carrito')

    producto = get_object_or_404(Menu, id=producto_id)
    accion = request.POST.get('accion')
    cantidad = carrito[clave]

    if type(cantidad) is not int or cantidad <= 0:
        carrito.pop(clave, None)
        request.session[CLAVE_CARRITO] = carrito
        messages.error(request, 'Se eliminó una cantidad inválida del carrito.')
        return redirect('ver_carrito')

    if accion == 'aumentar':
        if producto.admite_cantidad(cantidad + 1):
            carrito[clave] = cantidad + 1
            messages.success(request, 'Cantidad actualizada.')
        else:
            messages.warning(request, 'No hay más unidades disponibles.')
    elif accion == 'disminuir':
        if cantidad > 1:
            carrito[clave] = cantidad - 1
        else:
            del carrito[clave]
        messages.success(request, 'Carrito actualizado.')
    elif accion == 'eliminar':
        del carrito[clave]
        messages.success(request, 'Producto eliminado del carrito.')
    else:
        messages.error(request, 'Acción no válida.')
        return redirect('ver_carrito')

    request.session[CLAVE_CARRITO] = carrito
    return redirect('ver_carrito')


@require_POST
def actualizar_cupcake_personalizado(request: HttpRequest, indice: int) -> HttpResponse:
    """Suma o resta una unidad de un cupcake personalizado (mínimo 1)."""
    personalizados = obtener_personalizados(request)

    if 0 <= indice < len(personalizados):
        cupcake = personalizados[indice]
        try:
            cantidad = int(cupcake.get('cantidad', 1))
        except (TypeError, ValueError):
            cantidad = 1

        accion = request.POST.get('accion')
        if accion == 'sumar':
            cupcake['cantidad'] = cantidad + 1
        elif accion == 'restar':
            cupcake['cantidad'] = max(1, cantidad - 1)

        request.session[CLAVE_PERSONALIZADOS] = personalizados
        request.session.modified = True

    return redirect('ver_carrito')


@require_POST
def eliminar_cupcake_personalizado(request: HttpRequest, indice: int) -> HttpResponse:
    """Quita un cupcake personalizado del carrito."""
    personalizados = obtener_personalizados(request)

    if 0 <= indice < len(personalizados):
        personalizados.pop(indice)
        request.session[CLAVE_PERSONALIZADOS] = personalizados
        request.session.modified = True

    return redirect('ver_carrito')


# =====================================================
# 3. CHECKOUT Y PEDIDOS
# =====================================================


@login_required
def checkout(request: HttpRequest) -> HttpResponse:
    """Muestra el resumen de compra (GET) y registra el pedido (POST).

    El GET genera un token de un solo uso y guarda el total mostrado; el POST
    exige ese token (evita pedidos duplicados) y que el total no haya cambiado.
    Procesa productos del catálogo y cupcakes personalizados (hallazgo #7).
    """
    carrito = obtener_carrito(request)
    personalizados = obtener_personalizados(request)
    if not carrito and not personalizados:
        messages.warning(request, 'Tu carrito está vacío.')
        return redirect('ver_carrito')

    try:
        lineas = [
            *Pedido.objects.lineas_validas(carrito),
            *Pedido.objects.personalizados_validos(personalizados, request.user),
        ]
    except ErrorPedido as error:
        messages.error(request, str(error))
        return redirect('ver_carrito')

    # El descuento se recalcula en cada petición: si cambia entre el GET y el POST
    # (medianoche de un cumpleaños, Sweet vencido), el total ya no coincide y se
    # pide revisar el pedido en vez de cobrar otro importe.
    descuento, motivo = descuento_de_peticion(request)
    subtotal = Pedido.objects.total_de(lineas)
    total = Pedido.objects.total_de(lineas, descuento)

    if request.method == 'GET':
        request.session['checkout_token'] = str(uuid.uuid4())
        request.session['checkout_total'] = str(total)

    form_direccion = DireccionEntregaForm(request.POST if request.method == 'POST' else None)
    contexto = {
        'productos_carrito': [linea.as_dict(descuento) for linea in lineas],
        'subtotal': subtotal,
        'ahorro': subtotal - total,
        'total': total,
        'checkout_token': request.session.get('checkout_token'),
        'form_direccion': form_direccion,
    }

    if request.method != 'POST':
        return render(request, 'tienda/checkout.html', contexto)

    token_sesion = request.session.get('checkout_token')
    if not token_sesion or request.POST.get('checkout_token', '') != token_sesion:
        messages.error(request, 'La solicitud de compra no es válida o ya fue procesada.')
        return redirect('ver_carrito')

    # Con error se vuelve a mostrar el formulario con lo que el cliente ya escribió.
    if not form_direccion.is_valid():
        messages.error(request, 'Revisa los datos de tu dirección de entrega.')
        return render(request, 'tienda/checkout.html', contexto)
    direccion = form_direccion.como_texto()

    if request.session.get('checkout_total') != str(total):
        messages.warning(
            request,
            'El importe de tu carrito cambió. Revisa el pedido antes de confirmarlo.',
        )
        return redirect('checkout')

    try:
        pedido = Pedido.objects.crear_desde_carrito(
            usuario=request.user,
            carrito=carrito,
            direccion=direccion,
            checkout_token=token_sesion,
            total_esperado=total,
            personalizados=personalizados,
            descuento=descuento,
            motivo=motivo,
        )
    except IntegrityError:
        messages.error(
            request,
            'No fue posible registrar el pedido. Comprueba si ya lo confirmaste.',
        )
        return redirect('ver_carrito')
    except PrecioCambiado as error:
        messages.warning(request, str(error))
        return redirect('checkout')
    except ErrorPedido as error:
        messages.error(request, str(error))
        return redirect('ver_carrito')

    # Vaciar ambos carritos solo después de guardar el pedido correctamente.
    request.session[CLAVE_CARRITO] = {}
    request.session[CLAVE_PERSONALIZADOS] = []
    request.session.pop('checkout_token', None)
    request.session.pop('checkout_total', None)

    messages.success(request, f'Tu pedido #{pedido.id} se registró correctamente.')
    return redirect('pedido_confirmado', pedido_id=pedido.id)


@login_required
def pedido_confirmado(request: HttpRequest, pedido_id: int) -> HttpResponse:
    """Confirmación de un pedido; solo la ve su dueño."""
    pedido = get_object_or_404(Pedido, id=pedido_id, usuario=request.user)
    return render(request, 'tienda/pedido_confirmado.html', {'pedido': pedido})


# =====================================================
# 4. ASISTENTE DE CUPCAKES PERSONALIZADOS
# =====================================================

# Claves de sesión donde el asistente guarda cada selección.
CLAVES_SESION: dict[str, str] = {
    'base': 'cupcake_base',
    'relleno': 'cupcake_relleno',
    'cobertura': 'cupcake_cobertura',
    'topping': 'cupcake_topping',
}
CLAVE_PASO_ACTUAL = 'cupcake_paso_actual'
CLAVE_DIETAS = 'cupcake_dietas'
CLAVE_COLOR = 'cupcake_color'


def _ingrediente_de_sesion(request: HttpRequest, slug: str) -> Ingrediente | None:
    """Devuelve la selección guardada para un paso si sigue siendo válida para el usuario."""
    ingrediente_id = _entero_o_none(request.session.get(CLAVES_SESION[slug]))
    if ingrediente_id is None:
        return None

    return (
        Ingrediente.objects
        .de_categoria(CupcakePersonalizado.paso(slug).categoria)
        .filter(pk=ingrediente_id)
        .visibles_para(request.user)
        .first()
    )


def _selecciones_actuales(request: HttpRequest) -> dict[str, Ingrediente | None]:
    """Selección vigente de cada paso del asistente."""
    return {
        slug: _ingrediente_de_sesion(request, slug)
        for slug in CupcakePersonalizado.slugs_pasos()
    }


def _limpiar_asistente(request: HttpRequest) -> None:
    """Borra de la sesión todo el progreso del asistente."""
    for clave in (*CLAVES_SESION.values(), CLAVE_PASO_ACTUAL, CLAVE_DIETAS, CLAVE_COLOR):
        request.session.pop(clave, None)


def _guardar_paso(request: HttpRequest, slug: str) -> HttpResponse | None:
    """Valida y guarda la opción enviada para un paso.

    Devuelve una redirección si hay que interrumpir el flujo, o None si el
    ingrediente no es válido (la vista vuelve a mostrar el paso con el error).
    """
    ingrediente_id = _entero_o_none(request.POST.get('ingrediente'))
    ingrediente = None
    if ingrediente_id is not None:
        ingrediente = (
            Ingrediente.objects
            .de_categoria(CupcakePersonalizado.paso(slug).categoria)
            .filter(pk=ingrediente_id)
            .visibles_para(request.user)
            .first()
        )
    if ingrediente is None:
        messages.error(request, 'Selecciona una opción válida para continuar.')
        return None

    if slug == 'cobertura':
        color = request.POST.get('color_frosting', '')
        if color not in CupcakePersonalizado.COLORES_FROSTING:
            messages.error(request, 'Selecciona un color para el frosting.')
            return redirect('personalizar_paso', paso='cobertura')
        request.session[CLAVE_COLOR] = color

    request.session[CLAVES_SESION[slug]] = ingrediente.pk

    if slug == 'base':
        request.session[CLAVE_DIETAS] = CupcakePersonalizado.filtrar_dietas(
            request.POST.getlist('dietas')
        )

    request.session.modified = True

    # Desde el resumen, editar un paso devuelve al resumen.
    if request.POST.get('volver_resumen') == '1':
        return redirect('personalizar_paso', paso='resumen')

    siguiente = CupcakePersonalizado.indice_paso(slug) + 1
    request.session[CLAVE_PASO_ACTUAL] = siguiente
    pasos = CupcakePersonalizado.PASOS
    destino = pasos[siguiente].slug if siguiente < len(pasos) else 'resumen'
    return redirect('personalizar_paso', paso=destino)


def personalizar_cupcake(request: HttpRequest, paso: str = 'base') -> HttpResponse:
    """Asistente de 4 pasos + resumen. Impide saltarse pasos mediante la URL."""
    pasos = CupcakePersonalizado.PASOS
    slugs = CupcakePersonalizado.slugs_pasos()

    if paso not in (*slugs, 'resumen'):
        return redirect('personalizar_paso', paso='base')

    selecciones = _selecciones_actuales(request)
    paso_actual = request.session.get(CLAVE_PASO_ACTUAL, 0)

    if paso == 'resumen':
        if not CupcakePersonalizado.esta_completo(selecciones):
            pendiente = next(i for i, s in enumerate(slugs) if not selecciones[s])
            request.session[CLAVE_PASO_ACTUAL] = pendiente
            return redirect('personalizar_paso', paso=slugs[pendiente])
    elif CupcakePersonalizado.indice_paso(paso) > paso_actual:
        destino = slugs[paso_actual] if paso_actual < len(slugs) else 'resumen'
        return redirect('personalizar_paso', paso=destino)

    if request.method == 'POST' and paso != 'resumen':
        respuesta = _guardar_paso(request, paso)
        if respuesta is not None:
            return respuesta
        selecciones = _selecciones_actuales(request)

    contexto: dict[str, Any] = {
        'pasos': [p.as_dict() for p in pasos],
        'paso': paso,
        'selecciones': selecciones,
        'precio_base': CupcakePersonalizado.PRECIO_BASE,
        'precio_total': CupcakePersonalizado.calcular_precio(selecciones.values()),
        'dietas': CupcakePersonalizado.DIETAS,
        'dietas_elegidas': request.session.get(CLAVE_DIETAS, []),
        'colores_frosting': CupcakePersonalizado.COLORES_FROSTING,
        'color_frosting': request.session.get(CLAVE_COLOR, ''),
    }

    if paso == 'resumen':
        return render(request, 'tienda/personalizar_resumen.html', contexto)

    indice = CupcakePersonalizado.indice_paso(paso)
    definicion = pasos[indice]
    contexto.update({
        'paso_anterior': slugs[indice - 1] if indice > 0 else None,
        'definicion': definicion.as_dict(),
        'numero_paso': indice + 1,
        'total_pasos': len(pasos) + 1,
        'opciones': (
            Ingrediente.objects
            .de_categoria(definicion.categoria)
            .visibles_para(request.user)
            .order_by('nombre')
        ),
        'seleccion_actual': selecciones[paso],
        'volver_resumen': request.GET.get('volver') == 'resumen',
    })
    return render(request, 'tienda/personalizar_paso.html', contexto)


@require_POST
def agregar_cupcake_personalizado(request: HttpRequest) -> HttpResponse:
    """Agrega al carrito el cupcake armado; el precio se recalcula en el servidor."""
    selecciones = _selecciones_actuales(request)

    if not CupcakePersonalizado.esta_completo(selecciones):
        messages.error(request, 'Completa todos los pasos antes de agregar tu cupcake.')
        return redirect('personalizar_paso', paso='base')

    cupcake = {
        'tipo': 'cupcake_personalizado',
        'nombre': 'Cupcake personalizado',
        'ingredientes': {
            slug: {'id': ingrediente.pk, 'nombre': ingrediente.nombre}
            for slug, ingrediente in selecciones.items()
            if ingrediente is not None
        },
        'dietas': request.session.get(CLAVE_DIETAS, []),
        'color_frosting': request.session.get(CLAVE_COLOR, ''),
        'precio_unitario': str(CupcakePersonalizado.calcular_precio(selecciones.values())),
        'cantidad': 1,
    }

    personalizados = obtener_personalizados(request)
    personalizados.append(cupcake)
    request.session[CLAVE_PERSONALIZADOS] = personalizados
    _limpiar_asistente(request)
    request.session.modified = True

    messages.success(request, '¡Tu cupcake personalizado se agregó al carrito!')
    return redirect('ver_carrito')


# =====================================================
# 5. SUSCRIPCIONES (SWEET PLAN)
# =====================================================


def _mensaje_entrega_tarjeta(usuario: Any) -> str:
    """Texto de la entrega simulada de la tarjeta VIP tras contratar el Sweet Plan.

    Se lee la relación inversa `usuario.tarjeta` para no importar la app iot.
    """
    try:
        tarjeta = usuario.tarjeta
    except ObjectDoesNotExist:
        tarjeta = None
    if tarjeta is None:
        return 'Tu tarjeta VIP está en camino.'
    return (
        f'Tu tarjeta VIP termina en …{tarjeta.uid[-2:]}. Recíbela en tienda y '
        'úsala en el kiosco para entrar sin contraseña.'
    )


def pagina_suscripcion(request: HttpRequest) -> HttpResponse:
    """Comparativa de planes y estado de la suscripción del usuario."""
    suscripcion = Suscripcion.objects.vigente_para(request.user)
    return render(request, 'tienda/suscripcion.html', {
        'suscripcion_usuario': suscripcion,
        'plan_usuario_actual': PLAN_SWEET if suscripcion else PLAN_BASIC,
        'precio_sweet_plan': PRECIO_SWEET_PLAN,
    })


@login_required
def confirmar_suscripcion(request: HttpRequest) -> HttpResponse:
    """Confirma la contratación del Sweet Plan (pago simulado)."""
    if Suscripcion.objects.plan_de(request.user) == PLAN_SWEET:
        messages.info(request, 'Ya tienes acceso al Sweet Plan hasta la fecha indicada.')
        return redirect('suscripcion')

    if request.method == 'POST':
        Suscripcion.contratar_mes(request.user)
        messages.success(
            request,
            '¡Tu Sweet Plan está activo! Disfruta tus ingredientes exclusivos '
            'y tu descuento VIP.',
        )
        messages.info(request, _mensaje_entrega_tarjeta(request.user))
        return redirect('suscripcion')

    return render(request, 'tienda/confirmar_suscripcion.html', {
        'precio_sweet_plan': PRECIO_SWEET_PLAN,
    })


@login_required
@require_POST
def cancelar_suscripcion(request: HttpRequest) -> HttpResponse:
    """Cancela la renovación; el acceso se mantiene hasta fecha_fin."""
    suscripcion = Suscripcion.objects.activa_para(request.user)

    if suscripcion is None:
        vigente = Suscripcion.objects.vigente_para(request.user)
        if vigente and vigente.estado == Suscripcion.CANCELADA:
            messages.info(
                request,
                'Tu suscripción ya está cancelada. Conservas el acceso hasta '
                f'el {vigente.fecha_fin:%d/%m/%Y}.',
            )
        else:
            messages.warning(request, 'No tienes una suscripción activa que cancelar.')
        return redirect('suscripcion')

    suscripcion.cancelar()
    messages.success(
        request,
        'Tu Sweet Plan fue cancelado. Mantendrás el acceso hasta '
        f'el {suscripcion.fecha_fin:%d/%m/%Y}.',
    )
    return redirect('suscripcion')
