# Historial de cambios: de cómo lo recibimos a hoy

Este documento cuenta **en qué estado recibimos el proyecto, qué cambiamos y por qué**, etapa por etapa. Cómo funciona el sistema hoy está en [sistema-actual.md](sistema-actual.md), y el detalle técnico de la capa VIP en [IOT_VIP_SPEC.md](IOT_VIP_SPEC.md).

| Etapa | Fechas | Commits |
|---|---|---|
| 0. Proyecto recibido | 2026-09-09 a 2026-10-25 | `22c62d5` … `a400a83` |
| 1. Preparación para Render y reglas de ARCHITECTURE.md | 2026-11-17 | `03bea44` |
| 2. Capa VIP/RFID (fases 0 a 11) | 2026-11-18 a 2026-11-22 | `dd6b046` … `d764f28` (PR #2, #4, #5 y #6) |
| 3. Integración con `main` y dirección de entrega | 2026-11-22 | `413b025`, `dc38658`, `78a674f` |
| 4. Ajustes de interfaz | 2026-11-22 | `f0fce33` … `7096078` |

## 1. Cómo recibimos el proyecto

El punto de partida es el commit `a400a83` (2026-10-25, "Añadido planes de suscripción y personalización de cupcake"). Antes de él, el proyecto se creó (`889506c`), se agregaron los modelos de la base de datos (`aa833aa`) y se integró la tienda completa (`3d16513`).

**Qué funcionaba:**
- catálogo con stock, carrito en la sesión y checkout con control de inventario y un token para no duplicar pedidos;
- asistente de 4 pasos para armar cupcakes personalizados, con filtro de dietas;
- Sweet Plan mensual con pago simulado (`tienda/suscripciones.py`);
- registro, login y logout (las plantillas vivían en `tienda`);
- un diseño propio en CSS (`premium.css`, `carrito-premium.css`, `checkout-premium.css`).

**Cómo estaba organizado:**
- Una sola app, `tienda`. `views.py` tenía unas **1 070 líneas** con casi toda la lógica, y `models.py` (171 líneas) solo definía campos.
- Las rutas estaban todas en el `urls.py` del proyecto.
- Los modelos `RecordatorioEvento` y `ExperienciaQR` ya existían, pero nada los usaba.

**Problemas que encontramos** (numerados como en el análisis del 2026-11-17; su estado actual está en la [sección 6](#6-hallazgos-del-análisis-original-y-su-estado)):

| # | Problema |
|---|---|
| 1 | `SECRET_KEY` escrito en `settings.py` y subido a git |
| 2 | `DEBUG = True` y `ALLOWED_HOSTS = []` fijos en el código |
| 3 | No había `STATIC_ROOT` ni WhiteNoise: `collectstatic` fallaba y sin `DEBUG` no había estilos |
| 4 | Las imágenes subidas no se servían en producción, y el disco de Render es efímero |
| 5 | SQLite, sin `dj-database-url` ni `psycopg` |
| 6 | No había `requirements.txt` ni gunicorn |
| 7 | **El checkout ignoraba los cupcakes personalizados**: si el carrito solo tenía personalizados decía "Tu carrito está vacío", el total no coincidía con el del carrito y nunca se guardaban |
| 8 | Vender un personalizado no descontaba el stock de sus ingredientes |
| 9 | Ningún ingrediente era exclusivo del Sweet Plan, así que la suscripción no desbloqueaba nada |
| 10 | Código muerto e imports duplicados en `views.py` |
| 11 | La expiración de suscripciones hacía un `UPDATE` en cada petición (desde el context processor) |
| 12 | Archivos sueltos sin uso: `catalogo.json` (vacío), `catalogo_respaldo.json` (codificación dañada), `convertir.py` y `usuarios.json` |
| 13 | No había tests (`tests.py` estaba vacío) |
| 14 | Todas las rutas en el `urls.py` del proyecto |

## 2. Antes y ahora

| Aspecto | Como lo recibimos | Hoy |
|---|---|---|
| Apps | `tienda` | `tienda`, `usuarios` e `iot`, más el firmware del ESP32 |
| Lógica de negocio | En las vistas | En modelos y QuerySets; las vistas son delgadas |
| Configuración | Escrita en `settings.py` | Variables de entorno (`.env` en local, panel de Render en producción) |
| Base de datos | SQLite | PostgreSQL en Render y SQLite en local |
| Archivos subidos | Disco local | AWS S3 con URLs firmadas |
| Despliegue | Ninguno | Render (Blueprint `render.yaml`, `build.sh`, `/healthz`) |
| Checkout | Solo productos | Productos y personalizados, revalidados en el servidor, con descuento VIP y dirección por campos |
| Sweet Plan | Pago simulado, sin beneficios reales | 20 % de descuento (50 % en el cumpleaños), ingredientes exclusivos, página `/vip/` y tarjeta RFID |
| Tienda física | No existía | Kiosco con inicio de sesión por tarjeta (ESP32 + RC522) |
| Tests | 0 | 157, todos en verde |
| Documentación | Ninguna | README, CLAUDE.md y `docs/` |

## 3. Preparación para Render (`03bea44`, 2026-11-17)

**Objetivo:** que el proyecto se pudiera desplegar con seguridad y que cumpliera las reglas de [ARCHITECTURE.md](ARCHITECTURE.md) antes de construir encima.

| Cambio | Por qué |
|---|---|
| `settings.py` lee todo de variables de entorno (`python-dotenv`) y se agregó `.env.example` | Sacar credenciales del código (#1, #2). La `SECRET_KEY` vieja sigue en el historial de git y **no debe reutilizarse** |
| PostgreSQL vía `DATABASE_URL`, WhiteNoise y S3 opcional con `django-storages` | Requisitos de Render (#3, #4, #5) |
| `requirements.txt`, gunicorn, `build.sh` y `render.yaml` | Build y arranque en Render (#6) |
| Nueva app `usuarios` (registro, login, logout) y un `urls.py` por app | Separar responsabilidades (#14) |
| La lógica pasó a modelos y QuerySets (`Suscripcion.objects.plan_de()`, `Pedido.objects.crear_desde_carrito()`, etc.); `suscripciones.py` se integró en `models.py` | Regla "fat models, skinny views" |
| Type hints y docstrings en todo el código | Regla de ARCHITECTURE.md |
| Se borraron el código muerto y los archivos sueltos | #10, #12 |
| 18 tests: suscripciones, ingredientes, precios, pedidos, checkout y registro | #13 |
| `docs/` con el análisis y la guía de despliegue | Dejar registro del estado y de cómo desplegar |

## 4. Capa VIP/RFID (2026-11-18 a 2026-11-22)

**Objetivo:** que el Sweet Plan diera beneficios reales y conectar la tienda física con la web. Se diseñó primero en [IOT_VIP_SPEC.md](IOT_VIP_SPEC.md) y se construyó **una fase a la vez** en la rama `feat/iot-vip`. Cada fase terminó con los tests en verde y un commit, y se fusionó a `feat/render-allocation` (la rama de producción) con PR.

| Fase | Commit | Qué se agregó | Notas y decisiones |
|---|---|---|---|
| 0 | `dd6b046` | La especificación y el análisis actualizado | VIP y Sweet Plan son lo mismo. La tarjeta es la llave del kiosco |
| 1 | `59be3db` | App `iot` (`TarjetaRFID`, `Terminal`, `LecturaRFID`), `PerfilVIP` y campos nuevos en `RecordatorioEvento`, `ExperienciaQR` y `Pedido` | `url_video` quedó como archivo (`ExperienciaQR.video`) en S3 |
| 2 | `fc46c64` | Entrega simulada de la tarjeta al contratar el Sweet, comando `crear_usuarios_demo` e ingredientes exclusivos | Resuelve #9: Red velvet, Dulce de leche, Queso crema y Fresas son exclusivos (migración `tienda.0007` para bases existentes) |
| 3 | `5e3b247` | Descuentos: 20 % con Sweet vigente y 50 % en el cumpleaños | `PerfilVIP.descuento_vigente()` es la única fuente de la regla. El cumpleaños se registra una sola vez y no cuenta si se registra ese mismo día |
| 4 | `f1cba2b` | API del lector (`/api/rfid/scan/`), `/healthz`, `/kiosco/<codigo>/`, `/api/iot/estado/`, `/api/iot/salir/`, `iot.sesion.sincronizar()` y `simular_scan` | El ESP32 solo avisa; el kiosco pregunta. `Terminal.version` evita que un rechazo viejo saque a quien entró después |
| 5 | `dd09da7`, `4b5fcf1` | Precios con descuento en la tienda y el carrito, pestaña "VIP" y `polling.js` | Como las páginas no heredan de `base.html`, lo común va en fragmentos (`_vip_nav.html`, `_kiosco.html`). Polling cada 2 s para cumplir el criterio de 4 s. #11 en parte: el plan se calcula una vez por petición |
| 6 | `e73c735` | Checkout de cupcakes personalizados | Resuelve #7 y #8. Los ingredientes de la sesión se vuelven a validar en el servidor y su stock se descuenta. Se guardan `dietas` y `color_frosting` (migración `tienda.0008`) |
| 7 | `734e150` | Checkout con descuento | Redondeo por línea. El pedido guarda `descuento_porcentaje` y `motivo_descuento`, y `DetallePedido.precio_unitario` ya trae el descuento |
| 8 | `5581c5c` | Página `/vip/`: cumpleaños con aviso, calendario (FullCalendar) y QR con el video en S3 (`segno`) | Las vistas viven en `usuarios/views_vip.py`. Cada usuario solo ve sus fechas |
| 9 | `15416ec`, `29cc4ae` | Despliegue de la capa VIP en https://bake-and-made.onrender.com | `IOT_DEVICE_TOKEN` y `crear_terminal` en el build, Health Check `/healthz`. Verificado con `curl`. Resuelve #18 y #19 |
| 10 | `2d4cecc`, `a4ab75e` | Firmware del ESP32 + RC522 y scripts `cargar.ps1` y `cargar.sh` | Verificado con hardware: tarjeta → ESP32 → Render → sesión iniciada en el kiosco. Los UID demo se registran en Render con un deploy, no con el comando local |
| 11 | `d764f28` | Prueba de humo en Render y `docs/diagramas.md` | 21 de 21 pruebas automáticas contra Render y casi todas las manuales. Un 500 al guardar videos era por claves de AWS inválidas en Render. **Faltan 3 pruebas manuales** (ver [sistema-actual.md](sistema-actual.md#9-pendientes)) |

## 5. Ajustes posteriores

Estos cambios están en `feat/direccion-entrega` y `feat/ajustes-ui`. **Todavía no están en producción** (`feat/render-allocation`).

### Integración con `main` y dirección de entrega (2026-11-22)

En `main` había un commit (`413b025`, "Actualiza checkout y catalogo") hecho sobre la versión anterior a la refactorización. Pedía la dirección de entrega por campos y asignaba imágenes a los productos del catálogo. No se podía fusionar tal cual, así que:

| Commit | Qué se hizo | Por qué |
|---|---|---|
| `dc38658` | Merge de `main`: se conservaron las `IMAGENES` de `cargar_catalogo`, pero solo se asignan al crear un producto o si no tiene imagen | Para no pisar en cada deploy lo que se cambie en el admin. El checkout y el `Pipfile` se quedaron como en producción (Python 3.13) |
| `78a674f` | `DireccionEntregaForm` en `tienda/forms.py`: calle, números, colonia, CP de 5 dígitos, ciudad, estado y referencias. `.como_texto()` arma la dirección en formato postal mexicano | Reimplementa la idea de `413b025` sobre el checkout actual. Se guarda en `Pedido.direccion_entrega`, así que no hizo falta migración |

### Interfaz (2026-11-22)

| Commit | Qué se hizo |
|---|---|
| `f0fce33` | **Encabezado común** `tienda/_encabezado.html`, con el diseño de "Mi carrito", en todas las páginas de la tienda y en `/vip/`. **Logo de respaldo** cuando falta la imagen de un producto. En `/vip/`: QR centrado (el QR es el enlace) y tarjeta de cumpleaños con el día, el mes y los días que faltan (`PerfilVIP.dias_para_cumpleanios()`) |
| `ae63039` | `CLAUDE.md` documenta el encabezado común y el respaldo de imágenes |
| `5816290`, `7096078` | `/vip/` más limpia: el título es solo el nombre, se quitó el estado de la tarjeta RFID del resumen y el tamaño del mes se ajusta a su largo. Se centró el título "Mi video" |

## 6. Hallazgos del análisis original y su estado

| # | Hallazgo | Estado |
|---|---|---|
| 1 | `SECRET_KEY` en el código | ✅ Variable de entorno (etapa 1). La clave vieja quedó en el historial: no reutilizarla |
| 2 | `DEBUG` y `ALLOWED_HOSTS` fijos | ✅ Variables de entorno (etapa 1) |
| 3 | Sin `STATIC_ROOT` ni WhiteNoise | ✅ Etapa 1 |
| 4 | `/media` no persistía | ✅ S3 (etapa 1, configurado en la fase 9) |
| 5 | SQLite en producción | ✅ PostgreSQL (etapa 1) |
| 6 | Sin `requirements.txt` ni gunicorn | ✅ Etapa 1 |
| 7 | El checkout ignoraba los personalizados | ✅ Fase 6 |
| 8 | No se descontaba el stock de ingredientes | ✅ Fase 6 |
| 9 | Ningún ingrediente exclusivo | ✅ Fase 2 |
| 10 | Código muerto | ✅ Etapa 1 |
| 11 | `UPDATE` de suscripciones en cada petición | 🟡 Se calcula una vez por petición (fase 5); falta moverlo a un cron |
| 12 | Archivos sueltos | ✅ Etapa 1 |
| 13 | Sin tests | ✅ 18 en la etapa 1, 157 hoy |
| 14 | Rutas en un solo archivo | ✅ Etapa 1 |
| 15 | Correo con backend de consola | ⏳ Pendiente |
| 16 | HSTS en 0 | 🟡 Configurable por variable de entorno; falta subirlo |
| 17 | PostgreSQL gratuito vence a los 30 días | ⏳ Pendiente |
| 18 | La guía de despliegue decía `main` | ✅ Fase 9 |
| 19 | Imágenes perdidas sin bucket | ✅ Fase 9 |
| 20 | Sin CI | ⏳ Pendiente |
| 21 | `Pipfile.lock` desactualizado | ⏳ Pendiente |

Los hallazgos 15 a 21 se detectaron después de la etapa 1, ya con el proyecto en Render.
