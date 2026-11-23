# Bake & Made

Tienda en línea de repostería (cupcakes, pasteles, galletas y brownies) con membresía VIP y un kiosco en la tienda física donde el cliente inicia sesión pasando su tarjeta RFID.

- **Producción:** https://bake-and-made.onrender.com (Render, rama `feat/render-allocation`)
- **Stack:** Django 6.1.1 · Python 3.13 · PostgreSQL · WhiteNoise · AWS S3 · ESP32 + RC522

## Qué hace

| Para quién | Qué puede hacer |
|---|---|
| Cualquier visitante | Ver el catálogo, armar un carrito y diseñar cupcakes en un asistente de 4 pasos (base, relleno, cobertura y topping) |
| Cliente registrado | Comprar: el checkout valida precios y stock en el servidor, pide la dirección por campos y descuenta el inventario de productos e ingredientes |
| Cliente con **Sweet Plan** ($99 al mes, pago simulado) | 20 % de descuento en todo (50 % el día de su cumpleaños), ingredientes exclusivos, la página `/vip/` (calendario de fechas especiales y un QR con su video) y una tarjeta RFID |
| Personal de la tienda | Vincular la computadora del mostrador como kiosco (`/kiosco/caja-1/`). Ahí, quien pasa su tarjeta por el lector entra a su cuenta sin contraseña |
| Administrador | Catálogo, stock, pedidos, suscripciones, tarjetas, terminales y videos desde `/admin/` |

## Cómo funciona, en una imagen

```
Tarjeta ──▶ ESP32 + RC522 ──POST /api/rfid/scan/──▶ Django (Render) ──▶ PostgreSQL
                                                        ▲      │
Kiosco ──GET /api/iot/estado/ cada 2 s──────────────────┘      └──▶ S3 (imágenes y videos)
Cliente ──tienda, carrito, checkout, /vip/──▶ Django
Celular ──QR /vip/v/<codigo>/──▶ Django ──302──▶ video en S3
```

Django es la única fuente de verdad: el lector solo avisa qué tarjeta leyó y el kiosco pregunta cada 2 s si cambió algo. Hay diagramas más detallados en [docs/diagramas.md](docs/diagramas.md).

## Arranque rápido (local)

Requisitos: Python 3.13 y Pipenv (o `pip`). En local se usa SQLite y las imágenes van a `bakeandmade/media/`.

```bash
cp .env.example .env                # pon DEBUG=True; deja DATABASE_URL vacía
pipenv install                      # o: pip install -r requirements.txt
cd bakeandmade                      # aquí está manage.py
python manage.py migrate
python manage.py cargar_catalogo    # catálogo e ingredientes; se puede repetir
python manage.py runserver
python manage.py test               # 157 tests (tienda, usuarios e iot)
```

Para probar la capa VIP sin hardware:

```bash
python manage.py crear_terminal caja-1
DEMO_PASSWORD=algo-local python manage.py crear_usuarios_demo --uids A1B2C3D4,B2C3D4E5,C3D4E5F6
python manage.py createsuperuser    # entra como staff a /kiosco/caja-1/
python manage.py simular_scan A1B2C3D4 --terminal caja-1   # en otra terminal
```

> `Pipfile.lock` está desactualizado (no incluye gunicorn, whitenoise, segno, etc.). Si usas Pipenv, corre antes `pipenv lock`, o instala con `pip install -r requirements.txt`, que es lo que usa Render.

## Estructura del repo

```
bake-and-made/
├── README.md               ← este archivo
├── CLAUDE.md               ← mapa del código para agentes (Claude Code)
├── docs/                   ← documentación (ver abajo)
├── requirements.txt        ← dependencias que instala Render (Pipfile = desarrollo)
├── build.sh / render.yaml  ← build y Blueprint de Render
├── .env.example            ← plantilla de variables de entorno
├── firmware/esp32-vip/     ← lector RFID (PlatformIO); no se despliega en Render
└── bakeandmade/            ← proyecto Django
    ├── bakeandmade/        ← settings (todo por variables de entorno) y urls raíz
    ├── tienda/             ← catálogo, carrito, personalización, checkout, Sweet Plan, descuentos
    ├── usuarios/           ← registro, login, PerfilVIP y la página /vip/
    └── iot/                ← tarjetas, terminales, API del lector y sesión del kiosco
```

## Documentación

| Quiero… | Leer |
|---|---|
| Entender cómo está armado el sistema hoy (apps, modelos, rutas, tests y pendientes) | [docs/sistema-actual.md](docs/sistema-actual.md) |
| Saber cómo recibimos el proyecto y qué se cambió en cada etapa | [docs/historial-de-cambios.md](docs/historial-de-cambios.md) |
| Conocer las reglas de código y las decisiones de arquitectura | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (manda sobre todo lo demás) |
| Ver el diseño detallado de la capa VIP/RFID (API, reglas de descuento, pruebas) | [docs/IOT_VIP_SPEC.md](docs/IOT_VIP_SPEC.md) |
| Desplegar o configurar Render, PostgreSQL y S3 | [docs/despliegue-render.md](docs/despliegue-render.md) |
| Ver diagramas (panorama, entornos, despliegue, login por tarjeta, descuento) | [docs/diagramas.md](docs/diagramas.md) |
| Cargar el firmware al ESP32 | [firmware/esp32-vip/README.md](firmware/esp32-vip/README.md) |

## Cómo trabajamos

- Reglas de código (de ARCHITECTURE.md): type hints y docstrings en todo, lógica de negocio en modelos y QuerySets (vistas delgadas), credenciales solo por variables de entorno y todo en español.
- `feat/render-allocation` es la rama que despliega Render: todo push llega a producción. El trabajo se hace en otra rama y se fusiona con `python manage.py test` en verde.
- Si cambias dependencias, actualiza a la vez `requirements.txt` y `Pipfile`.
