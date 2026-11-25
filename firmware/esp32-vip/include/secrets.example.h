// Plantilla de credenciales del lector. Cópiala a secrets.h (está en .gitignore)
// y llena los valores. Nunca subas secrets.h al repositorio.
#pragma once

// Redes Wi-Fi conocidas, {"nombre", "clave"}: solo 2.4 GHz y sin portal cautivo.
// El lector se conecta a la de mejor señal. La primera es el hotspot del celular:
// configúralo con este mismo nombre y clave y no habrá que volver a cargar el
// firmware al cambiar de lugar. Nombre: máximo 31 caracteres. Clave: de 8 a 63.
#define WIFI_REDES {"BakeMade-IoT", "cambia-esta-clave"}

// Con más redes, sepáralas con comas (pon solo redes reales, sin ejemplos):
// #define WIFI_REDES {"BakeMade-IoT", "cambia-esta-clave"}, {"red-de-casa", "su-clave"}

// URL del servicio en Render, sin "/" al final.
#define API_URL "https://bake-and-made.onrender.com"

// Mismo valor que la variable IOT_DEVICE_TOKEN en el panel de Render.
#define IOT_DEVICE_TOKEN "pega-aqui-el-token"

// Código de la terminal (python manage.py crear_terminal caja-1).
#define TERMINAL "caja-1"
