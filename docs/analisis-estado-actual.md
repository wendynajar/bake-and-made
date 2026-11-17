# Análisis del estado actual — Bake & Made

> Fecha del análisis: 2026-11-17 · Último commit analizado: `a400a83` ("Añadido planes de suscripción y personalización de cupcake")

## 1. Resumen

Bake & Made es una tienda en línea de repostería (cupcakes, pasteles, galletas) hecha con **Django 6.1.1** y renderizado del lado del servidor (plantillas Django, sin frontend SPA). Hay una sola app de negocio, `tienda`, que incluye:

- catálogo de productos con stock,
- carrito guardado en la sesión,
- registro, inicio y cierre de sesión,
- checkout con control de inventario e idempotencia,
- asistente de 4 pasos para armar un cupcake personalizado,
- suscripción mensual "Sweet Plan" (el pago es simulado),
- panel de administración de Django para gestionar todo.

El proyecto **funciona en local pero aún no está listo para producción**. Usa SQLite, tiene el `SECRET_KEY` escrito en el código, `DEBUG=True`, le falta `STATIC_ROOT` y no tiene servidor WSGI de producción. Las secciones 6 y 7 lo detallan.

## 2. Herramientas y dependencias

| Elemento | Valor | Fuente |
|---|---|---|
| Lenguaje | Python 3.13 | `Pipfile` (`python_version = "3.13"`) |
| Framework | Django 6.1.1 | `Pipfile.lock` |
| Imágenes | Pillow (requerido por `ImageField`) | `Pipfile` |
| Otras (transitivas) | asgiref 3.12.1, sqlparse 0.6.0, tzdata | `Pipfile.lock` |
| Gestor de dependencias | **Pipenv** (`Pipfile` + `Pipfile.lock`) | raíz del repo |
| Base de datos | SQLite (`db.sqlite3`, ignorado en git) | `settings.py` |
| Frontend | HTML de plantillas Django + CSS propio + `premium.js` (vanilla) + Google Fonts | `tienda/static`, `base.html` |
| Correo | Backend de consola (`MAILERS`) | `settings.py` |
| Idioma / zona horaria | `es-mx` / `America/Mexico_City` | `settings.py` |
| Tests | No hay (`tienda/tests.py` está vacío) | — |
| CI/CD | No hay | — |

**Faltan para producción:** `gunicorn`, `whitenoise`, `dj-database-url` y `psycopg` (driver de PostgreSQL). Tampoco hay `requirements.txt`.

## 3. Estructura del repositorio

```
bake-and-made/                  ← raíz del repo git
├── Pipfile / Pipfile.lock      ← dependencias (Pipenv)
├── .gitignore
├── .vscode/settings.json
└── bakeandmade/                ← proyecto Django (aquí vive manage.py)
    ├── manage.py
    ├── bakeandmade/            ← paquete de configuración
    │   ├── settings.py
    │   ├── urls.py             ← TODAS las rutas están aquí (la app no tiene urls.py)
    │   ├── wsgi.py / asgi.py
    ├── tienda/                 ← app de negocio
    │   ├── models.py           ← 12 modelos
    │   ├── views.py            ← ~1070 líneas, vistas basadas en funciones
    │   ├── suscripciones.py    ← reglas de negocio del Sweet Plan
    │   ├── context_processors.py ← contador del carrito + plan del usuario
    │   ├── forms.py            ← RegistroUsuarioForm
    │   ├── admin.py
    │   ├── templatetags/wizard_filters.py ← filtro dict_get
    │   ├── management/commands/cargar_catalogo.py ← datos iniciales (seed)
    │   ├── migrations/ 0001–0005
    │   ├── templates/tienda/*.html (12 plantillas)
    │   └── static/tienda/*.css, premium.js
    ├── catalogo.json           ← vacío ("[ ]")
    ├── catalogo_respaldo.json  ← fixture con acentos dañados (cp1252)
    ├── convertir.py            ← script suelto para convertir cp1252 → UTF-8
    └── usuarios.json           ← vacío
```

## 4. Arquitectura

Es un **monolito Django clásico (MVT)**:

