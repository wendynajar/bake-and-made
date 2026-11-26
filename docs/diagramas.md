# Diagramas del sistema

Vista rápida de cómo está armado Bake & Made. Los diagramas usan [Mermaid](https://mermaid.js.org/): GitHub los dibuja solo y en VS Code basta la extensión *Markdown Preview Mermaid Support*. Las reglas de código siguen en [ARCHITECTURE.md](ARCHITECTURE.md), el detalle de la capa VIP en [IOT_VIP_SPEC.md](IOT_VIP_SPEC.md) y la descripción completa del sistema en [sistema-actual.md](sistema-actual.md).

## 1. Panorama: quién habla con quién

```mermaid
flowchart LR
    subgraph Tienda["Tienda física"]
        ESP["ESP32 + RC522<br/>(lector de tarjetas)"]
        KIOSCO["Navegador del kiosco<br/>(/kiosco/caja-1/)"]
    end
    CLIENTE["Navegador del cliente<br/>(en su casa)"]
    CEL["Celular<br/>(escanea el QR)"]

    subgraph Render["Render (producción)"]
        DJANGO["Django + gunicorn<br/>apps: tienda, usuarios, iot"]
        PG[("PostgreSQL<br/>bakeandmade-db")]
    end
    S3[("AWS S3<br/>bake-and-made.bucket<br/>media/videos, media/productos, media/ingredientes")]

    ESP -- "POST /api/rfid/scan/<br/>Token IOT_DEVICE_TOKEN" --> DJANGO
    ESP -. "GET /healthz cada 10 min<br/>(que Render no se duerma)" .-> DJANGO
    KIOSCO -- "páginas + polling<br/>GET /api/iot/estado/ cada 2 s" --> DJANGO
    CLIENTE -- "tienda, carrito, checkout, /vip/" --> DJANGO
    DJANGO -- "DATABASE_URL" --> PG
    DJANGO -- "sube archivos (admin)<br/>firma URLs de 1 h" --> S3
    CEL -- "/vip/v/codigo/ → 302" --> DJANGO
    CEL -- "URL firmada del video" --> S3
```

El ESP32 **nunca** habla con el navegador: solo le dice a Django qué tarjeta leyó. El kiosco se entera preguntando cada 2 s.

## 2. Dos entornos, dos bases de datos

Una sola línea de `settings.py` decide qué base se usa: si `DATABASE_URL` tiene valor, se usa esa; si está vacía, SQLite.

```mermaid
flowchart TB
    INICIO(["Django arranca"]) --> ENV{"¿DATABASE_URL<br/>tiene valor?"}
    ENV -- "No (tu .env local)" --> SQLITE[("SQLite<br/>bakeandmade/db.sqlite3")]
    ENV -- "Sí (Render la inyecta<br/>desde render.yaml)" --> POSTGRES[("PostgreSQL de Render")]

    INICIO --> AWS{"¿AWS_STORAGE_BUCKET_NAME<br/>tiene valor?"}
    AWS -- "No (local)" --> DISCO["Disco: bakeandmade/media/"]
    AWS -- "Sí (Render)" --> BUCKET["S3, carpeta media/"]
```

| | Local (WSL) | Render |
|---|---|---|
| Base de datos | SQLite (`db.sqlite3`) | PostgreSQL (gratuito, **vence a los 30 días**) |
| Imágenes y videos | `bakeandmade/media/` | S3 (`media/`) |
| Variables | `.env` (python-dotenv) | Panel **Environment** del servicio |
| `DEBUG` | `True` | `False` |
| Usuarios demo | `python manage.py crear_usuarios_demo` | `build.sh` en cada deploy |

**Las dos bases no se sincronizan.** Lo que hagas en el admin local no aparece en Render y al revés. Por eso, en la fase 10, los usuarios demo creados en local no servían para el ESP32: él consulta la base de Render.

## 3. Del commit a producción

```mermaid
flowchart LR
    DEV["Tu máquina<br/>rama de trabajo"] -- "git push + PR" --> RA["GitHub<br/>feat/render-allocation"]
    RA -- "Render detecta el push" --> BUILD

    subgraph BUILD["build.sh (cada deploy)"]
        direction TB
        B1["pip install -r requirements.txt"] --> B2["collectstatic"]
        B2 --> B3["migrate<br/>(cambios de tablas y migraciones de datos)"]
        B3 --> B4["cargar_catalogo<br/>(crea lo que falte y<br/>completa imágenes faltantes)"]
        B4 --> B5["crear_terminal caja-1"]
        B5 --> B6["createsuperuser<br/>(si hay DJANGO_SUPERUSER_*)"]
        B6 --> B7["crear_usuarios_demo<br/>(si hay DEMO_PASSWORD y DEMO_VIP_UIDS)"]
    end

    BUILD --> RUN["gunicorn<br/>bakeandmade.wsgi"]
```

Todos los pasos del build son **idempotentes**: se pueden repetir en cada deploy sin duplicar nada. `firmware/` no participa en el despliegue; se carga a mano con `cargar.ps1` o `cargar.sh`.

## 4. Ingredientes: modelo de datos

```mermaid
erDiagram
    CategoriaIngrediente ||--o{ Ingrediente : agrupa
    Menu ||--o{ DetallesMenu : "receta"
    Ingrediente ||--o{ DetallesMenu : "forma parte de"
    Ingrediente ||--o{ CupcakeIngredientes : "se usa en"
    CupcakePersonalizado ||--o{ CupcakeIngredientes : lleva
    User ||--o{ CupcakePersonalizado : arma
    CupcakePersonalizado ||--o{ DetallePedido : "se cobra en"
    Menu ||--o{ DetallePedido : "se cobra en"
    Pedido ||--|{ DetallePedido : contiene
    User ||--o{ Pedido : hace

    CategoriaIngrediente {
        string nombre "Base, Relleno, Cobertura, Topping"
    }
    Ingrediente {
        string nombre
        decimal precio_adicional "se suma al precio del cupcake"
        bool solo_suscriptores "exclusivo del Sweet Plan"
        int stock_disponible "baja en cada checkout"
        image imagen "S3 en producción"
        bool activo "false = no aparece en el armador"
    }
    CupcakePersonalizado {
        decimal precio_calculado "precio base, sin descuento"
        json dietas
        string color_frosting
    }
    CupcakeIngredientes {
        int cantidad
    }
    DetallesMenu {
        int cantidad "porciones por unidad (cargar_catalogo)"
    }
    DetallePedido {
        int cantidad
        decimal precio_unitario "ya con descuento VIP"
    }
    Pedido {
        decimal total
        decimal descuento_porcentaje "0, 0.20 o 0.50"
        string motivo_descuento
    }
```

El checkout **nunca** cobra con los precios guardados en la sesión: `Pedido.objects.personalizados_validos()` vuelve a leer cada ingrediente de la base (precio, `activo`, stock y si es exclusivo del Sweet).

## 5. Cómo agregar o cambiar ingredientes

Hay tres caminos, y la diferencia es **en qué bases queda el cambio**:

```mermaid
flowchart TB
    Q{"¿Qué quieres hacer?"}
    Q -- "Probar rápido o ajustar<br/>solo producción" --> ADMIN
    Q -- "Ingrediente NUEVO que debe<br/>existir en todas las bases" --> CATALOGO
    Q -- "CAMBIAR uno que ya existe<br/>(precio, exclusivo, nombre)<br/>en todas las bases" --> MIGRACION

    ADMIN["<b>Admin</b><br/>/admin/ → Ingredientes → Añadir"]
    ADMIN --> A1["Queda solo en la base donde lo hiciste<br/>(Render o local)"]
    A1 --> A2["⚠ No queda en el código: si se recrea<br/>el PostgreSQL de Render, se pierde"]

    CATALOGO["<b>cargar_catalogo</b><br/>agregar una tupla a INGREDIENTES<br/>(y a INGREDIENTES_EXCLUSIVOS si es del Sweet)"]
    CATALOGO --> C1["Local: python manage.py cargar_catalogo"]
    CATALOGO --> C2["Render: se crea solo en el siguiente deploy"]
    C2 --> C3["⚠ get_or_create: si ya existe uno con esa<br/>categoría y nombre, NO lo modifica"]

    MIGRACION["<b>Migración de datos</b><br/>como tienda/migrations/0007_ingredientes_exclusivos.py"]
    MIGRACION --> M1["Se aplica una sola vez en cada base<br/>con python manage.py migrate"]
    M1 --> M2["Render la corre en build.sh"]
```

Regla práctica:

- **Ingrediente nuevo del catálogo** → agrégalo en `tienda/management/commands/cargar_catalogo.py` y haz deploy. Si ya alguien lo creó en el admin de Render con la misma categoría y nombre, no pasa nada: `get_or_create` lo encuentra y no lo duplica.
- **Cambiar precio o volver exclusivo uno que ya existe** → el admin basta si solo importa producción; si debe valer en todas las bases (incluida una nueva), escribe una migración de datos como `0007`.
- **Imagen del ingrediente** → agrega el archivo a `media/ingredientes/` (`git add -f`) y su ruta a `IMAGENES_INGREDIENTES`; el build la sube a S3. También se puede subir en el admin, y esa manda.
- **Ingredientes agregados en el admin de Render** que quieras conservar → cópialos también a `INGREDIENTES` en `cargar_catalogo.py`, para que no se pierdan si la base de Render se recrea.

## 6. Inicio de sesión con la tarjeta VIP

```mermaid
sequenceDiagram
    autonumber
    actor Cliente
    participant ESP as ESP32
    participant API as Django (/api/rfid/scan/)
    participant DB as PostgreSQL
    participant K as Navegador del kiosco

    Cliente->>ESP: acerca la tarjeta
    ESP->>API: POST {uid, terminal: caja-1}<br/>Authorization: Token ...
    API->>DB: busca TarjetaRFID y la Suscripción del dueño
    alt tarjeta activa y Sweet vigente
        API->>DB: Terminal.activar(tarjeta), version + 1
        API-->>ESP: 200 {"status": "ok", "cliente": "Ana"}
        ESP->>ESP: LED verde
    else Sweet vencido / UID desconocido / token malo
        API->>DB: 403 y 404 quedan registrados en LecturaRFID
        API-->>ESP: 403 sin_sweet / 404 desconocida / 401 token
        ESP->>ESP: LED rojo
    end
    loop cada 2 s
        K->>API: GET /api/iot/estado/
        API->>DB: ¿cambió la version de caja-1?
    end
    API-->>K: recargar: sesión de Ana iniciada<br/>(conserva carrito y terminal)
    Note over K: "Hola, Ana", pestaña VIP, carrito −20 %
    Note over K,API: 5 min sin navegar o "Salir" → sesión cerrada<br/>vía iot.sesion.sincronizar()
```

## 7. De dónde sale el descuento

```mermaid
flowchart TB
    P["Cada petición"] --> PP["tienda/peticion.py<br/>descuento_de_peticion() (una vez por petición)"]
    PP --> D["descuento_para(usuario, hoy)"]
    D --> V{"PerfilVIP.descuento_vigente()"}
    V -- "sin sesión o sin Sweet vigente" --> D0["0 %"]
    V -- "Sweet vigente" --> C{"¿es su cumpleaños hoy<br/>y no lo registró hoy?"}
    C -- "no" --> D20["20 % (VIP_DESCUENTO)"]
    C -- "sí" --> D50["50 % (VIP_DESCUENTO_CUMPLE)"]
    D20 & D50 --> AP["aplicar_descuento(precio, descuento)<br/>Decimal, redondeo por línea"]
    AP --> USO["inicio, carrito y checkout<br/>(DetallePedido.precio_unitario ya descontado)"]
```
