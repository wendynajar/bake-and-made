# El sistema hoy: Bake & Made

> Actualizado el 2026-11-23 sobre `feat/ajustes-ui` (commit `7096078`). Producción (`feat/render-allocation`) todavía no tiene los cambios de las ramas `feat/direccion-entrega` y `feat/ajustes-ui` (ver [historial-de-cambios.md](historial-de-cambios.md#5-ajustes-posteriores)).

Este documento describe **cómo funciona el sistema ahora**. Cómo lo recibimos y qué cambió en cada etapa está en [historial-de-cambios.md](historial-de-cambios.md). Las reglas de código están en [ARCHITECTURE.md](ARCHITECTURE.md).

## 1. Resumen

Bake & Made es una tienda en línea de repostería hecha como un **monolito Django** con plantillas que se renderizan en el servidor, desplegado en Render con PostgreSQL y S3. Tiene tres apps:

| App | Responsabilidad |
|---|---|
| `tienda` | Catálogo, carrito en la sesión, asistente de cupcakes personalizados, checkout (productos y personalizados, con descuento VIP), Sweet Plan y reglas de descuento |
| `usuarios` | Registro, login y logout con el `User` nativo, `PerfilVIP` (teléfono y cumpleaños) y la página `/vip/` (cumpleaños, calendario y video QR) |
| `iot` | Tarjetas RFID, terminales de kiosco, API del lector ESP32 y sesión iniciada con tarjeta |

Además, `firmware/esp32-vip/` tiene el programa del lector (ESP32 + RC522), que se carga aparte y no forma parte del despliegue.

**Estado:** la capa VIP está completa: las fases 0 a 11 están terminadas, incluida la prueba de humo en Render (confirmada el 2026-11-23). Hay **165 tests y todos pasan** (verificado el 2026-11-23).

## 2. Herramientas y dependencias

| Elemento | Valor |
|---|---|
| Lenguaje | Python 3.13 (Render: `PYTHON_VERSION=3.13.5`) |
| Framework | Django 6.1.1 |
| Servidor WSGI | gunicorn ≥ 23 (`WEB_CONCURRENCY=2`) |
| Base de datos | PostgreSQL en Render (`dj-database-url` + `psycopg[binary]`). En local, SQLite si `DATABASE_URL` está vacía |
| Estáticos | WhiteNoise (`STATIC_ROOT = staticfiles/`) |
| Archivos subidos | `django-storages[s3]` si `AWS_STORAGE_BUCKET_NAME` tiene valor (URLs firmadas de 1 h). Si no, `bakeandmade/media/` |
| Código QR | `segno` (genera el SVG en el servidor) |
| Calendario | FullCalendar 6.1.15 por CDN |
| Imágenes (`ImageField`) | Pillow ≥ 11 |
| Configuración | `python-dotenv`: todo se lee de variables de entorno (plantilla en `.env.example`) |
| Frontend | Plantillas Django, CSS propio y JS vanilla (`premium.js`, `vip.js`, `polling.js`) |
| Firmware | PlatformIO, `espressif32@6.9.0`, `MFRC522@1.4.11` |
| Idioma y zona horaria | `es-mx` y `America/Mexico_City` |
| Dependencias | `requirements.txt` (lo usa Render) y `Pipfile` + `Pipfile.lock` (desarrollo), sincronizados |

## 3. Estructura del repositorio

```
bake-and-made/
├── README.md, CLAUDE.md
├── docs/                         ← esta documentación
├── requirements.txt, Pipfile     ← dependencias (mantenerlas sincronizadas)
├── build.sh, render.yaml         ← build y Blueprint de Render
├── .env.example, .gitattributes  ← variables de entorno; LF obligatorio en *.sh
├── firmware/esp32-vip/           ← lector RFID: src/main.cpp, cargar.ps1, cargar.sh, README
└── bakeandmade/                  ← proyecto Django (manage.py)
    ├── bakeandmade/              ← settings.py, urls.py (admin, /healthz e include de cada app)
    ├── tienda/
    │   ├── models.py             ← modelos, QuerySets y reglas de negocio
    │   ├── views.py              ← vistas delgadas
    │   ├── forms.py              ← DireccionEntregaForm
    │   ├── carrito.py            ← claves y lectura del carrito en la sesión
    │   ├── peticion.py           ← plan y descuento calculados una vez por petición
    │   ├── context_processors.py ← contador del carrito y plan
    │   ├── management/commands/cargar_catalogo.py
    │   ├── migrations/ 0001–0008
    │   ├── templates/tienda/     ← páginas + fragmentos _encabezado, _vip_nav, _campo_direccion
    │   └── static/tienda/        ← CSS y premium.js
    ├── usuarios/
    │   ├── models.py             ← PerfilVIP
    │   ├── views.py, views_vip.py← autenticación y página /vip/ con sus APIs
    │   ├── context_processors.py ← contexto VIP y de kiosco
    │   ├── management/commands/crear_usuarios_demo.py
    │   └── templates/usuarios/   ← login, registro, vip
    └── iot/
        ├── models.py             ← TarjetaRFID, Terminal, LecturaRFID
        ├── views.py              ← API del lector, estado, salir y kiosco
        ├── sesion.py             ← sincronizar(): inicia o cierra la sesión del kiosco
        ├── middleware.py         ← ActividadKioscoMiddleware
        ├── management/commands/  ← crear_terminal, registrar_tarjeta, simular_scan
        └── templates/iot/_kiosco.html, static/iot/polling.js
```

## 4. Arquitectura

```
Navegador / kiosco ──HTTPS──▶ Render ──▶ gunicorn ──▶ Django
ESP32 ──POST /api/rfid/scan/──┘                         │
          urls.py → usuarios.urls / iot.urls / tienda.urls → vistas delgadas → modelos y QuerySets
                                                         │
     ├── Sesión (en la BD): carrito, carrito_personalizados, pasos del asistente,
     │   checkout_token, terminal del kiosco
     ├── ORM ──▶ PostgreSQL (Render) / SQLite (local)
     ├── /static ──▶ WhiteNoise
     └── /media  ──▶ S3 (imágenes del catálogo y videos del QR)
```

Decisiones que conviene conocer antes de tocar el código:

- **Fat models, skinny views.** Toda regla de negocio vive en `models.py` (métodos y QuerySets). Las vistas solo leen la petición, llaman al modelo y responden.
- **Una sola fuente del descuento.** `PerfilVIP.descuento_vigente()` decide el porcentaje: 0 %, 20 % con el Sweet vigente o 50 % en su cumpleaños, salvo que haya registrado la fecha ese mismo día. `descuento_para()` y `aplicar_descuento()` en `tienda/models.py` lo aplican con `Decimal` y redondeo por línea. `tienda/peticion.py` lo calcula una vez por petición.
- **El checkout no confía en la sesión.** `Pedido.objects.lineas_validas()` y `.personalizados_validos()` vuelven a leer precio, stock, `activo` y exclusividad de la base. `crear_desde_carrito()` es atómico, descuenta stock con `F()` y usa un token único para que un doble envío no duplique el pedido.
- **Polling en lugar de WebSockets.** El kiosco consulta `/api/iot/estado/` cada 2 s (`IOT_POLL_SEGUNDOS`). El ESP32 nunca habla con el navegador.
- **Sesión del kiosco.** Cualquier inicio o cierre de sesión en un kiosco pasa por `iot.sesion.sincronizar()`, que conserva el carrito y la vinculación de la terminal. `Terminal.version` evita que un rechazo viejo cierre la sesión de quien entró después.
- **Las páginas no heredan de `base.html`.** Lo común va en fragmentos que se incluyen en todas: `tienda/_encabezado.html` (anuncio y barra, que incluye `_vip_nav.html`) e `iot/_kiosco.html` (polling y barra del kiosco). Login y registro no usan el encabezado.
- **Imágenes con respaldo.** Toda `<img>` de producto lleva un `<template>` con el logo y un `onerror` que lo muestra si el archivo no existe (por ejemplo, si aún no se sube a S3).
- **Nombres de URL sin namespace**, porque las plantillas usan `{% url 'inicio' %}`.

### Configuración de negocio (`settings.py`)

| Ajuste | Valor | Qué controla |
|---|---|---|
| `VIP_DESCUENTO` | `0.20` | Descuento del Sweet Plan vigente |
| `VIP_DESCUENTO_CUMPLE` | `0.50` | Descuento el día del cumpleaños |
| `VIP_EXPIRA_MINUTOS` | `5` | Inactividad que cierra la sesión abierta con tarjeta |
| `IOT_POLL_SEGUNDOS` | `2` | Frecuencia del polling del kiosco |
| `IOT_DEVICE_TOKEN` | variable de entorno | Token que el ESP32 manda en `Authorization: Token …` |

## 5. Modelo de datos

| App | Modelo | Para qué se usa |
|---|---|---|
| `tienda` | `CategoriaProducto`, `Menu` | Catálogo con stock e imagen |
| `tienda` | `DetallesMenu` | Receta de cada producto del catálogo: qué ingredientes lleva y cuántas porciones (`cantidad`). La llena `cargar_catalogo` y se edita en el admin. Por ahora es informativa: vender un producto del catálogo no descuenta ingredientes |
| `tienda` | `CategoriaIngrediente`, `Ingrediente` | Asistente de personalización. `solo_suscriptores` marca los exclusivos del Sweet, `activo` oculta uno y `stock_disponible` baja en cada venta |
| `tienda` | `CupcakePersonalizado`, `CupcakeIngredientes` | Se guardan al comprar, con `dietas` y `color_frosting` para la cocina. `precio_calculado` es el precio base, sin descuento |
| `tienda` | `Pedido`, `DetallePedido` | Pedido con `direccion_entrega` (texto armado desde el formulario), `descuento_porcentaje` y `motivo_descuento`. `DetallePedido.precio_unitario` ya trae el descuento |
| `tienda` | `Suscripcion` | Sweet Plan mensual. `contratar_mes()` también entrega una tarjeta RFID |
| `tienda` | `RecordatorioEvento` | Fechas del calendario VIP. Cumpleaños y aniversarios se repiten cada año. `notificado` aún no se usa porque no hay envío de correos |
| `tienda` | `ExperienciaQR` | Video del usuario en S3 con `codigo_unico` y `fecha_expiracion` |
| `usuarios` | `PerfilVIP` | Teléfono (se pide al registrarse), `fecha_nacimiento` y `cumple_registrado_en`. El cumpleaños se registra una sola vez y después solo el admin lo cambia |
| `iot` | `TarjetaRFID` | Inventario de tarjetas. El UID se normaliza (mayúsculas, sin separadores). `usuario` queda vacío mientras esté libre |
| `iot` | `Terminal` | Un kiosco (p. ej. `caja-1`): tarjeta activa, último rechazo, última actividad y `version` |
| `iot` | `LecturaRFID` | Bitácora de cada lectura y su resultado |

Hay diagramas de los ingredientes y del flujo del descuento en [diagramas.md](diagramas.md).

## 6. Rutas

| Ruta | Quién la usa | Qué hace |
|---|---|---|
| `/` | Todos | Catálogo (`Menu.objects.en_venta()`), con el precio VIP si aplica |
| `/registro/`, `/login/`, `/logout/` | Todos | Autenticación. El registro pide teléfono de 10 dígitos y lo guarda en `PerfilVIP`. El logout es por POST y, en un kiosco, conserva la vinculación |
| `/carrito/` (+ `agregar/`, `actualizar/`, `personalizado/<i>/…`) | Todos | Carrito de productos y personalizados, con el renglón de descuento VIP |
| `/personalizar/`, `/personalizar/<paso>/`, `/personalizar/agregar/` | Todos | Asistente base → relleno → cobertura → topping → resumen. El precio se recalcula en el servidor |
| `/checkout/` | Con sesión | Dirección por campos (`DireccionEntregaForm`), validación en el servidor y pedido con descuento |
| `/pedido-confirmado/<id>/` | Dueño del pedido | Confirmación con el desglose del descuento |
| `/suscripcion/` (+ `confirmar/`, `cancelar/`) | Con sesión | Sweet Plan con pago simulado. Al cancelar se conserva el acceso hasta `fecha_fin` |
| `/vip/` | Sweet vigente | Resumen de la membresía, tarjeta de cumpleaños (día, mes y días que faltan), QR del video y calendario |
| `/api/vip/fechas/` (GET, POST), `/api/vip/fechas/<id>/` (DELETE) | Sweet vigente | Fechas del calendario. Cada usuario solo ve las suyas |
| `/api/vip/cumpleanios/` (POST) | Sweet vigente | Registro único del cumpleaños (409 si ya existe, 400 si la fecha es inválida) |
| `/vip/v/<codigo>/` | Pública (el QR) | Redirige (302) a la URL firmada del video en S3, o 404 si expiró |
| `/api/rfid/scan/` (POST) | ESP32 | Con token: 200 ok, 403 sin Sweet, 404 tarjeta desconocida, 401 token malo y 400 terminal desconocida |
| `/api/iot/estado/` (GET) | Kiosco, cada 2 s | Aplica la expiración por inactividad y sincroniza la sesión con la terminal |
| `/api/iot/salir/` (POST) | Botón "Salir" del kiosco | Cierra en el acto la sesión abierta con tarjeta |
| `/kiosco/<codigo>/` | Staff | Vincula este navegador con la terminal y cierra la sesión del staff |
| `/healthz` | Render y ESP32 | Responde `ok` sin tocar la base de datos |
| `/admin/` | Admin | Catálogo, pedidos, suscripciones, tarjetas, terminales, perfiles VIP y videos |

## 7. Comandos de gestión

| Comando | App | Qué hace |
|---|---|---|
| `cargar_catalogo` | `tienda` | Crea las categorías, productos e ingredientes que falten sin modificar los existentes. Las únicas excepciones: completa la imagen (`IMAGENES`, en `media/productos/`) y la receta (`RECETAS`, tabla `DetallesMenu`) de un producto que no tenga. Render lo corre en cada build |
| `crear_terminal <codigo>` | `iot` | Crea una terminal de kiosco (`build.sh` crea `caja-1`) |
| `registrar_tarjeta <uid>` | `iot` | Agrega una tarjeta libre al inventario |
| `simular_scan <uid> --terminal caja-1` | `iot` | Simula una lectura del ESP32, para probar sin hardware |
| `crear_usuarios_demo` | `usuarios` | Crea a Ana, Bruno y Carla con Sweet vigente y tarjeta. Requiere `DEMO_PASSWORD` y `--uids` o `DEMO_VIP_UIDS`. Como `build.sh` lo corre en cada deploy, **cada deploy restablece** su contraseña (`DEMO_PASSWORD`), nombre y teléfono, y les vuelve a contratar el Sweet si venció |

## 8. Tests

165 tests con `unittest` de Django (`python manage.py test`), todos en verde:

| App | Clases |
|---|---|
| `tienda` (80) | `SumarUnMesTests`, `SuscripcionTests`, `IngredientesVisiblesTests`, `PrecioCupcakeTests`, `PedidoTests`, `CheckoutVistaTests`, `DireccionEntregaFormTests`, `DireccionCheckoutVistaTests`, `CheckoutPersonalizadosTests`, `CheckoutVIPTests`, `PaginasPublicasTests`, `CamposVIPTests`, `IngredientesExclusivosTests`, `ImagenesCatalogoTests`, `RecetasCatalogoTests`, `EncabezadoComunTests`, `ImagenFaltanteTests`, `DescuentoVIPTests`, `AplicarDescuentoTests`, `TiendaVIPTests`, `KioscoPlantillaTests`, `EntregaTarjetaMensajeTests` |
| `usuarios` (44) | `RegistroTests`, `PerfilVIPTests`, `UsuariosDemoTests`, `CumpleaniosTests`, `DiasParaCumpleaniosTests`, `FechasVIPTests`, `CumpleaniosAPITests`, `VideoQRTests`, `PaginaVIPTests` |
| `iot` (41) | `NormalizarUidTests`, `TarjetasLibresTests`, `ComandosIotTests`, `EntregaTarjetaTests`, `ScanAPITests`, `LoginTarjetaTests`, `KioscoTests`, `HealthzTests`, `SimularScanTests` |

No hay CI: los tests se corren a mano antes de fusionar a `feat/render-allocation`.

## 9. Pendientes

Los números son los del análisis original, para poder rastrearlos en [historial-de-cambios.md](historial-de-cambios.md).

**Producción y configuración**
- **Integrar ramas:** `feat/direccion-entrega` y `feat/ajustes-ui` aún no se fusionan a `feat/render-allocation`.
- **Imágenes del catálogo en S3:** `cargar_catalogo` apunta a `media/productos/*.jpg`. Mientras no estén en el bucket, la tienda muestra el logo en su lugar.
- **#15** No hay envío de correos: `MAILERS` usa el backend de consola (`check --deploy` avisa `mail.E001`). Lo necesitarían los recordatorios del calendario.
- **#16** `SECURE_HSTS_SECONDS` vale `0` por defecto (aviso `security.W004`). Ya se configura por variable de entorno; falta subirlo.
- **#17** El PostgreSQL gratuito de Render vence a los 30 días. Si se recrea, se pierden pedidos, cumpleaños y fechas (los usuarios demo se recrean en el build).
- **#20** No hay CI que corra `test` y `check --deploy` antes de cada deploy.
- Si las claves de AWS en Render son inválidas, guardar una `ExperienciaQR` en el admin da un error 500 en lugar de un mensaje claro (visto en la fase 11).

**Calidad de código**
- **#11** `Suscripcion.objects.plan_de()` hace un `UPDATE` (`expirar_vencidas`) en cada petición de un usuario autenticado. Ya se calcula una sola vez por petición (`tienda/peticion.py`); a futuro conviene moverlo a un cron.

**Funcionalidad sin implementar (fuera de alcance por ahora)**
- Pasarela de pago real para pedidos y Sweet Plan (`TODO` en `Suscripcion.contratar_mes`).
- Historial "Mis pedidos" y seguimiento del estado del pedido.
- Avisos por correo de las fechas del calendario (`RecordatorioEvento.notificado`).
- Uso del kiosco desde el celular.

**Riesgos conocidos** (detalle en [IOT_VIP_SPEC.md](IOT_VIP_SPEC.md#riesgos-conocidos)): el UID de una MIFARE Classic se puede clonar, los videos grandes subidos por el admin pueden agotar la instancia gratuita y el ESP32 solo funciona con Wi-Fi de 2.4 GHz.
