// Plantilla de credenciales del lector. Cópiala a secrets.h (está en .gitignore)
// y llena los valores. Nunca subas secrets.h al repositorio.
#pragma once

// Red Wi-Fi de la tienda: solo 2.4 GHz y sin portal cautivo.
#define WIFI_SSID "nombre-de-la-red"
#define WIFI_PASS "clave-de-la-red"

// URL del servicio en Render, sin "/" al final.
#define API_URL "https://bake-and-made.onrender.com"

// Mismo valor que la variable IOT_DEVICE_TOKEN en el panel de Render.
#define IOT_DEVICE_TOKEN "pega-aqui-el-token"

// Código de la terminal (python manage.py crear_terminal caja-1).
#define TERMINAL "caja-1"
