# CLAUDE.md

**Bake & Made** es una tienda en línea de repostería: un monolito Django 6.1.1 (Python 3.13) que se despliega en Render con PostgreSQL. Las reglas del proyecto están en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) y se aplican a todo el código.

## Documentación
- [README.md](README.md): qué es el proyecto, arranque rápido y guía de la documentación.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): visión, decisiones de diseño y reglas de código. **Manda sobre todo lo demás.**
- [docs/sistema-actual.md](docs/sistema-actual.md): el sistema hoy (apps, modelos, rutas, comandos, tests y pendientes).
- [docs/historial-de-cambios.md](docs/historial-de-cambios.md): cómo se recibió el proyecto y qué cambió en cada etapa. Agrega ahí cada cambio relevante.
- [docs/despliegue-render.md](docs/despliegue-render.md): Web Service + PostgreSQL, build y start command, variables de entorno.
- [docs/IOT_VIP_SPEC.md](docs/IOT_VIP_SPEC.md): especificación de la capa VIP/RFID (modelos, descuentos, API, kiosco, firmware y fases).
- [docs/diagramas.md](docs/diagramas.md): diagramas Mermaid (panorama, local vs Render, despliegue, ingredientes, login por tarjeta, descuento). Actualízalos si cambias esas piezas.

## Comandos
```bash
cp .env.example .env                # DEBUG=True para desarrollo local
pipenv install                      # o: pip install -r requirements.txt
cd bakeandmade                      # aquí está manage.py
python manage.py migrate
python manage.py cargar_catalogo    # datos iniciales; se puede repetir sin duplicar
python manage.py runserver
python manage.py test               # tests de tienda, usuarios e iot
```

## Mapa del código
- `bakeandmade/bakeandmade/settings.py`: toda la configuración se lee de variables de entorno (python-dotenv). WhiteNoise sirve los estáticos y S3 guarda las imágenes subidas (`/media`) si se define `AWS_STORAGE_BUCKET_NAME`.
- `bakeandmade/bakeandmade/urls.py`: hace `include()` de `usuarios.urls` y `tienda.urls`.
- `bakeandmade/usuarios/`: registro (pide teléfono, que `RegistroUsuarioForm.save()` guarda en `PerfilVIP`), login y logout con el `User` nativo; `PerfilVIP` (teléfono y cumpleaños, `PerfilVIP.de(usuario)`, `.registrar_cumpleanios()`, `.es_cumpleanios()`, `.descuento_vigente()`: **única fuente de la regla de descuento**). Comando `crear_usuarios_demo` (requiere `DEMO_PASSWORD` y `--uids` o `DEMO_VIP_UIDS`; `build.sh` lo corre en cada deploy y restablece la contraseña de los demos).
- `bakeandmade/usuarios/views_vip.py`: página `/vip/` (solo Sweet vigente), APIs `/api/vip/fechas/` (GET/POST), `/api/vip/fechas/<id>/` (DELETE), `/api/vip/cumpleanios/` (POST) y `/vip/v/<codigo>/` (pública: redirige a la URL firmada del video en S3). El calendario usa FullCalendar 6.1.15 por CDN y el QR se genera con `segno`.
- `bakeandmade/iot/`: `TarjetaRFID` (inventario, `.objects.libres()`, `.entregar_a()`, UID normalizado con `normalizar_uid`), `Terminal` (`.registrar_lectura()`, `.activar/rechazar/salir()`, `.expirar_si_inactiva()`) y `LecturaRFID`.
  - `iot/sesion.py`: `sincronizar(request, terminal)` inicia o cierra la sesión del kiosco según la terminal, conservando carrito y terminal. Cualquier cierre de sesión en un kiosco debe pasar por aquí (lo usa `usuarios.views.CerrarSesionView`).
  - `iot/middleware.py`: `ActividadKioscoMiddleware` (solo las páginas navegadas cuentan como actividad; `/api/` no).
  - Rutas: `/api/rfid/scan/` (ESP32, token en `IOT_DEVICE_TOKEN`), `/api/iot/estado/`, `/api/iot/salir/`, `/kiosco/<codigo>/` y `/healthz` (en `bakeandmade/urls.py`).
  - Comandos `crear_terminal <codigo>`, `registrar_tarjeta <uid>` y `simular_scan <uid> --terminal caja-1` (prueba sin hardware).
