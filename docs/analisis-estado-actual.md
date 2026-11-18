# Análisis del estado actual — Bake & Made

> Fecha del análisis: 2026-11-18 · Rama: `feat/render-allocation` · Último commit analizado: `03bea44` ("Preparar despliegue en Render y aplicar reglas de ARCHITECTURE.md")

## 1. Resumen

Bake & Made es una tienda en línea de repostería (cupcakes, pasteles, galletas) hecha con **Django 6.1.1** y plantillas renderizadas en el servidor. **Está desplegada en Render** (Web Service con gunicorn y PostgreSQL administrado). El código está dividido en dos apps:

- `tienda`: catálogo con stock, carrito en la sesión, checkout con control de inventario e idempotencia, un asistente de 4 pasos para armar cupcakes personalizados y la suscripción mensual "Sweet Plan" (con pago simulado).
- `usuarios`: registro, inicio y cierre de sesión con el `User` nativo de Django.

Ya se aplicaron las reglas de [ARCHITECTURE.md](ARCHITECTURE.md): configuración por variables de entorno, la lógica de negocio en modelos y QuerySets (fat models, skinny views), type hints y docstrings. Hay **18 tests y todos pasan**.

Lo que falta de la visión de ARCHITECTURE.md:
- toda la capa IoT: la app `iot`, el endpoint `/api/rfid/scan/`, el polling en JS y el ESP32;
- una pasarela de pago real;
- llevar los cupcakes personalizados hasta el checkout.

### Fases de ARCHITECTURE.md

| Fase | Estado |
|---|---|
| 1. Planteamiento | Modelos hechos. **Pendientes:** el contrato de la API RFID, el mapeo de pines del ESP32 y el registro de UIDs VIP |
| 2. Construcción | Backend web y S3 hechos (S3 se activa por variable de entorno). **Pendientes:** la app `iot`, el polling en el frontend y el firmware del ESP32 |
| 3. Pruebas | Hay tests unitarios del checkout, las suscripciones, los ingredientes y el registro. **Pendientes:** pruebas de integración del endpoint RFID y pruebas de hardware |
| 4. Despliegue | Funciona en Render. **Pendientes:** CI/CD con GitHub Actions y la prueba de humo con RFID |

## 2. Herramientas y dependencias

| Elemento | Valor | Fuente |
|---|---|---|
| Lenguaje | Python 3.13 (Render: `PYTHON_VERSION=3.13.5`) | `Pipfile`, `render.yaml` |
| Framework | Django 6.1.1 | `requirements.txt` / `Pipfile` |
| Servidor WSGI | gunicorn ≥ 23 | `requirements.txt` |
| Estáticos | WhiteNoise ≥ 6.8 (`STATIC_ROOT = staticfiles/`) | `settings.py` |
| Base de datos | PostgreSQL en Render (`dj-database-url` + `psycopg[binary]`). En local es SQLite si `DATABASE_URL` está vacía | `settings.py` |
| Imágenes subidas | `django-storages[s3]` si `AWS_STORAGE_BUCKET_NAME` está definida. Si no, el disco local, que es efímero en Render | `settings.py` |
| Configuración | `python-dotenv` (lee `.env` en la raíz del repo) | `settings.py`, `.env.example` |
| Imágenes (`ImageField`) | Pillow ≥ 11 | `requirements.txt` |
| Gestor de dependencias | `requirements.txt` (lo usa Render) y Pipenv (desarrollo). Hoy están sincronizados | raíz del repo |
| Frontend | Plantillas Django, CSS propio, `premium.js` (vanilla) y Google Fonts | `tienda/static`, `base.html` |
| Correo | Backend de consola (`MAILERS`). **No envía correos reales** | `settings.py` |
| Idioma / zona horaria | `es-mx` / `America/Mexico_City` | `settings.py` |
| Tests | `unittest` de Django: 16 en `tienda` y 2 en `usuarios` | `*/tests.py` |
| CI/CD | Render hace el deploy desde GitHub. **No hay CI** que ejecute los tests | — |

## 3. Estructura del repositorio

