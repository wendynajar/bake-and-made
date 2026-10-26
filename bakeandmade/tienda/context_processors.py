from .suscripciones import PRECIO_SWEET_PLAN, plan_actual


def contador_carrito(request):
    carrito = request.session.get('carrito', {})
    personalizados = request.session.get('carrito_personalizados', [])

    total_normales = sum(
        cantidad
        for cantidad in carrito.values()
        if type(cantidad) is int and cantidad > 0
    )

    total_personalizados = sum(
        cupcake.get('cantidad', 1)
        for cupcake in personalizados
        if type(cupcake.get('cantidad', 1)) is int
        and cupcake.get('cantidad', 1) > 0
    )

    plan = plan_actual(request.user)

    return {
        'contador_carrito': total_normales + total_personalizados,
        'plan_usuario': plan,
        'es_plan_sweet': plan == 'sweet',
        'precio_sweet_plan': PRECIO_SWEET_PLAN,
    }