```
Navegador ──HTTP──▶ Django (urls.py → views.py)
                        │
                        ├── Sesión (django_session en BD): carrito, carrito_personalizados,
                        │   pasos del asistente, checkout_token
                        ├── ORM ──▶ SQLite (hoy) / PostgreSQL (objetivo)
                        ├── Plantillas (templates/tienda) + context processor
                        └── Archivos: /static (CSS/JS) y /media (imágenes subidas en el admin)
```

- **Estado del carrito:** se guarda solo en la sesión (`request.session`), que vive en la base de datos (backend de sesiones por defecto). No hay modelo `Carrito`.
- **Autenticación:** usa el `User` nativo de Django. El login y el logout usan `LoginView` y `LogoutView` (el logout es por POST, como exige Django 5+).
- **Lógica de negocio:** casi toda está en `views.py`. Solo las suscripciones están en un módulo aparte (`suscripciones.py`).
- **Imágenes:** `Menu.imagen` e `Ingrediente.imagen` se guardan en `MEDIA_ROOT` (disco local). Solo se sirven si `DEBUG=True`.

### Modelo de datos

| Módulo | Modelos | ¿Se usa en las vistas? |
|---|---|---|
| Catálogo | `CategoriaProducto`, `Menu`, `DetallesMenu` | `Menu` y `CategoriaProducto` sí. `DetallesMenu` solo en el admin |
| Ingredientes | `CategoriaIngrediente`, `Ingrediente` | Sí (asistente de personalización) |
| Pedidos | `Pedido`, `DetallePedido` | Sí (checkout) |
| Personalización | `CupcakePersonalizado`, `CupcakeIngredientes` | **No.** Los cupcakes personalizados solo viven en la sesión |
| Suscripciones | `Suscripcion` | Sí |
| Futuro | `RecordatorioEvento`, `ExperienciaQR` | **No**, solo en el admin |

## 5. Funcionalidad actual (rutas)

| Ruta | Vista | Qué hace |
|---|---|---|
| `/` | `inicio` | Muestra el catálogo (productos disponibles con stock > 0) |
| `/registro/` | `registro` | Registro con email único, inicia sesión automáticamente |
| `/login/`, `/logout/` | `LoginView` / `LogoutView` | Autenticación |
| `/carrito/` | `ver_carrito` | Muestra productos normales y personalizados |
| `/carrito/agregar/<id>/` | `agregar_carrito` | Suma 1 unidad sin pasar del stock |
| `/carrito/actualizar/<id>/` | `actualizar_carrito` | Aumentar, disminuir o eliminar |
| `/carrito/personalizado/<i>/actualizar|eliminar/` | — | Gestiona los cupcakes personalizados que están en la sesión |
| `/checkout/` | `checkout` | Exige login. Usa token UUID (idempotencia), revisa precio y stock, descuenta stock con `F()` dentro de una transacción |
| `/pedido-confirmado/<id>/` | `pedido_confirmado` | Confirmación (solo la ve el dueño del pedido) |
| `/personalizar/`, `/personalizar/<paso>/` | `personalizar_cupcake` | Asistente base → relleno → cobertura (con color) → topping → resumen. Incluye dietas y bloquea saltarse pasos |
| `/personalizar/agregar/` | `agregar_cupcake_personalizado` | El precio se recalcula en el servidor ($35 + extras) |
| `/suscripcion/` (+ `confirmar/`, `cancelar/`) | — | Sweet Plan a $99 al mes, con pago **simulado**. Al cancelar se conserva el acceso hasta `fecha_fin` |
| `/admin/` | Django admin | Gestión del catálogo, el stock, los pedidos y las suscripciones |

Datos iniciales: `python manage.py cargar_catalogo` crea 13 productos, 5 categorías, 4 categorías de ingredientes y 15 ingredientes. Se puede ejecutar varias veces sin duplicar nada (usa `get_or_create`).

## 6. Hallazgos (bugs y deuda técnica)

> **Actualización 2026-11-17, después de aplicar docs/ARCHITECTURE.md:**
> - Resueltos: #1 a #3, #5, #6, #10, #12 y #14 (configuración por variables de entorno, WhiteNoise, PostgreSQL, gunicorn, `requirements.txt` y `build.sh`, código muerto eliminado, archivos sueltos borrados, rutas por app).
> - #4 queda resuelto si se configura `AWS_STORAGE_BUCKET_NAME` (django-storages con S3).
> - #13: se agregaron tests en `tienda/tests.py` y `usuarios/tests.py`, pero **aún no se han ejecutado**.
> - Pendientes: #7, #8, #9 y #11.
> - La lógica de negocio se movió a `tienda/models.py` (QuerySets y métodos) y se creó la app `usuarios`. Las secciones 2 a 5 describen el estado **anterior** a este cambio; el mapa actual está en `CLAUDE.md`.