```
bake-and-made/                    ← raíz del repo git
├── CLAUDE.md                     ← guía rápida para agentes
├── Pipfile / Pipfile.lock        ← dependencias de desarrollo
├── requirements.txt              ← dependencias que instala Render
├── build.sh                      ← Build Command de Render
├── render.yaml                   ← Blueprint: Web Service + PostgreSQL
├── .env.example                  ← plantilla de variables de entorno
├── .gitattributes                ← obliga a LF en *.sh
├── docs/                         ← ARCHITECTURE, este análisis y la guía de despliegue
└── bakeandmade/                  ← proyecto Django (aquí está manage.py)
    ├── manage.py
    ├── bakeandmade/
    │   ├── settings.py           ← todo se lee de variables de entorno
    │   ├── urls.py               ← admin + include(usuarios.urls) + include(tienda.urls)
    │   └── wsgi.py / asgi.py
    ├── usuarios/                 ← autenticación (sin modelos propios)
    │   ├── forms.py              ← RegistroUsuarioForm (email único)
    │   ├── views.py              ← registro
    │   ├── urls.py               ← registro, login y logout
    │   ├── templates/usuarios/   ← login.html, registro.html
    │   └── tests.py
    └── tienda/
        ├── models.py             ← modelos, QuerySets y reglas de negocio (~550 líneas)
        ├── views.py              ← vistas delgadas (~570 líneas)
        ├── carrito.py            ← claves y lectura del carrito en la sesión
        ├── context_processors.py ← contador del carrito y plan del usuario
        ├── urls.py
        ├── admin.py
        ├── templatetags/wizard_filters.py  ← filtro dict_get
        ├── management/commands/cargar_catalogo.py  ← datos iniciales (idempotente)
        ├── migrations/ 0001–0005
        ├── templates/tienda/     ← 9 plantillas
        ├── static/tienda/        ← 5 CSS y premium.js
        └── tests.py
```

Ya no están los archivos sueltos de antes (`catalogo.json`, `catalogo_respaldo.json`, `convertir.py` y `usuarios.json`).

## 4. Arquitectura

Es un **monolito Django (MVT)** en Render:

```
Navegador ──HTTPS──▶ Render ──▶ gunicorn (WEB_CONCURRENCY procesos) ──▶ Django
                                                                    │
     urls.py → usuarios.urls / tienda.urls → views (delgadas) → models / QuerySets
                                                                    │
       ├── Sesión (django_session en BD): carrito, carrito_personalizados,
       │   pasos del asistente, checkout_token, checkout_total
       ├── ORM ──▶ PostgreSQL (Render) / SQLite (local)
       ├── /static ──▶ WhiteNoise (desde el mismo proceso)
       └── /media  ──▶ S3 (si hay bucket) / disco local efímero
```

- **Build en Render (`build.sh`):** `pip install`, `collectstatic`, `migrate`, `cargar_catalogo` y, si se definen las variables `DJANGO_SUPERUSER_*`, la creación del superusuario.
- **Carrito:** vive solo en la sesión. No hay modelo `Carrito`. `tienda/carrito.py` define `CLAVE_CARRITO` y `CLAVE_PERSONALIZADOS`.
- **Autenticación:** `LoginView` y `LogoutView`. El logout es por POST.
- **Lógica de negocio** (en `tienda/models.py`):
  - `Suscripcion.objects.plan_de()`, `.vigente_para()`, `.activa_para()` y `.expirar_vencidas()`; `Suscripcion.contratar_mes()` y `.cancelar()`; `sumar_un_mes()`.
  - `Ingrediente.objects.de_categoria().visibles_para(usuario)`: los ingredientes `solo_suscriptores` solo los ve quien tiene el Sweet Plan.
  - `Menu.objects.en_venta()` y `Menu.admite_cantidad()`.
  - `Pedido.objects.lineas_validas()`, `.total_de()` y `.crear_desde_carrito()`. Este último es atómico, descuenta stock con `F()` y usa un token único. Lanza `StockInsuficiente` o `PrecioCambiado`, que heredan de `ErrorPedido`.
  - `CupcakePersonalizado.PASOS`, `.calcular_precio()` ($35 + extras), `.esta_completo()`, `.filtrar_dietas()`, `.DIETAS` y `.COLORES_FROSTING`.

### Modelo de datos

| Módulo | Modelos | ¿Se usa fuera del admin? |
|---|---|---|
| Catálogo | `CategoriaProducto`, `Menu`, `DetallesMenu` | `Menu` y `CategoriaProducto` sí. `DetallesMenu` solo en el admin |
| Ingredientes | `CategoriaIngrediente`, `Ingrediente` | Sí (en el asistente de personalización) |
| Pedidos | `Pedido`, `DetallePedido` | Sí (en el checkout) |
| Personalización | `CupcakePersonalizado`, `CupcakeIngredientes` | La clase se usa para pasos y precios, pero **no se guardan filas**: los personalizados solo viven en la sesión |
| Suscripciones | `Suscripcion` | Sí |
| Futuro | `RecordatorioEvento`, `ExperienciaQR` | **No**, solo en el admin |

