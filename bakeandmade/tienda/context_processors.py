def contador_carrito(request):
    carrito = request.session.get('carrito', {})

    total_productos = sum(
        int(cantidad)
        for cantidad in carrito.values()
    )

    return {
        'contador_carrito': total_productos
    }
