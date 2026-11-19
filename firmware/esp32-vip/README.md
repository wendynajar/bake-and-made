# Lector RFID del kiosco (ESP32 + RC522)

Lee la tarjeta VIP, envía su UID a `POST /api/rfid/scan/` en Render y enciende un LED verde (aceptada) o rojo (rechazada). Cada 10 minutos llama a `/healthz` para que Render no se duerma. Contrato completo en [docs/IOT_VIP_SPEC.md](../../docs/IOT_VIP_SPEC.md).

## Conexiones

| RC522 | ESP32 |
|---|---|
| SDA (SS) | GPIO 5 |
| SCK | GPIO 18 |
| MOSI | GPIO 23 |
| MISO | GPIO 19 |
| RST | GPIO 22 |
| 3.3V | 3V3 (**nunca 5 V**) |
| GND | GND |
| IRQ | sin conectar |

| LED | ESP32 |
|---|---|
| Verde (+) | GPIO 25, con resistencia de 220 Ω; (−) a GND |
| Rojo (+) | GPIO 26, con resistencia de 220 Ω; (−) a GND |

## Primer uso

1. Instala [PlatformIO](https://platformio.org/install) (extensión de VS Code o `pip install platformio`).
2. Copia la plantilla de credenciales y llénala:
   ```bash
   cd firmware/esp32-vip
   cp include/secrets.example.h include/secrets.h
   ```
   - `WIFI_SSID` / `WIFI_PASS`: red de **2.4 GHz** sin portal cautivo.
   - `API_URL`: `https://bake-and-made.onrender.com` (sin `/` final).
   - `IOT_DEVICE_TOKEN`: el mismo valor que en el panel de Render.
   - `TERMINAL`: `caja-1`.
3. Conecta el ESP32 por USB, carga el programa y abre el monitor serie:
   ```bash
   pio run -t upload
   pio device monitor
   ```
   Debe aparecer `RC522: Firmware Version: 0x92` (o `0x91`). Si sale `0x00` o `0xFF`, revisa los cables.

## Leer los UID de las 3 tarjetas

Pasa cada tarjeta y copia la línea `UID ...` del monitor serie. Funciona aunque el Wi-Fi no esté configurado todavía. Con el Wi-Fi bien configurado, las 3 deben responder `HTTP 404` (`desconocida`) porque aún no están registradas.

En Render, pon los 3 UID en `DEMO_VIP_UIDS` separados por comas, **en el orden Ana, Bruno, Carla**:

```
DEMO_VIP_UIDS=A1B2C3D4,B2C3D4E5,C3D4E5F6
```

Define también `DEMO_PASSWORD` y vuelve a desplegar: `build.sh` crea los 3 usuarios con su tarjeta y su Sweet Plan. Después, al pasar la tarjeta de Ana el LED se pone verde y el monitor muestra `HTTP 200`.

## Qué significa cada respuesta

| Monitor serie | LED | Causa |
|---|---|---|
| `HTTP 200` `{"status": "ok", ...}` | verde | Tarjeta activa de un usuario con Sweet vigente |
| `HTTP 403` `sin_sweet` | rojo | El dueño no tiene el mes del Sweet Plan pagado |
| `HTTP 404` `desconocida` | rojo | UID no registrado, sin dueño o tarjeta desactivada |
| `HTTP 401` | rojo | `IOT_DEVICE_TOKEN` distinto al de Render |
| `HTTP 400` `terminal_desconocida` | rojo | `TERMINAL` no existe (el build crea `caja-1`) |
| `HTTP -100` | rojo | Sin Wi-Fi (el lector reintenta la red cada 10 s) |
| `HTTP -101` | rojo | `API_URL` mal escrita |
| `HTTP -11` o tarda ~15 s | rojo | Timeout: Render estaba dormido; la siguiente lectura ya responde rápido |
| `HTTP -1` | rojo | Conexión rechazada: revisa `API_URL` y que el servicio esté arriba |

## Notas

- `secrets.h` está en `.gitignore`. Nunca lo subas.
- `setInsecure()` cifra la conexión pero no verifica el certificado de Render. Es aceptable para el prototipo; para producción hay que fijar la CA raíz con `setCACert()`.
- El UID de una MIFARE Classic se puede clonar: la tarjeta sirve como llave de la demo, no como autenticación fuerte.
