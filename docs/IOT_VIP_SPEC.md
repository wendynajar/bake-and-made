# Especificación técnica — Bake & Made VIP (RFID)

Nov 18, 2026 · @sopadepollo7

## Resumen y alcance

La capa VIP se agrega al repo existente de Bake & Made (Django 6.1.1 en Render, rama `feat/render-allocation`) como una app nueva `iot` más un perfil VIP en `usuarios`. VIP y Sweet Plan son lo mismo: todo usuario con Sweet vigente tiene 20 % (50 % en su cumpleaños), calendario y video, haya iniciado sesión con contraseña o con su tarjeta.

La tarjeta RFID es la llave del kiosco de la tienda física. Al comprar el Sweet Plan se simula la entrega de una tarjeta, que queda ligada a la cuenta. Al pasarla por el lector de la computadora de la tienda, se valida que el dueño tenga Sweet vigente y se inicia su sesión sin contraseña.

Criterios de aceptación:

1. Sin sesión, o con sesión Basic, `/` y `/carrito/` se ven y cobran exactamente como hoy, y no aparece "Membresía VIP".
2. Un usuario Sweet que inicia sesión con contraseña ve "Membresía VIP" y su carrito (productos y cupcakes personalizados) con 20 % menos.
3. Al comprar el Sweet Plan, el usuario recibe una tarjeta simulada: se le asigna una tarjeta libre y la página lo confirma.
4. En el kiosco, al pasar la tarjeta de un usuario Sweet, en 4 s o menos queda su sesión iniciada con el modo VIP, y el carrito se conserva.
5. Al pasar la tarjeta de otro usuario, la sesión cambia a esa cuenta sin ningún dato del anterior.
6. Una tarjeta cuyo dueño ya no tiene Sweet vigente no inicia sesión y muestra "Renueva tu Sweet Plan".
7. Cada usuario Sweet agrega, ve y borra sus propias fechas; nunca ve las de otro.
8. Cada usuario registra su cumpleaños una sola vez, tras un aviso de que no podrá cambiarlo. Después solo el admin lo cambia.
9. El día de su cumpleaños (hora de Ciudad de México) el descuento es 50 %, salvo si registró la fecha ese mismo día.
10. El QR abre el video del usuario, alojado en AWS S3, desde un celular.
11. Un pedido Sweet en `/checkout/` guarda el descuento aplicado y el total con descuento, incluidos los cupcakes personalizados.
12. En el kiosco, "Salir", 5 min sin actividad o una tarjeta inválida cierran la sesión que abrió la tarjeta.
13. Un comando crea los 3 usuarios Sweet de la demo, con la estructura de la tabla `Usuarios`. Los 18 tests actuales siguen pasando, junto con los nuevos.

