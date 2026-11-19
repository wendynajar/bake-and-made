# CLAUDE.md

**Bake & Made** es una tienda en línea de repostería: un monolito Django 6.1.1 (Python 3.13) que se despliega en Render con PostgreSQL. Las reglas del proyecto están en [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) y se aplican a todo el código.

## Documentación
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): visión, decisiones de diseño y reglas de código. **Manda sobre todo lo demás.**
- [docs/analisis-estado-actual.md](docs/analisis-estado-actual.md): arquitectura, modelos, rutas, hallazgos y hoja de ruta.
- [docs/despliegue-render.md](docs/despliegue-render.md): Web Service + PostgreSQL, build y start command, variables de entorno.
- [docs/IOT_VIP_SPEC.md](docs/IOT_VIP_SPEC.md): especificación de la capa VIP/RFID (modelos, descuentos, API, kiosco, firmware y fases).

## Comandos
```bash
cp .env.example .env                # DEBUG=True para desarrollo local
pipenv install                      # o: pip install -r requirements.txt
cd bakeandmade                      # aquí está manage.py
python manage.py migrate
python manage.py cargar_catalogo    # datos iniciales; se puede repetir sin duplicar
python manage.py runserver
python manage.py test               # tests de tienda y usuarios
```

## Mapa del código
- `bakeandmade/bakeandmade/settings.py`: toda la configuración se lee de variables de entorno (python-dotenv). WhiteNoise sirve los estáticos y S3 guarda las imágenes subidas (`/media`) si se define `AWS_STORAGE_BUCKET_NAME`.
- `bakeandmade/bakeandmade/urls.py`: hace `include()` de `usuarios.urls` y `tienda.urls`.
- `bakeandmade/usuarios/`: registro, login y logout con el `User` nativo; `PerfilVIP` (teléfono y cumpleaños, `PerfilVIP.de(usuario)`). Comando `crear_usuarios_demo` (requiere `DEMO_PASSWORD` y `--uids` o `DEMO_VIP_UIDS`).
- `bakeandmade/iot/`: `TarjetaRFID` (inventario, `.objects.libres()`, UID normalizado con `normalizar_uid`), `Terminal` y `LecturaRFID`. Comandos `crear_terminal <codigo>` y `registrar_tarjeta <uid>`.
- `bakeandmade/tienda/models.py`: **lógica de negocio** en QuerySets y métodos de modelo:
  - `Suscripcion.objects.plan_de()`, `.vigente_para()`, `Suscripcion.contratar_mes()` (también entrega la tarjeta VIP con `TarjetaRFID.objects.entregar_a()`), `.cancelar()`
  - `Ingrediente.objects.de_categoria().visibles_para(usuario)`
  - `Menu.objects.en_venta()`, `Menu.admite_cantidad()`
  - `Pedido.objects.lineas_validas()`, `.crear_desde_carrito()` (atómico, con `F()` y token único)
  - `CupcakePersonalizado.PASOS`, `.calcular_precio()`, `.DIETAS`, `.COLORES_FROSTING`
- `bakeandmade/tienda/carrito.py`: claves y lectura del carrito en la sesión.
- `bakeandmade/tienda/views.py`: vistas delgadas (HTTP → modelos → plantilla/redirect).

## Reglas (de ARCHITECTURE.md)
- Apps separadas por responsabilidad: `tienda`, `usuarios` y, a futuro, `iot`.
- **Type hints** en todas las funciones y métodos.
- **Docstrings (PEP 257)** que expliquen el qué y el por qué.
- **Fat models, skinny views**: la lógica nueva va en modelos o QuerySets, no en vistas.
- Nada de credenciales en el código: todo por variables de entorno (agregarlas también a `.env.example`).
- Código, nombres y textos de la interfaz en español.

## Cuidado
- El checkout **no** procesa `carrito_personalizados` todavía (hallazgo #7 en el análisis).
- Los nombres de URL no tienen namespace porque las plantillas usan `{% url 'inicio' %}`. Mantenlos así o actualiza todas las plantillas.
- Si cambias dependencias, actualiza **a la vez** `requirements.txt` (lo usa Render) y `Pipfile` (desarrollo).
- Capa IoT/VIP decidida: seguir [docs/IOT_VIP_SPEC.md](docs/IOT_VIP_SPEC.md). Se implementa **una fase a la vez** en la rama `feat/iot-vip`; cada fase termina con `python manage.py test` en verde y un commit. No avances a la siguiente fase sin indicación.
