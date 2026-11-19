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
3. Conecta el ESP32 por USB y usa el script de tu entorno (ver [Cargar el programa](#cargar-el-programa)). Compila, carga el programa y abre el monitor serie.

   Debe aparecer `RC522: Firmware Version: 0x92` (o `0x91`). Si sale `0x00` o `0xFF`, revisa los cables.

## Cargar el programa

El firmware **no forma parte del despliegue en Render**: `build.sh` solo usa `bakeandmade/`. Estos scripts solo se ejecutan en la computadora que tiene el ESP32 conectado.

### Desde Windows (PowerShell): `cargar.ps1`

```powershell
cd \\wsl.localhost\Ubuntu\home\<usuario>\bake-and-made\bake-and-made\firmware\esp32-vip
powershell -ExecutionPolicy Bypass -File .\cargar.ps1              # detecta el COM del ESP32
powershell -ExecutionPolicy Bypass -File .\cargar.ps1 -Puerto COM7
powershell -ExecutionPolicy Bypass -File .\cargar.ps1 -SoloCompilar
```

Requiere PlatformIO en el Python de Windows (`python -m pip install platformio`).

**Por qué un script:** si el repo vive en WSL, la ruta del proyecto es `\\wsl.localhost\...` (una ruta de red), y PlatformIO se cuelga al compilar ahí sin mostrar ningún error: se queda en `Processing esp32dev`. Eso pasa aunque se ejecute desde PowerShell. El script copia `src/`, `include/` y `platformio.ini` a `%LOCALAPPDATA%\bake-and-made\esp32-vip` y compila ahí. Esa copia incluye `secrets.h`: no la subas a ningún repositorio.

### Desde WSL o Linux: `cargar.sh`

```bash
cd firmware/esp32-vip
./cargar.sh                          # detecta /dev/ttyUSB* o /dev/ttyACM*
./cargar.sh --puerto /dev/ttyUSB0
./cargar.sh --solo-compilar
```

Requiere PlatformIO en WSL (`pipx install platformio`; no va en `requirements.txt`). En WSL la ruta es nativa y compila directo, pero WSL no ve el USB de Windows. Hay que pasárselo con [usbipd-win](https://github.com/dorssel/usbipd-win), en PowerShell como administrador:

```powershell
usbipd list                       # BUSID del "Silicon Labs CP210x" o "CH340", p. ej. 1-5
usbipd bind --busid 1-5           # solo la primera vez
usbipd attach --wsl --busid 1-5   # cada vez que conectes la placa
usbipd detach --busid 1-5         # para regresarla a Windows
```

Mientras la placa está en WSL, Windows no ve su COM, y al revés. Si no tienes permiso sobre el puerto: `sudo usermod -aG dialout $USER` y luego `wsl --shutdown`.

### Si la carga falla

| Síntoma | Causa |
|---|---|
| Se queda en `Processing esp32dev` sin avanzar | Se compila sobre `\\wsl.localhost\...`: usa `cargar.ps1` |
| `Could not open COM7, the port doesn't exist` (aunque el puerto exista) | Otro programa tiene el puerto abierto: cierra el monitor serie (terminal, Arduino IDE o VS Code) |
| Se queda en `Connecting.....` | Mantén presionado **BOOT** hasta que empiece `Writing at 0x...` |
| El monitor muestra textos que no son `UID ...`, `HTTP ...` | La placa tiene otro programa: la carga no terminó; repítela hasta ver `[SUCCESS]` |

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