Fuera de alcance por ahora: uso del kiosco en celular, pasarela de pago real (el pago del Sweet Plan sigue simulado) y CI. El checkout de cupcakes personalizados (bug #7) sí entra.

## Arquitectura y flujo

El ESP32 nunca habla con el navegador: le dice a Django qué tarjeta leyó la terminal `caja-1`. La computadora de la tienda, vinculada una vez a esa terminal, pregunta su estado cada 2 s (ARCHITECTURE.md fija polling de 3 a 5 s; se bajó a 2 s para cumplir el criterio de 4 s).

```
Tarjeta ──▶ ESP32 + RC522 ──POST /api/rfid/scan/ (token)──▶ Django en Render ──▶ PostgreSQL
                                                                 ▲   │
Computadora del kiosco ──GET /api/iot/estado/ cada 2 s (cookie)──┘   └──▶ S3 (videos, URL firmada)
Celular ──GET /vip/v/<codigo>/ (QR)──▶ Django ──302──▶ S3
```

Django es la única fuente de verdad del VIP activo y del descuento. El lector y la página solo envían y muestran, y los videos viven en S3 porque el disco de Render es efímero.

## Supuestos y decisiones

Todas las decisiones están cerradas (las últimas se confirmaron el 2026-11-18).

| Tema | Decisión | Origen |
| --- | --- | --- |
| VIP = Sweet Plan | El modo VIP, el 20 % y el 50 % de cumpleaños dependen solo de que `Suscripcion.objects.plan_de(usuario)` sea Sweet vigente. Basic no tiene descuento. | Tu decisión |
| Descuento sin tarjeta | Un usuario Sweet que inicia sesión con contraseña (en casa o en tienda) también tiene el descuento. | Tu decisión |
| Para qué sirve la tarjeta | Es la llave del kiosco de la tienda física: al pasarla, valida que el dueño sea Sweet vigente e inicia su sesión sin contraseña. No da descuentos por sí misma. | Tu decisión |
| Entrega de la tarjeta | Solo al comprar el Sweet Plan (un pedido normal no entrega tarjeta): `Suscripcion.contratar_mes()` asigna al usuario la primera tarjeta libre del inventario. Si no hay tarjetas libres, la compra sigue y la página dice "Tu tarjeta VIP está en camino". Las renovaciones no asignan otra tarjeta. | Tu decisión |
| Validez mensual de la tarjeta | La tarjeta vale solo mientras el Sweet Plan esté vigente, es decir, mientras hoy ≤ `Suscripcion.fecha_fin` del mes pagado. Si no se paga el mes siguiente, la suscripción expira y la tarjeta deja de validar aunque se pase por el lector. Una suscripción cancelada vale hasta su `fecha_fin`, porque ese mes ya está pagado. | Tu decisión |
| Inventario de tarjetas | Los UID de las 3 tarjetas físicas se dan de alta sin dueño (en el admin o con `registrar_tarjeta <uid>`) y quedan libres hasta la entrega simulada. Nunca se escriben en el código. | ARCHITECTURE.md |
| Tarjeta de un Sweet vencido | No inicia sesión; el kiosco muestra "Renueva tu Sweet Plan". La tarjeta sigue ligada a la cuenta para cuando renueve. | Validación de Sweet |
| Dónde vale la tarjeta | Solo en un navegador vinculado con `/kiosco/caja-1/` (solo staff). | Seguridad |
| Cierre de sesión en el kiosco | "Salir", 5 min sin actividad o una tarjeta inválida cierran la sesión que abrió la tarjeta y vacían el carrito; la terminal queda vinculada. | Para que el siguiente cliente no herede la cuenta |
| Qué cuenta como actividad | Solo navegar páginas en el kiosco (cualquier petición que no sea `/api/`): un middleware de `iot` actualiza `Terminal.ultima_actividad`. El polling **no** cuenta como actividad. | Tu decisión |
| Tarjeta inválida y sesión con contraseña | Si en el kiosco hay una sesión iniciada con contraseña y se pasa una tarjeta inválida (desconocida o sin Sweet), esa sesión también se cierra. | Tu decisión |
| Ingredientes exclusivos (#9) | `cargar_catalogo` marca algunos ingredientes como `solo_suscriptores=True` para que el Sweet Plan desbloquee algo desde los datos iniciales. Se hace en la fase 2. | Tu decisión |
| Descuento | 20 % desde `settings.VIP_DESCUENTO`. Aplica a productos del catálogo y a cupcakes personalizados; no al pago del Sweet Plan. | Tu decisión |
| Cumpleaños | 50 % que reemplaza al 20 %. El usuario Sweet lo registra una vez desde `/vip/` tras un aviso; después solo el admin lo cambia. No aplica el mismo día en que se registró. | Tu decisión |
| Usuarios de la demo | Un comando idempotente crea 3 usuarios Sweet con los campos de la tabla `Usuarios` (nombre, email, contraseña, teléfono, fecha de registro), les contrata el Sweet Plan y les entrega una tarjeta cada uno. | Tu decisión |
| Videos | `ExperienciaQR` es el video del usuario, con el archivo en AWS S3. | Tu decisión |
| Sincronización del kiosco | Polling cada 2 s (`IOT_POLL_SEGUNDOS = 2`); recarga cuando cambia `Terminal.version`. | Tu decisión (ARCHITECTURE.md decía 3 a 5 s) |
| Carrito | Se reutiliza el de la sesión. Al iniciar sesión por tarjeta se conservan el carrito y la terminal, aunque Django rote la sesión. | Existente |
| Render despierto | El ESP32 hace `GET /healthz` cada 10 min. | Tu decisión |
| Rama | Se trabaja en `feat/iot-vip` y se fusiona a `feat/render-allocation`, que es la que despliega Render. | Tu decisión |

## Modelos de datos

Se crean 4 modelos (`PerfilVIP` en `usuarios`; `TarjetaRFID`, `Terminal` y `LecturaRFID` en `iot`) y se agregan pocos campos a 3 tablas del diagrama ER. La tarjeta y el perfil van separados: la tarjeta existe antes de tener dueño (inventario) y el perfil existe aunque la tarjeta no haya llegado. Antes de migrar, Claude Code debe comparar `tienda/models.py` con el diagrama y agregar solo lo que falte.

**Tabla `Usuarios` del diagrama → Django** (el proyecto usa el `User` nativo; no se cambia a un modelo de usuario propio)

| Campo del diagrama | Dónde vive |
| --- | --- |
| `id_usuario` | `User.id` |
| `nombre` | `User.first_name` (y `last_name` si se separa) |
| `email` | `User.email` (único, como ya valida `RegistroUsuarioForm`); también `User.username` |
| `password_hash` | `User.password` (Django guarda el hash; nunca texto plano) |
| `telefono` | `PerfilVIP.telefono` (el `User` nativo no tiene ese campo) |
| `fecha_registro` | `User.date_joined` |

```python
# usuarios/models.py
class CumpleYaRegistrado(Exception):
    """El usuario ya registró su cumpleaños; solo el admin puede cambiarlo."""

class PerfilVIP(models.Model):
    """Datos extra del usuario y su lógica de descuento (fat model)."""
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                   related_name="perfil_vip")
    telefono = models.CharField(max_length=20, blank=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    cumple_registrado_en = models.DateField(null=True, blank=True)

    @classmethod
    def de(cls, usuario) -> "PerfilVIP": ...          # get_or_create
    def es_sweet_vigente(self) -> bool: ...
    def registrar_cumpleanios(self, fecha: date, hoy: date) -> None: ...
    def es_cumpleanios(self, hoy: date) -> bool: ...
    def descuento_vigente(self, hoy: date) -> tuple[Decimal, str]: ...

# iot/models.py
class TarjetaQuerySet(models.QuerySet):
    def libres(self) -> "TarjetaQuerySet": ...         # activa y sin dueño
    def entregar_a(self, usuario) -> "TarjetaRFID | None":
        """Entrega simulada: asigna la primera tarjeta libre (select_for_update).
        Si el usuario ya tiene tarjeta, la devuelve sin asignar otra."""

class TarjetaRFID(models.Model):
    """Tarjeta física. Sin dueño = en inventario."""
    uid = models.CharField(max_length=20, unique=True)        # normalizado en save()
    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="tarjeta")
    entregada_en = models.DateTimeField(null=True, blank=True)
    activa = models.BooleanField(default=True)                # perdida -> False
    objects = TarjetaQuerySet.as_manager()

class Terminal(models.Model):
    """Una computadora de la tienda con su lector."""
    codigo = models.SlugField(unique=True)                    # "caja-1"
    tarjeta_activa = models.ForeignKey(TarjetaRFID, null=True, blank=True,
                                       on_delete=models.SET_NULL)
    ultima_actividad = models.DateTimeField(null=True, blank=True)
    ultimo_rechazo = models.CharField(max_length=20, blank=True)  # "desconocida", "sin_sweet"
    version = models.PositiveIntegerField(default=0)

    def activar(self, tarjeta: TarjetaRFID) -> None: ...
    def rechazar(self, motivo: str) -> None: ...
    def salir(self) -> None: ...
    def expirar_si_inactiva(self, ahora: datetime) -> bool: ...

class LecturaRFID(models.Model):
    """Bitácora de lecturas para depurar el hardware."""
    terminal = models.ForeignKey(Terminal, on_delete=models.CASCADE)
    uid = models.CharField(max_length=20)
    resultado = models.CharField(max_length=20)               # "ok", "desconocida", "sin_sweet"
    creada = models.DateTimeField(auto_now_add=True)
```

Cambios a tablas del diagrama ER:

| Tabla (modelo) | Campos del diagrama que se usan | Campos que se agregan | Para qué |
| --- | --- | --- | --- |
| `Suscripciones` (`Suscripcion`) | `estado`, `fecha_inicio`, `fecha_fin`, `monto_mensual` | — | `contratar_mes()` llama a `TarjetaRFID.objects.entregar_a(usuario)` |
| `Recordatorios_Eventos` (`RecordatorioEvento`) | `id_usuario`, `nombre_evento`, `fecha_evento`, `notificado` | `tipo` (cumpleaños, aniversario, otro), `se_repite_cada_anio` | Calendario del usuario |
| `Experiencias_QR` (`ExperienciaQR`) | `codigo_unico` (token del QR), `mensaje_texto`, `fecha_expiracion`; `url_video` pasa a ser un `FileField` en S3 o guarda la clave del objeto en S3 | `usuario` (FK al `User`); `id_detalle` pasa a opcional | Video del usuario |
| `Pedidos` (`Pedido`) | `total` (ya con descuento) | `descuento_porcentaje` (Decimal, default 0), `motivo_descuento` ("", "vip", "cumpleanios") | Dejar registrado el descuento cobrado |
| `Detalle_Pedidos` (`DetallePedido`) | `precio_unitario` = precio cobrado; `cupcake_custom` (el `id_cupcake` del diagrama) para personalizados | — | Se llena también para personalizados (#7) |

Todos los modelos nuevos se registran en el admin. En `PerfilVIP`, `fecha_nacimiento` sí se puede editar ahí: es la vía para corregir un cumpleaños. En `TarjetaRFID` el admin puede reasignar o desactivar una tarjeta perdida.

## Reglas de precio y descuento

El descuento depende solo del usuario con sesión: si es Sweet vigente, 20 % (50 % en su cumpleaños). Da igual si inició sesión con contraseña o con la tarjeta. Lo decide `PerfilVIP.descuento_vigente()` y se aplica con `aplicar_descuento()`; nadie más calcula descuentos.

```python
# settings.py
VIP_DESCUENTO = "0.20"
VIP_DESCUENTO_CUMPLE = "0.50"

# usuarios/models.py (métodos de PerfilVIP)
def es_sweet_vigente(self) -> bool:
    Suscripcion = apps.get_model("tienda", "Suscripcion")   # evita import circular
    return Suscripcion.objects.plan_de(self.usuario) == PLAN_SWEET  # constante de módulo en tienda.models

def es_cumpleanios(self, hoy: date) -> bool:
    n = self.fecha_nacimiento
    if n is None or self.cumple_registrado_en == hoy:      # anti-abuso
        return False
    if (n.month, n.day) == (2, 29) and not calendar.isleap(hoy.year):
        return (hoy.month, hoy.day) == (2, 28)
    return (n.month, n.day) == (hoy.month, hoy.day)

def descuento_vigente(self, hoy: date) -> tuple[Decimal, str]:
    if not self.es_sweet_vigente():
        return Decimal("0"), ""
    if self.es_cumpleanios(hoy):
        return Decimal(settings.VIP_DESCUENTO_CUMPLE), "cumpleanios"
    return Decimal(settings.VIP_DESCUENTO), "vip"

# tienda/models.py
def descuento_para(usuario, hoy: date) -> tuple[Decimal, str]:
    """Punto único para vistas y checkout. Anónimo -> sin descuento."""
    if not usuario.is_authenticated:
        return Decimal("0"), ""
    return PerfilVIP.de(usuario).descuento_vigente(hoy)

def aplicar_descuento(precio: Decimal, descuento: Decimal) -> Decimal:
    """Precio final redondeado a centavos."""
    return (precio * (1 - descuento)).quantize(Decimal("0.01"), ROUND_HALF_UP)
```

| Situación | Descuento | Producto de $100.00 | Cupcake personalizado de $35.00 |
| --- | --- | --- | --- |
| Sin sesión | 0 % | $100.00 | $35.00 |
| Sesión Basic | 0 % | $100.00 | $35.00 |
| Sesión Sweet vigente (contraseña o tarjeta) | 20 % | $80.00 | $28.00 |
| Sweet vigente, día de su cumpleaños | 50 %, reemplaza al 20 % | $50.00 | $17.50 |
| Igual, pero registró la fecha hoy mismo | 20 % | $80.00 | $28.00 |
| Sweet cancelado, todavía antes de `fecha_fin` | 20 % (sigue vigente) | $80.00 | $28.00 |
| Sweet vencido | 0 % | $100.00 | $35.00 |

Reglas adicionales:

- `hoy` siempre es `timezone.localdate()`; siempre `Decimal`, nunca `float`. Se redondea por línea y el total es la suma de líneas.
- Los cupcakes personalizados toman su precio de `CupcakePersonalizado.calcular_precio()` ($35 + extras) y luego `aplicar_descuento()`.
- `Pedido.objects.crear_desde_carrito()` recibe `descuento` y `motivo`, guarda `precio_unitario` ya descontado en cada `DetallePedido` y los dos campos nuevos en `Pedido`. `PrecioCambiado` sigue comparando contra el precio base de `Menu`.
- `checkout_total` en la sesión guarda el total ya con descuento, para que la validación de idempotencia actual siga coincidiendo.
- El descuento no aplica al pago del Sweet Plan ($99).
- La pantalla muestra el precio base tachado, el precio final y la etiqueta "VIP −20 %" o "Cumpleaños −50 %".

## Contrato de API

El ESP32 usa solo `POST /api/rfid/scan/` y `GET /healthz`. El inicio de sesión por tarjeta ocurre en la respuesta de `/api/iot/estado/`, porque es la única petición que llega con la cookie de sesión de la computadora del kiosco; el ESP32 no tiene esa cookie.

| Método y ruta | App | Quién lo llama | Qué hace | Respuestas |
| --- | --- | --- | --- | --- |
| `POST /api/rfid/scan/` | `iot` | ESP32 | Body `{"uid": "A1B2C3D4", "terminal": "caja-1"}`, header `Authorization: Token <IOT_DEVICE_TOKEN>`, sin CSRF. Busca la tarjeta, valida que su dueño sea Sweet vigente y fija `Terminal.tarjeta_activa`. | 200 `{"status":"ok","cliente":"Ana"}` · 403 `{"status":"sin_sweet"}` · 404 `{"status":"desconocida"}` (también tarjeta sin dueño o inactiva) · 401 · 400 |
| `GET /healthz` | proyecto | ESP32 cada 10 min y health check de Render | Responde sin tocar la sesión. | 200 `ok` |
| `GET /kiosco/<codigo>/` | `iot` | Staff, una vez por computadora | Guarda `terminal` en la sesión y redirige a `/`. | 302 · 403 si no es staff |
| `GET /api/iot/estado/` | `iot` | Página del kiosco, cada 2 s | Aplica la expiración de 5 min, sincroniza la sesión con la terminal (ver abajo) y devuelve el estado. | 200 `{"version": 7, "recargar": true, "rechazo": "" \| "desconocida" \| "sin_sweet"}` |
| `POST /api/iot/salir/` | `iot` | Botón "Salir" del kiosco | Quita la tarjeta activa y sube `version`; el siguiente `estado` cierra la sesión. Con CSRF. | 200 |
| `GET /vip/` | `usuarios` | Pestaña "Membresía VIP" | Página VIP. Exige sesión Sweet vigente, con o sin tarjeta. | 200 · 302 a `/suscripcion/` |
| `GET` / `POST /api/vip/fechas/` | `usuarios` | Calendario | Lista o crea `RecordatorioEvento` del usuario con sesión. | 200 · 201 · 400 · 403 |
| `DELETE /api/vip/fechas/<id>/` | `usuarios` | Calendario | Borra solo si es del usuario con sesión. | 204 · 404 |
| `POST /api/vip/cumpleanios/` | `usuarios` | Formulario de cumpleaños | Body `{"fecha": "1995-03-14"}`. Guarda una sola vez. | 201 · 409 si ya existe · 400 si es futura o inválida |
| `GET /vip/v/<codigo_unico>/` | `usuarios` | Celular que escanea el QR | Redirige a una URL firmada de S3 que vence en 1 h. 404 si pasó `fecha_expiracion`. | 302 · 404 |

**Sincronización de la sesión en `/api/iot/estado/`** (función `iot.sesion.sincronizar(request, terminal)`):

1. Terminal con tarjeta activa y la sesión sin usuario o con otro usuario: guardar el carrito (`CLAVE_CARRITO`, `CLAVE_PERSONALIZADOS`) y la clave `terminal`, llamar a `login(request, tarjeta.usuario, backend="django.contrib.auth.backends.ModelBackend")`, restaurar lo guardado y marcar `request.session["login_por_tarjeta"] = True`. Hay que restaurar porque Django vacía la sesión al cambiar de usuario.
2. Terminal sin tarjeta activa (salida, expiración o rechazo) y `login_por_tarjeta` verdadero: `logout(request)` y volver a poner solo `terminal`. El carrito se vacía a propósito.
3. Usuario que inició sesión con contraseña en el kiosco: una tarjeta válida lo reemplaza como en el paso 1. Una **tarjeta inválida** (rechazo `desconocida` o `sin_sweet`) también cierra su sesión, como en el paso 2. La expiración por inactividad y "Salir" solo cierran sesiones abiertas por tarjeta.
4. En los pasos 1 y 2 la respuesta lleva `recargar: true` para que la página se vuelva a dibujar.

Otras reglas:

- Normalizar el UID (quitar espacios y `:`, mayúsculas) antes de buscar `TarjetaRFID`.
- Comparar el token con `hmac.compare_digest` contra `settings.IOT_DEVICE_TOKEN`, que viene de una variable de entorno. Si la variable está vacía, `/api/rfid/scan/` siempre responde 401.
- **Validez mensual:** el scan valida con `Suscripcion.objects.plan_de(dueño)`, que primero marca como expiradas las suscripciones con `fecha_fin` pasada. Si el mes no se pagó, la respuesta es 403 `sin_sweet` aunque la tarjeta esté registrada y activa.
- **Actividad:** el middleware `iot.middleware.ActividadKioscoMiddleware` actualiza `Terminal.ultima_actividad` en cada petición que no empiece con `/api/` de una sesión que tenga `terminal`. `/api/iot/estado/` compara contra ese valor para aplicar los 5 min.
- Cada cambio (entrada, cambio de tarjeta, salida, expiración, rechazo) sube `Terminal.version`.
- Las APIs `/api/vip/*` usan `request.user` y exigen Sweet vigente; nunca leen un id de usuario que mande el navegador.
- Vistas delgadas: validan la petición y llaman a un método de modelo (`Terminal.activar`, `PerfilVIP.registrar_cumpleanios`, etc.).

## Frontend

No hay una tienda nueva: `/`, `/carrito/`, `/checkout/` y `/suscripcion/` ganan lo VIP para cualquier sesión Sweet, y se agrega `/vip/`. Lo único exclusivo del kiosco es el polling y el inicio de sesión por tarjeta. Se mantienen las plantillas Django, el CSS propio y JavaScript sin framework.

**En todas las páginas (vía `base.html`)**

- Un context processor nuevo, `usuarios.context_processors.vip`, expone `vip_activo`, `vip_descuento` y `vip_motivo` a partir de `descuento_para(request.user, hoy)`. Se suma al de carrito y plan que ya existe.
- Sesión Sweet vigente: en la barra aparecen la pestaña "Membresía VIP" y la etiqueta "VIP −20 %" o "Cumpleaños −50 %". Sesión Basic o sin sesión: la barra de hoy.

**Solo en el kiosco** (sesión con `terminal`)

- `base.html` carga `iot/static/iot/polling.js`, que llama a `/api/iot/estado/` cada 2 s (`IOT_POLL_SEGUNDOS`) y hace `location.reload()` si `recargar` es verdadero o cambió `version`.
- Avisos de 3 s según `rechazo`: "Tarjeta no registrada" o "Tu Sweet Plan venció. Renuévalo para usar tu tarjeta".
- Con sesión abierta por tarjeta: "Hola, \<nombre>" y un botón grande "Salir".

**Suscripción**

- Al confirmar el Sweet Plan en `/suscripcion/confirmar/`, la página de éxito muestra la entrega simulada: "Tu tarjeta VIP termina en …D4. Recibe tu tarjeta en tienda y úsala en el kiosco para entrar sin contraseña". Sin tarjetas libres: "Tu tarjeta VIP está en camino".

**Catálogo, carrito y checkout**

- `inicio` y `ver_carrito` reciben de la vista el precio final de cada producto y de cada cupcake personalizado, calculado con `aplicar_descuento()`. Con descuento se ve el precio base tachado y el final.
- `/checkout/` procesa productos y cupcakes personalizados (#7) y muestra el desglose: subtotal, descuento y total.

**Página `/vip/`** (sesión Sweet vigente)

- Encabezado "Membresía VIP — \<nombre>", vigencia del Sweet Plan (`fecha_fin`), descuento de hoy y estado de la tarjeta (entregada, terminación del UID, o en camino). En su cumpleaños, una felicitación con el 50 %.
- **Cumpleaños**: si `fecha_nacimiento` está vacía, un formulario con selector de fecha. Al enviarlo se abre un modal propio (no `alert`): "Vas a registrar el 14 de marzo como tu cumpleaños. Después no podrás cambiarlo. ¿Confirmas?", con "Cancelar" y "Sí, guardar". Si ya existe, se muestra la fecha con la nota "Para corregirla, pídelo en tienda".
- **Calendario**: FullCalendar 6 por CDN, vista mensual, conectado a `/api/vip/fechas/`. Formulario con nombre del evento, fecha y tipo; clic en un evento para borrarlo. El cumpleaños aparece como evento fijo que no se puede borrar.
- **Mi video**: QR en SVG generado con `segno`, apuntando a `https://<RENDER_EXTERNAL_HOSTNAME>/vip/v/<codigo_unico>/`, con el enlace en texto debajo y el `mensaje_texto`. Sin `ExperienciaQR`: "Tu video estará listo pronto".

## Firmware ESP32 + RC522

El ESP32 lee el UID, lo manda por HTTPS a `/api/rfid/scan/`, enciende un LED verde (200) o rojo (cualquier otra respuesta) y cada 10 min llama a `/healthz` para que Render no se duerma.

**Conexión (SPI por defecto del ESP32)**

| RC522 | ESP32 |
| --- | --- |
| SDA (SS) | GPIO 5 |
| SCK | GPIO 18 |
| MOSI | GPIO 23 |
| MISO | GPIO 19 |
| RST | GPIO 22 |
| 3.3V | 3V3 (nunca 5 V) |
| GND | GND |
| IRQ | sin conectar |

**Proyecto**: carpeta `firmware/esp32-vip/` en la raíz del repo, con PlatformIO (`platform = espressif32`, `framework = arduino`) y la librería `miguelbalboa/MFRC522`. Credenciales en `include/secrets.h`, listado en `.gitignore`; en el repo solo va `secrets.example.h`.

```cpp
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <MFRC522.h>
#include "secrets.h"   // WIFI_SSID, WIFI_PASS, API_URL, IOT_DEVICE_TOKEN, TERMINAL

MFRC522 rfid(5, 22);
String ultimoUid;
unsigned long ultimoMs = 0, ultimoPing = 0;
const unsigned long PING_MS = 10UL * 60UL * 1000UL;

String leerUid() {
  String s;
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) s += "0";
    s += String(rfid.uid.uidByte[i], HEX);
  }
  s.toUpperCase();
  return s;
}

int peticion(const char* metodo, const String& ruta, const String& body) {
  WiFiClientSecure cli; cli.setInsecure();   // prototipo; luego fijar el certificado raíz
  HTTPClient http;
  http.setTimeout(15000);
  http.begin(cli, String(API_URL) + ruta);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Token ") + IOT_DEVICE_TOKEN);
  int code = (strcmp(metodo, "POST") == 0) ? http.POST(body) : http.GET();
  http.end();
  return code;
}

void setup() {
  Serial.begin(115200);
  SPI.begin(); rfid.PCD_Init();
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) delay(300);
  Serial.println("WiFi OK");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) WiFi.reconnect();

  if (millis() - ultimoPing > PING_MS) {            // mantiene despierto Render
    Serial.printf("healthz %d\n", peticion("GET", "/healthz", ""));
    ultimoPing = millis();
  }

  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;
  String uid = leerUid();
  if (uid == ultimoUid && millis() - ultimoMs < 3000) return;   // antirrebote 3 s
  ultimoUid = uid; ultimoMs = millis();

  String body = "{\"uid\":\"" + uid + "\",\"terminal\":\"" + TERMINAL + "\"}";
  int code = peticion("POST", "/api/rfid/scan/", body);
  if (code < 0) code = peticion("POST", "/api/rfid/scan/", body);   // un reintento
  Serial.printf("UID %s -> HTTP %d\n", uid.c_str(), code);
  // LED verde si code == 200, rojo en otro caso
  rfid.PICC_HaltA(); rfid.PCD_StopCrypto1();
}
```

Puntos a cuidar:

- **Primer paso**: cargar el sketch, pasar las 3 tarjetas y copiar sus UID del monitor serie a `DEMO_VIP_UIDS` (o al admin de `TarjetaRFID`).
- `IOT_DEVICE_TOKEN` en `secrets.h` debe ser el mismo valor que la variable de entorno en Render.
- El ping cada 10 min usa horas de instancia gratuita las 24 h. Render da [750 horas al mes por workspace](https://render.com/docs/free), suficiente para un solo servicio encendido todo el mes, pero no para dos.
- Algunas tarjetas tienen UID de 7 bytes; el código ya lo soporta porque recorre `uid.size`.

## Despliegue en Render

El servicio ya funciona en Render (gunicorn, WhiteNoise, PostgreSQL, `build.sh` y `render.yaml`); solo se agregan una dependencia, unas variables de entorno y un comando al build.

| Archivo | Cambio |
| --- | --- |
| `requirements.txt` y `Pipfile` | Agregar `segno`. Volver a dejarlos sincronizados. `django-storages[s3]` ya está. |
| `settings.py` | `INSTALLED_APPS += ["iot"]`, el context processor `usuarios.context_processors.vip`, el middleware `iot.middleware.ActividadKioscoMiddleware`, `IOT_DEVICE_TOKEN = os.environ.get("IOT_DEVICE_TOKEN", "")` (vacío = scan siempre 401; así no fallan los tests ni `collectstatic`), `VIP_DESCUENTO`, `VIP_DESCUENTO_CUMPLE`, `IOT_POLL_SEGUNDOS = 2`, `VIP_EXPIRA_MINUTOS = 5` y `/healthz` en `SECURE_REDIRECT_EXEMPT` (para que el health check de Render reciba 200 y no 301). |
| `.env.example` | Agregar `IOT_DEVICE_TOKEN=`, `DEMO_PASSWORD=` y `DEMO_VIP_UIDS=` con comentarios. |
| `render.yaml` | En el Web Service: `healthCheckPath: /healthz`, `IOT_DEVICE_TOKEN` con `generateValue: true`, y `DEMO_PASSWORD` y `DEMO_VIP_UIDS` con `sync: false` (se capturan a mano en el panel). |
| `build.sh` | Después de `cargar_catalogo`: `python manage.py crear_terminal caja-1` y, si existen `DEMO_PASSWORD` y `DEMO_VIP_UIDS`, `python manage.py crear_usuarios_demo`. Ambos idempotentes. |
| `bakeandmade/urls.py` | `include("iot.urls")` y la ruta `/healthz`. |

Pendientes del análisis que afectan a esta capa:

- **Rama**: Render despliega `feat/render-allocation`, así que todo push ahí llega a producción. Trabajar en `feat/iot-vip` y fusionar solo con tests en verde. Corregir `docs/despliegue-render.md`, que todavía dice `main` (#18).
- **#19 S3 (obligatorio)**: los videos viven en AWS. Hay que definir en Render `AWS_STORAGE_BUCKET_NAME` y las credenciales de AWS, con el bucket privado; el QR redirige a una URL firmada.
- **#17 PostgreSQL**: la base gratuita [vence a los 30 días de crearse](https://render.com/docs/free). Si se recrea, el siguiente build vuelve a crear los 3 usuarios demo; las tarjetas se conservan porque sus UID están en `DEMO_VIP_UIDS`.
- **#16 HSTS**: el ESP32 exige HTTPS, que Render ya da; subir `SECURE_HSTS_SECONDS` cuando se confirme estable.

## Usuarios de demostración

El comando `python manage.py crear_usuarios_demo` crea los 3 usuarios Sweet de la demo con los campos de la tabla `Usuarios`. Se puede correr varias veces sin duplicar nada, igual que `cargar_catalogo`.

| nombre | email | telefono | fecha\_registro |
| --- | --- | --- | --- |
| Ana López | ana.demo@bakeandmade.test | 5510000001 | 2026-09-01 |
| Bruno García | bruno.demo@bakeandmade.test | 5510000002 | 2026-09-15 |
| Carla Méndez | carla.demo@bakeandmade.test | 5510000003 | 2026-10-01 |

Para cada usuario, en este orden:

1. `User` con `username` y `email` = el email, `first_name` = nombre y `date_joined` = fecha\_registro. La contraseña sale de la variable de entorno `DEMO_PASSWORD` y se guarda con `set_password()` (hash). Sin esa variable el comando falla con un mensaje claro.
2. `PerfilVIP` con el teléfono.
3. Si el UID no existe, se registra como tarjeta libre. Los UID vienen de `--uids A1B2C3D4,B2C3D4E5,C3D4E5F6` o de la variable `DEMO_VIP_UIDS`, en el mismo orden que la tabla. Nunca se escriben en el código.
4. Si no tiene Sweet vigente, se llama a `Suscripcion.contratar_mes()` (pago simulado). Eso dispara la entrega simulada y le asigna su tarjeta.

En Render se ejecuta desde `build.sh` solo si están definidas `DEMO_PASSWORD` y `DEMO_VIP_UIDS`, igual que hoy se hace con `DJANGO_SUPERUSER_*`. En local, sin hardware, se usan UID inventados.

## Plan de pruebas

Todo se prueba primero sin hardware: `python manage.py simular_scan <uid> --terminal caja-1` hace lo mismo que el ESP32, y `curl` sirve contra Render. Las pruebas usan `unittest` de Django, como las 18 actuales, en `iot/tests.py`, `usuarios/tests.py` y `tienda/tests.py`.

**Pruebas automáticas** (`python manage.py test` debe pasar completo, con las 18 actuales, antes de cada merge a `feat/render-allocation`)

| Clase | Caso | Resultado esperado |
| --- | --- | --- |
| `UsuariosDemoTests` | Correr `crear_usuarios_demo` con 3 UID | 3 `User` con nombre, email, `date_joined` y teléfono de la tabla; los 3 Sweet vigentes; cada uno con su tarjeta en el orden dado |
| `UsuariosDemoTests` | Correrlo dos veces | Siguen siendo 3 usuarios, 3 tarjetas y 1 suscripción vigente cada uno |
| `UsuariosDemoTests` | Contraseña | Se guarda como hash (`check_password` funciona; el campo no contiene el texto) |
| `UsuariosDemoTests` | Sin `DEMO_PASSWORD` | El comando falla sin crear nada |
| `EntregaTarjetaTests` | Comprar Sweet con tarjetas libres | Se asigna la primera libre y se llena `entregada_en` |
| `EntregaTarjetaTests` | Renovar Sweet | No se asigna otra tarjeta |
| `EntregaTarjetaTests` | Comprar Sweet sin tarjetas libres | La suscripción queda activa y el usuario sin tarjeta ("en camino") |
| `DescuentoVIPTests` | Sesión Sweet vigente iniciada con contraseña | 20 % |
| `DescuentoVIPTests` | Sesión Basic / sin sesión | 0 % |
| `DescuentoVIPTests` | Sweet cancelado antes de `fecha_fin` / vencido | 20 % / 0 % |
| `DescuentoVIPTests` | Cumpleaños hoy (Sweet) / registrado hoy mismo | 50 % / 20 % |
| `DescuentoVIPTests` | Nacido 29 feb, año no bisiesto | 50 % el 28 feb |
| `DescuentoVIPTests` | `aplicar_descuento($99.99, 0.20)` | $79.99, tipo `Decimal` |
| `CumpleaniosTests` | Primer registro / segundo intento / fecha futura | Se guarda / 409 sin cambios / 400 |
| `ScanAPITests` | Tarjeta de un Sweet vigente, token correcto | 200, terminal con esa tarjeta, `version` +1 |
| `ScanAPITests` | Tarjeta de un Sweet vencido | 403 `sin_sweet`, sin sesión |
| `ScanAPITests` | UID desconocido, tarjeta libre o inactiva | 404, queda en `LecturaRFID` |
| `ScanAPITests` | UID en minúsculas o con espacios | Se reconoce igual |
| `ScanAPITests` | Sin token o token incorrecto | 401, estado sin cambios |
| `LoginTarjetaTests` | Escaneo con sesión anónima y 2 productos en carrito | Tras `estado`: sesión del dueño, el carrito sigue con 2 productos |
| `LoginTarjetaTests` | Tarjeta A y luego B | Sesión de B, carrito y `terminal` conservados |
| `LoginTarjetaTests` | Salir o 5 min sin actividad | Sesión cerrada, carrito vacío, `terminal` conservada |
| `LoginTarjetaTests` | Escaneo en un navegador sin terminal vinculada | No inicia sesión |
| `KioscoTests` | `/kiosco/caja-1/` sin staff | 403 |
| `FechasVIPTests` | A crea una fecha; B pide la lista / intenta borrarla | B no la ve / 404 |
| `FechasVIPTests` | Usuario Basic llama a `/api/vip/fechas/` | 403 |
| `TiendaVIPTests` | Mismo carrito (producto + personalizado) anónimo y luego con sesión Sweet | Total normal y luego −20 % en ambas líneas |
| `CheckoutVIPTests` | Solo personalizados en el carrito | Pedido creado con `DetallePedido.cupcake_custom` (resuelve #7) |
| `CheckoutVIPTests` | Sesión Sweet | `descuento_porcentaje = 0.20`, `precio_unitario` descontado, total correcto |
| `CheckoutVIPTests` | Token de checkout reutilizado | No duplica el pedido (como hoy) |
| `VideoQRTests` | `/vip/v/<codigo_unico>/` vigente / expirado | 302 a URL firmada de S3 (con S3 simulado en el test) / 404 |

**Prueba de humo** (en la URL de Render, con las 3 tarjetas reales y los 3 usuarios demo)

- [ ] Leer los 3 UID con el monitor serie, ponerlos en `DEMO_VIP_UIDS` y desplegar: aparecen los 3 usuarios Sweet con tarjeta en el admin.
- [ ] Subir en el admin un video a S3 para cada uno (`ExperienciaQR`).
- [ ] Como staff, abrir `/kiosco/caja-1/` y cerrar la sesión de staff.
- [ ] Agregar un producto y un cupcake personalizado: precio normal, sin pestaña VIP.
- [ ] Pasar la tarjeta de Ana: en 4 s o menos aparece "Hola, Ana", "Membresía VIP" y el carrito baja 20 %.
- [ ] En `/vip/`, registrar el cumpleaños de Ana con fecha de hoy: aparece el aviso; después ya no se puede editar y el descuento sigue en 20 %.
- [ ] Agregar una fecha al calendario y escanear el QR con un celular: abre el video de Ana.
- [ ] Hacer checkout: el pedido queda con 20 % y con el cupcake personalizado.
- [ ] Pasar la tarjeta de Bruno: cambian la sesión, el calendario (sin la fecha de Ana) y el QR.
- [ ] En el admin, poner hoy como cumpleaños de Carla con `cumple_registrado_en` en otra fecha; pasar su tarjeta: 50 % y felicitación.
- [ ] En el admin, vencer la suscripción de Bruno y pasar su tarjeta: "Renueva tu Sweet Plan", sin sesión.
- [ ] En otra computadora, iniciar sesión como Ana con contraseña: también ve el 20 %.
- [ ] Esperar 5 min sin actividad en el kiosco: la sesión se cierra sola.

## Fases para Claude Code

Pídele a Claude Code una fase a la vez. Cada fase termina con `python manage.py test` en verde y un commit.

0. **Rama** ✅: `feat/iot-vip` creada desde `feat/render-allocation` (la que despliega Render). Fusionar de vuelta solo con tests en verde.
1. **Modelos** ✅ (Fase 1 de ARCHITECTURE; `url_video` quedó como `ExperienciaQR.video`): app `iot`, `PerfilVIP`, `TarjetaRFID`, `Terminal`, `LecturaRFID`; campos nuevos en `RecordatorioEvento`, `ExperienciaQR` (con `detalle_pedido` opcional y `url_video` como archivo) y `Pedido` según el diagrama ER; migraciones y admin. Comandos `crear_terminal` y `registrar_tarjeta`.
2. **Entrega simulada, usuarios demo e ingredientes exclusivos** ✅ (exclusivos: Red velvet, Dulce de leche, Queso crema y Fresas; la migración `tienda.0007` los marca en bases existentes): `TarjetaRFID.objects.entregar_a()`, la llamada desde `Suscripcion.contratar_mes()` (import perezoso para no acoplar `tienda` a `iot`), el comando `crear_usuarios_demo` y `cargar_catalogo` con ingredientes `solo_suscriptores=True` (#9). Tests `EntregaTarjetaTests` y `UsuariosDemoTests`.
3. **Descuentos** ✅ (`descuento_para()` no crea el perfil si no existe, para que consultar el descuento nunca escriba en la base; `registrar_cumpleanios()` lanza `CumpleYaRegistrado` o `FechaCumpleInvalida`, que la fase 8 traduce a 409 y 400): `es_sweet_vigente()`, `es_cumpleanios()`, `registrar_cumpleanios()`, `descuento_vigente()`, `descuento_para()`, `aplicar_descuento()` y settings. Tests `DescuentoVIPTests` y `CumpleaniosTests`.
4. **API IoT e inicio de sesión por tarjeta** ✅ (detalles de implementación: la sesión solo procesa cada `Terminal.version` una vez, para que un rechazo viejo no saque a quien entre después; `/kiosco/<codigo>/` cierra la sesión del staff al vincular; "Salir" cierra la sesión en el acto, sin esperar al siguiente polling; el cierre de sesión de la barra conserva la vinculación del kiosco; terminal desconocida en el scan responde 400; `/healthz` ya está en `SECURE_REDIRECT_EXEMPT`) (Fase 2): `/api/rfid/scan/` (con validación mensual del Sweet), `/healthz`, `/kiosco/<codigo>/`, `/api/iot/estado/` con `iot.sesion.sincronizar()`, `/api/iot/salir/`, `ActividadKioscoMiddleware` y el comando `simular_scan`. Tests `ScanAPITests`, `LoginTarjetaTests` y `KioscoTests`, y `curl` en local.
5. **Tienda con descuento**: context processor (calcula el plan una sola vez por petición, sin duplicar el `UPDATE` de `plan_de()`), barra VIP, precios con descuento en `inicio` y `ver_carrito` (productos y personalizados), `polling.js` del kiosco, mensaje de entrega en `/suscripcion/`. Test `TiendaVIPTests`.
6. **Checkout de personalizados (#7 y #8)**: `checkout()` procesa `carrito_personalizados`, guarda `CupcakePersonalizado`, `CupcakeIngredientes` y `DetallePedido.cupcake_custom`, vuelve a validar en el servidor los ingredientes de la sesión, descuenta `Ingrediente.stock_disponible` y vacía ambos carritos.
7. **Checkout con descuento**: `crear_desde_carrito()` recibe `descuento` y `motivo`; desglose en la plantilla. Test `CheckoutVIPTests`.
8. **Página `/vip/`**: cumpleaños con el modal de aviso, calendario y QR con video en S3. Tests `FechasVIPTests` y `VideoQRTests`.
9. **Despliegue** (Fase 4): cambios de la tabla de despliegue, variables de AWS y de demo en Render, merge a `feat/render-allocation` y `curl` a la URL de Render.
10. **Firmware**: `firmware/esp32-vip/`; leer los 3 UID con el monitor serie y ponerlos en `DEMO_VIP_UIDS`.
11. **Prueba de humo**: recorrer la lista del plan de pruebas.

Prompt sugerido por fase: *"Lee docs/ARCHITECTURE.md y docs/IOT\_VIP\_SPEC.md. Implementa solo la fase N siguiendo las reglas de ARCHITECTURE.md (type hints, docstrings, fat models). Escribe y corre sus tests y no avances a la siguiente fase."*

## Preguntas abiertas

Ninguna. Todas quedaron cerradas el 2026-11-18:

- [x] La tarjeta se entrega solo al contratar el Sweet Plan y valida solo mientras el mes esté pagado (`fecha_fin`).
- [x] La actividad del kiosco se mide por páginas navegadas; el polling no cuenta.
- [x] Una tarjeta inválida también cierra una sesión iniciada con contraseña en el kiosco.
- [x] El polling es cada 2 s.
- [x] Los ingredientes exclusivos del Sweet Plan (#9) entran en la fase 2.

## Riesgos conocidos

- **UID clonable:** el UID de una MIFARE Classic se copia fácilmente. La tarjeta sirve como llave de la demo, no como autenticación fuerte.
- **Videos por el admin:** al subirlos, el archivo pasa por la instancia gratuita de Render (512 MB de RAM, timeout de gunicorn de 30 s). Hay que usar videos cortos (menos de ~30 MB) o subirlos directo a S3 y guardar la clave.
- **PostgreSQL gratuito:** vence a los 30 días. Si se recrea, se pierden pedidos, cumpleaños y fechas del calendario; los usuarios demo se vuelven a crear en el build.
- **Wi-Fi del ESP32:** solo funciona en 2.4 GHz y no pasa portales cautivos.
- **Cambio de precio entre GET y POST del checkout:** si el descuento cambia (medianoche de un cumpleaños o vencimiento del Sweet), el checkout rechaza la compra con un mensaje claro y hay que recargar.