## 5. Funcionalidad actual (rutas)

| Ruta | App / vista | Qué hace |
|---|---|---|
| `/` | `tienda.inicio` | Catálogo: productos `en_venta()` (disponibles y con stock) |
| `/registro/` | `usuarios.registro` | Registro con email único. Inicia sesión automáticamente |
| `/login/`, `/logout/` | `LoginView` / `LogoutView` | Autenticación |
| `/carrito/` | `ver_carrito` | Muestra productos normales y personalizados |
| `/carrito/agregar/<id>/` | `agregar_carrito` | Suma 1 unidad sin pasar del stock |
| `/carrito/actualizar/<id>/` | `actualizar_carrito` | Aumentar, disminuir o eliminar |
| `/carrito/personalizado/<i>/actualizar/` y `/eliminar/` | — | Gestiona los cupcakes personalizados de la sesión |
| `/checkout/` | `checkout` | Exige login. Token UUID (idempotencia), revisa precio y stock y crea el pedido con `crear_desde_carrito()`. **Solo procesa el carrito normal** |
| `/pedido-confirmado/<id>/` | `pedido_confirmado` | Confirmación. Solo la ve el dueño del pedido |
| `/personalizar/`, `/personalizar/<paso>/` | `personalizar_cupcake` | Asistente: base → relleno → cobertura (con color) → topping → resumen. Incluye filtro de dietas y no deja saltarse pasos |
| `/personalizar/agregar/` | `agregar_cupcake_personalizado` | Recalcula el precio en el servidor y lo agrega a `carrito_personalizados` |
| `/suscripcion/` (+ `confirmar/`, `cancelar/`) | — | Sweet Plan a $99 al mes con pago **simulado**. Al cancelar se conserva el acceso hasta `fecha_fin` |
| `/admin/` | Django admin | Catálogo, stock, ingredientes, pedidos y suscripciones |

Datos iniciales: `python manage.py cargar_catalogo` crea 13 productos, 5 categorías, 4 categorías de ingredientes y 15 ingredientes. Se puede ejecutar varias veces sin duplicar nada (`get_or_create`), y Render lo ejecuta en cada build.

### Cobertura de tests (18, todos OK)

| Clase | Qué prueba |
|---|---|
| `SumarUnMesTests` | Mes normal, fin de mes corto y cambio de año |
| `SuscripcionTests` | Plan Basic por defecto, contratar, cancelada con acceso vigente y expiración |
| `IngredientesVisiblesTests` | Los exclusivos se ocultan a Basic y se muestran a Sweet |
| `PrecioCupcakeTests` | Precio base más extras |
| `PedidoTests` | Crea el pedido y descuenta stock; rechaza si no hay stock o si cambió el precio |
| `CheckoutVistaTests` | El pedido se registra y vacía el carrito; un token reutilizado no duplica el pedido |
| `PaginasPublicasTests` | Inicio, carrito y suscripción responden |
| `RegistroTests` (`usuarios`) | El registro inicia sesión; rechaza un correo duplicado |

## 6. Hallazgos

### Resueltos (desde el análisis del 2026-11-17)

| # | Hallazgo | Cómo se resolvió |
|---|---|---|
| 1 | `SECRET_KEY` escrito en el código | Ahora se lee de una variable de entorno. Render la genera. ⚠️ La clave vieja **sigue en el historial de git**: no debe reutilizarse |
| 2 | `DEBUG` y `ALLOWED_HOSTS` fijos | Se leen de variables de entorno, y `RENDER_EXTERNAL_HOSTNAME` se agrega sola |
| 3 | No existía `STATIC_ROOT` ni WhiteNoise | `STATIC_ROOT = staticfiles/` y WhiteNoise |
| 4 | `/media` no persistía | Se usa S3 con django-storages **si se define** `AWS_STORAGE_BUCKET_NAME` |
| 5 | SQLite en producción | PostgreSQL vía `DATABASE_URL` |
| 6 | Faltaban `requirements.txt` y gunicorn | Se agregaron, junto con `build.sh` y `render.yaml` |
| 10 | Código muerto e imports duplicados en `views.py` | Eliminados |
| 12 | Archivos JSON y scripts sueltos | Borrados |
| 13 | No había tests | 18 tests, todos OK (verificado el 2026-11-18) |
| 14 | Todas las rutas en el `urls.py` del proyecto | `tienda/urls.py` y `usuarios/urls.py` con `include()` |

