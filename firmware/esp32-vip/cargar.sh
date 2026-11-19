#!/usr/bin/env bash
# Compila y carga el firmware del lector RFID desde WSL o Linux.
#
# En WSL la ruta del proyecto es nativa de Linux, así que PlatformIO compila
# directo aquí; lo único que falta es pasarle el USB a WSL con usbipd-win
# (el script lo explica si no encuentra la placa). No influye en el despliegue
# de Render: build.sh solo usa bakeandmade/.
#
# Uso:
#   ./cargar.sh                       # detecta /dev/ttyUSB* o /dev/ttyACM*
#   ./cargar.sh --puerto /dev/ttyUSB0
#   ./cargar.sh --solo-compilar       # sin placa: solo revisa que compile
#   ./cargar.sh --sin-monitor         # carga y no abre el monitor serie
set -o errexit
set -o pipefail
set -o nounset

cd "$(dirname "$0")"

puerto=""
solo_compilar=false
sin_monitor=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --puerto) puerto="${2:?Falta el valor de --puerto}"; shift 2 ;;
    --solo-compilar) solo_compilar=true; shift ;;
    --sin-monitor) sin_monitor=true; shift ;;
    *) echo "Opción desconocida: $1" >&2; exit 2 ;;
  esac
done

# 1. Requisitos
if command -v pio >/dev/null 2>&1; then
  pio=(pio)
elif python3 -m platformio --version >/dev/null 2>&1; then
  pio=(python3 -m platformio)
else
  echo "No se encontró PlatformIO. Instálalo con: pipx install platformio" >&2
  echo "(no lo agregues a requirements.txt: Render no lo necesita)." >&2
  exit 1
fi
if [[ ! -f include/secrets.h ]]; then
  echo "Falta include/secrets.h. Copia include/secrets.example.h a include/secrets.h y llena tus valores." >&2
  exit 1
fi

# 2. Compilar
if $solo_compilar; then
  "${pio[@]}" run
  echo "Compilado. No se cargó a la placa (--solo-compilar)."
  exit 0
fi

# 3. Puerto
if [[ -z "$puerto" ]]; then
  puerto=$(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null | head -n 1 || true)
fi
if [[ -z "$puerto" || ! -e "$puerto" ]]; then
  cat >&2 <<'EOF'
No se encontró el ESP32 en WSL. WSL no ve los puertos USB de Windows por defecto;
en PowerShell como administrador:

  usbipd list                       # busca el BUSID del CP210x o CH340, p. ej. 1-5
  usbipd bind --busid 1-5           # solo la primera vez
  usbipd attach --wsl --busid 1-5   # cada vez que conectes la placa

Para regresarla a Windows: usbipd detach --busid 1-5
EOF
  exit 1
fi
if [[ ! -r "$puerto" || ! -w "$puerto" ]]; then
  echo "Sin permiso sobre $puerto. Ejecuta: sudo usermod -aG dialout \$USER" >&2
  echo "y reinicia WSL (en PowerShell: wsl --shutdown)." >&2
  exit 1
fi

# 4. Cargar
echo "Cargando a $puerto (si se queda en 'Connecting...', mantén presionado BOOT) ..."
if ! "${pio[@]}" run -t upload --upload-port "$puerto"; then
  echo "" >&2
  echo "No se pudo cargar a $puerto. Revisa que no haya un monitor serie abierto" >&2
  echo "y que el cable USB transmita datos." >&2
  exit 1
fi

# 5. Monitor serie
if ! $sin_monitor; then
  echo "Monitor serie abierto. Pasa una tarjeta; sal con Ctrl+C."
  "${pio[@]}" device monitor --port "$puerto"
fi