### Bloqueantes para producción
1. **`SECRET_KEY` escrito en el código y subido a git.** Hay que sacarlo a una variable de entorno y **rotarlo**, porque ya es público en el historial.
2. **`DEBUG = True` y `ALLOWED_HOSTS = []`**, ambos fijos en el código.
3. **No existe `STATIC_ROOT`**, así que `collectstatic` falla. Tampoco hay WhiteNoise para servir los estáticos con gunicorn.
4. **Las imágenes subidas (`/media`) no se sirven con `DEBUG=False`** (ver `urls.py`). Además, en Render el disco es **efímero**: lo que se sube por el admin se pierde en cada deploy o reinicio. Opciones: un Persistent Disk de Render (planes de pago) o almacenamiento externo (Cloudinary, S3 o R2 con `django-storages`).
5. SQLite en lugar de PostgreSQL, y no está instalado `dj-database-url` ni `psycopg`.
6. No hay `requirements.txt` ni `gunicorn`.

### Bugs funcionales
7. **El checkout ignora los cupcakes personalizados.** `checkout()` solo lee `session['carrito']`:
   - si el carrito solo tiene personalizados, responde "Tu carrito está vacío";
   - si tiene ambos tipos, el total del carrito (que sí incluye los personalizados) **no coincide** con el del checkout, y los personalizados se quedan en la sesión después de comprar;
   - los modelos `CupcakePersonalizado` y `CupcakeIngredientes` nunca se escriben. Tampoco `DetallePedido.cupcake_custom`.
8. No se descuenta el stock de los ingredientes (`Ingrediente.stock_disponible`) al vender un personalizado.
9. `cargar_catalogo` crea todos los ingredientes con `solo_suscriptores=False`, así que el Sweet Plan no da acceso a nada exclusivo hasta que alguien lo configure en el admin.

### Calidad de código
10. Código muerto en `views.py`: `iniciar_sesion`, `cerrar_sesion`, `personalizar` y `obtener_cantidad_carrito` (este último duplica el context processor). También hay imports repetidos (`login_required`, `require_POST`).
11. `suscripcion_vigente()` lanza un `UPDATE` en **cada request** porque se llama desde el context processor. Funciona, pero conviene moverlo a una tarea programada (cron job) o hacerlo de forma perezosa.
12. Archivos sueltos sin uso: `catalogo.json` (vacío), `catalogo_respaldo.json` (codificación dañada), `convertir.py` y `usuarios.json`. Se recomienda borrarlos o moverlos a `fixtures/`.
13. No hay tests. Lo más sensible y que debería probarse primero es el checkout (inventario y token) y las suscripciones.
14. Todas las rutas están en el `urls.py` del proyecto. Conviene pasarlas a `tienda/urls.py` con `include()`.

## 7. Próximos pasos sugeridos (hoja de ruta)

1. **Preparar el despliegue** (ver [despliegue-render.md](despliegue-render.md)): configuración por variables de entorno, PostgreSQL, WhiteNoise, gunicorn, `requirements.txt` y `build.sh`.
2. **Almacenamiento de imágenes** externo (Cloudinary o S3) para `/media`.
3. **Llevar los cupcakes personalizados hasta el checkout**: crear `CupcakePersonalizado` + `DetallePedido.cupcake_custom` y validar en el servidor las selecciones de ingredientes.
4. **Pasarela de pago** (Stripe o Mercado Pago) para los pedidos y el Sweet Plan. Está marcado como `TODO` en `confirmar_suscripcion`.
5. Implementar `RecordatorioEvento` (requiere un backend de correo real y un cron job de Render) y `ExperienciaQR`.
6. Historial de pedidos del cliente ("Mis pedidos") y seguimiento del estado.
7. Tests y CI (GitHub Actions: `python manage.py test` + `check --deploy`).