### Pendientes

**Bugs funcionales**
7. **El checkout ignora los cupcakes personalizados.** `checkout()` solo lee `obtener_carrito()` (`views.py:247`):
   - si el carrito solo tiene personalizados, responde "Tu carrito está vacío";
   - si tiene ambos tipos, el total del carrito no coincide con el del checkout, y los personalizados se quedan en la sesión después de comprar;
   - nunca se escriben `CupcakePersonalizado`, `CupcakeIngredientes` ni `DetallePedido.cupcake_custom`.
8. Al vender un personalizado no se descuenta `Ingrediente.stock_disponible`.
9. `cargar_catalogo` crea todos los ingredientes con `solo_suscriptores=False` (`cargar_catalogo.py:118`). El filtro ya funciona (`visibles_para`), pero el Sweet Plan no da nada exclusivo hasta que se marque algún ingrediente en el admin.

**Producción y configuración**
15. `check --deploy` falla con **`mail.E001`**: `MAILERS` usa el backend de consola. No afecta mientras nada envíe correos, pero `RecordatorioEvento` va a necesitar SMTP o un proveedor configurado por variables de entorno.
16. `SECURE_HSTS_SECONDS` vale `0` por defecto (aviso `security.W004`). Hay que subirlo cuando se confirme HTTPS estable.
17. `render.yaml` usa `plan: free` en PostgreSQL. La base gratuita de Render **expira a los 30 días**.
18. **Rama de despliegue.** Render despliega `feat/render-allocation`, pero `docs/despliegue-render.md` todavía dice `main`. Se corrige en la fase 9 de `IOT_VIP_SPEC.md`.
19. Si no se definió `AWS_STORAGE_BUCKET_NAME` en Render, las imágenes subidas desde el admin se pierden en cada deploy.
20. No hay CI: nadie ejecuta `python manage.py test` ni `check --deploy` antes de cada deploy.

**Calidad de código**
11. `Suscripcion.objects.plan_de()` lanza un `UPDATE` (`expirar_vencidas`) en cada petición de un usuario autenticado, porque lo llama el context processor. Ya está documentado en el docstring. A futuro, moverlo a un cron job.

**Funcionalidad sin implementar**
- Pasarela de pago para los pedidos y el Sweet Plan (`TODO` en `Suscripcion.contratar_mes`, `models.py:131`).
- `RecordatorioEvento` y `ExperienciaQR`: los modelos existen, pero no hay flujo.
- Historial de pedidos del cliente ("Mis pedidos") y seguimiento del estado.
- Capa IoT de ARCHITECTURE.md: la app `iot`, `/api/rfid/scan/` con token estático, las sesiones VIP, el polling en JS y el firmware del ESP32. **Capa IoT/VIP decidida: seguir [`docs/IOT_VIP_SPEC.md`](IOT_VIP_SPEC.md)**, que se implementa por fases en la rama `feat/iot-vip`.

## 7. Milestones

El siguiente trabajo es la **capa VIP/RFID**, definida en [`docs/IOT_VIP_SPEC.md`](IOT_VIP_SPEC.md) y dividida en fases (un commit por fase, con los tests en verde). Se trabaja en `feat/iot-vip` y se fusiona a `feat/render-allocation`, que es la rama que despliega Render.

| Fase | Contenido | Hallazgos que resuelve |
|---|---|---|
| 0 | Rama `feat/iot-vip` y especificación en `docs/` | — |
| 1 | Modelos: app `iot`, `PerfilVIP`, campos nuevos, admin | — |
| 2 | Entrega simulada de tarjeta, usuarios demo, ingredientes exclusivos | #9 |
| 3 | Descuentos VIP (20 %) y de cumpleaños (50 %) | — |
| 4 | API IoT, inicio de sesión por tarjeta, `/healthz` | — |
| 5 | Tienda con descuento y polling del kiosco (2 s) | #11 (en parte: un solo cálculo del plan por petición) |
| 6 | Checkout de cupcakes personalizados | #7, #8 |
| 7 | Checkout con descuento | — |
| 8 | Página `/vip/`: cumpleaños, calendario, QR con video en S3 | — |
| 9 | Despliegue en Render | #16, #18, #19 |
| 10 | Firmware ESP32 + RC522 | — |
| 11 | Prueba de humo | — |

**Fuera de alcance por ahora:** pasarela de pago real, CI (#20), backend de correo (#15), "Mis pedidos" y uso del kiosco en celular.