- `bakeandmade/tienda/models.py`: **lógica de negocio** en QuerySets y métodos de modelo:
  - `Suscripcion.objects.plan_de()`, `.vigente_para()`, `Suscripcion.contratar_mes()` (también entrega la tarjeta VIP con `TarjetaRFID.objects.entregar_a()`), `.cancelar()`
  - `Ingrediente.objects.de_categoria().visibles_para(usuario)`
  - `descuento_para(usuario, hoy)` y `aplicar_descuento(precio, descuento)`: todo precio con descuento VIP pasa por aquí (Decimal, redondeo por línea)
  - `Menu.objects.en_venta()`, `Menu.admite_cantidad()`
  - `Pedido.objects.lineas_validas()`, `.personalizados_validos()`, `.total_de(lineas, descuento)`, `.crear_desde_carrito()` (atómico, con `F()` y token único; guarda `CupcakePersonalizado` + `CupcakeIngredientes`, descuenta el stock de productos e ingredientes y registra `descuento_porcentaje`/`motivo_descuento` con `DetallePedido.precio_unitario` ya descontado)
  - `CupcakePersonalizado.PASOS`, `.calcular_precio()`, `.DIETAS`, `.COLORES_FROSTING`
- `bakeandmade/tienda/carrito.py`: claves y lectura del carrito en la sesión.
- `bakeandmade/tienda/peticion.py`: `plan_de_peticion()` y `descuento_de_peticion()` calculan plan y descuento **una vez por petición**; vistas y context processors deben usarlas en vez de llamar a `plan_de()` directo.
- Plantillas: las páginas no heredan de `base.html`. Lo común va en fragmentos incluidos en todas: `tienda/_encabezado.html` (anuncio y navbar, con el diseño de "Mi carrito"; cámbialo ahí, no en cada página; login y registro no lo usan), que incluye `tienda/_vip_nav.html` (pestaña "VIP", entre el carrito y el saludo), e `iot/_kiosco.html` (polling y barra del kiosco, antes de `</body>`). Toda `<img>` de producto lleva un `<template>` previo con el logo y `onerror` que lo usa si el archivo no existe. Contexto VIP y de kiosco en `usuarios.context_processors.vip`.
- `bakeandmade/tienda/views.py`: vistas delgadas (HTTP → modelos → plantilla/redirect).
- `bakeandmade/tienda/forms.py`: `DireccionEntregaForm` (dirección del checkout por campos; `.como_texto()` la une en `Pedido.direccion_entrega`, sin migración). Se dibuja con `tienda/_campo_direccion.html`.
- `cargar_catalogo`: crea lo que falte sin modificar lo existente; las únicas excepciones son completar la imagen que falte o esté rota (`IMAGENES`, `IMAGENES_INGREDIENTES`) y la receta (`RECETAS` → `DetallesMenu`) de un producto que no tenga. Las imágenes se versionan en `media/productos/` y `media/ingredientes/` (con `git add -f`, porque `media` está en `.gitignore`) y el comando sube a S3 las que falten.

- `firmware/esp32-vip/`: lector RFID (PlatformIO, ESP32 + RC522). Credenciales en `include/secrets.h` (en `.gitignore`; plantilla `secrets.example.h`). Pines, LEDs y lectura de UID en su `README.md`. Se carga con `cargar.ps1` (Windows; PlatformIO se cuelga compilando sobre `\\wsl.localhost\...`, así que compila en una copia en `%LOCALAPPDATA%`) o `cargar.sh` (WSL, con `usbipd-win`). No es parte del despliegue en Render.

## Reglas (de ARCHITECTURE.md)
- Apps separadas por responsabilidad: `tienda`, `usuarios` e `iot`.
- **Type hints** en todas las funciones y métodos.
- **Docstrings (PEP 257)** que expliquen el qué y el por qué.
- **Fat models, skinny views**: la lógica nueva va en modelos o QuerySets, no en vistas.
- Nada de credenciales en el código: todo por variables de entorno (agregarlas también a `.env.example`).
- Código, nombres y textos de la interfaz en español.

## Cuidado
- El checkout procesa productos y cupcakes personalizados. Los precios e ingredientes de la sesión **nunca** se usan para cobrar: `Pedido.objects.personalizados_validos()` los vuelve a validar contra la BD.
- Los nombres de URL no tienen namespace porque las plantillas usan `{% url 'inicio' %}`. Mantenlos así o actualiza todas las plantillas.
- Si cambias dependencias, actualiza **a la vez** `requirements.txt` (lo usa Render) y `Pipfile` (desarrollo).
- Capa IoT/VIP decidida: seguir [docs/IOT_VIP_SPEC.md](docs/IOT_VIP_SPEC.md). Se implementa **una fase a la vez** en la rama `feat/iot-vip`; cada fase termina con `python manage.py test` en verde y un commit. No avances a la siguiente fase sin indicación.
