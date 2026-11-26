<#
.SYNOPSIS
    Compila y carga el firmware del lector RFID desde Windows (PowerShell).

.DESCRIPTION
    PlatformIO se cuelga al compilar sobre rutas UNC como \\wsl.localhost\...,
    así que este script copia el proyecto a una carpeta local de Windows
    (%LOCALAPPDATA%\bake-and-made\esp32-vip), compila ahí, carga el programa al
    ESP32 y abre el monitor serie. La copia conserva la carpeta .pio entre
    ejecuciones, así que a partir de la segunda vez compila mucho más rápido.

    No influye en el despliegue de Render: build.sh solo usa bakeandmade/.

.PARAMETER Puerto
    Puerto COM del ESP32. Si se omite, se detecta el adaptador USB-serie
    (CP210x o CH340).

.PARAMETER SoloCompilar
    Compila sin cargar a la placa (sirve para revisar errores sin el ESP32).

.PARAMETER SinMonitor
    Carga el programa pero no abre el monitor serie al terminar.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\cargar.ps1
    powershell -ExecutionPolicy Bypass -File .\cargar.ps1 -Puerto COM7
#>
param(
    [string]$Puerto = '',
    [switch]$SoloCompilar,
    [switch]$SinMonitor
)

$ErrorActionPreference = 'Stop'
$origen = $PSScriptRoot
$destino = Join-Path $env:LOCALAPPDATA 'bake-and-made\esp32-vip'

function Invoke-Pio {
    <# Ejecuta PlatformIO con el Python de Windows y falla si devuelve error. #>
    param([string[]]$Argumentos)
    & python -m platformio @Argumentos
    if ($LASTEXITCODE -ne 0) {
        throw "PlatformIO terminó con error ($LASTEXITCODE)."
    }
}

function Find-PuertoEsp32 {
    <# Devuelve el COM del adaptador USB-serie del ESP32, o $null si no hay ninguno. #>
    $puertos = Get-CimInstance Win32_PnPEntity |
        Where-Object { $_.Name -match '(CP210|CH34|USB-SERIAL|UART).*\((COM\d+)\)' } |
        ForEach-Object { if ($_.Name -match '\((COM\d+)\)') { $Matches[1] } }
    return @($puertos) | Select-Object -First 1
}

# 1. Requisitos
& python -m platformio --version *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'No se encontró PlatformIO. Instálalo con: python -m pip install platformio'
}
if (-not (Test-Path (Join-Path $origen 'include\secrets.h'))) {
    throw 'Falta include\secrets.h. Copia include\secrets.example.h a include\secrets.h y llena tus valores.'
}

# 2. Copia local (robocopy /MIR deja src e include idénticos al repo; .pio se conserva)
Write-Host "Copiando el firmware a $destino ..."
New-Item -ItemType Directory -Force $destino | Out-Null
Copy-Item (Join-Path $origen 'platformio.ini') $destino -Force
foreach ($carpeta in 'src', 'include') {
    robocopy (Join-Path $origen $carpeta) (Join-Path $destino $carpeta) /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy no pudo copiar $carpeta (código $LASTEXITCODE)."
    }
}

Push-Location $destino
try {
    # 3. Compilar
    if ($SoloCompilar) {
        Invoke-Pio @('run')
        Write-Host 'Compilado. No se cargó a la placa (-SoloCompilar).' -ForegroundColor Green
        return
    }

    # 4. Puerto
    if (-not $Puerto) {
        $Puerto = Find-PuertoEsp32
        if (-not $Puerto) {
            throw 'No se encontró el ESP32. Conéctalo por USB o indica el puerto: -Puerto COM7'
        }
    }
    Write-Host "Cargando a $Puerto (si se queda en 'Connecting...', mantén presionado BOOT) ..."

    # 5. Cargar
    try {
        Invoke-Pio @('run', '-t', 'upload', '--upload-port', $Puerto)
    } catch {
        Write-Host ''
        Write-Host "No se pudo cargar a $Puerto. Revisa:" -ForegroundColor Yellow
        Write-Host '  - Que no haya un monitor serie abierto (este script, Arduino IDE o VS Code).'
        Write-Host '  - Que la placa no esté conectada a WSL con usbipd (usbipd detach --busid <id>).'
        Write-Host '  - El cable USB: algunos solo cargan y no transmiten datos.'
        throw
    }

    # 6. Monitor serie
    if (-not $SinMonitor) {
        Write-Host 'Monitor serie abierto. Pasa una tarjeta; sal con Ctrl+C.' -ForegroundColor Green
        Invoke-Pio @('device', 'monitor', '--port', $Puerto)
    }
} finally {
    Pop-Location
}
