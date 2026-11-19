// Lector RFID del kiosco Bake & Made VIP (docs/IOT_VIP_SPEC.md, fase 10).
//
// Lee el UID de la tarjeta con el RC522, lo envía por HTTPS a
// POST /api/rfid/scan/ y enciende el LED verde (200) o rojo (cualquier otra
// respuesta). Cada 10 minutos llama a GET /healthz para que la instancia
// gratuita de Render no se duerma.
//
// El ESP32 nunca habla con el navegador: solo le dice a Django qué tarjeta leyó
// la terminal. La página del kiosco se entera por polling.

#include <Arduino.h>
#include <HTTPClient.h>
#include <MFRC522.h>
#include <SPI.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>

#include "secrets.h"  // WIFI_SSID, WIFI_PASS, API_URL, IOT_DEVICE_TOKEN, TERMINAL

// --- Pines --------------------------------------------------------------------
// RC522 en el SPI por defecto del ESP32: SCK 18, MISO 19, MOSI 23.
constexpr uint8_t PIN_RC522_SS = 5;
constexpr uint8_t PIN_RC522_RST = 22;
// LEDs con resistencia de 220 Ω a GND.
constexpr uint8_t PIN_LED_VERDE = 25;
constexpr uint8_t PIN_LED_ROJO = 26;

// --- Tiempos (ms) -------------------------------------------------------------
constexpr unsigned long PING_MS = 10UL * 60UL * 1000UL;  // /healthz cada 10 min
constexpr unsigned long ANTIRREBOTE_MS = 3000;           // misma tarjeta: ignorar 3 s
constexpr unsigned long LED_MS = 1500;                   // tiempo encendido del LED
constexpr unsigned long REINTENTO_WIFI_MS = 10000;       // reconectar Wi-Fi cada 10 s
constexpr unsigned long ESPERA_WIFI_INICIAL_MS = 20000;  // no bloquear el arranque
constexpr uint16_t TIMEOUT_HTTP_MS = 15000;              // Render puede tardar si despierta

// Códigos propios; los negativos de -1 a -11 son de HTTPClient (p. ej. -11 = timeout).
constexpr int SIN_WIFI = -100;
constexpr int URL_INVALIDA = -101;

MFRC522 rfid(PIN_RC522_SS, PIN_RC522_RST);

String ultimoUid;
unsigned long ultimoMs = 0;
unsigned long ultimoPing = 0;
unsigned long ultimoIntentoWifi = 0;
unsigned long ledApagarEn = 0;

// UID en hexadecimal y mayúsculas, sin separadores (4, 7 o 10 bytes).
String leerUid() {
  String uid;
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) {
      uid += "0";
    }
    uid += String(rfid.uid.uidByte[i], HEX);
  }
  uid.toUpperCase();
  return uid;
}

void encenderLed(bool exito) {
  digitalWrite(PIN_LED_VERDE, exito ? HIGH : LOW);
  digitalWrite(PIN_LED_ROJO, exito ? LOW : HIGH);
  ledApagarEn = millis() + LED_MS;
}

void apagarLedSiToca() {
  if (ledApagarEn != 0 && (long)(millis() - ledApagarEn) >= 0) {
    digitalWrite(PIN_LED_VERDE, LOW);
    digitalWrite(PIN_LED_ROJO, LOW);
    ledApagarEn = 0;
  }
}

// Reintenta el Wi-Fi sin bloquear: el lector sigue imprimiendo UIDs aunque no haya red
// (así se pueden leer las 3 tarjetas antes de configurar el Wi-Fi).
void mantenerWifi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }
  if (millis() - ultimoIntentoWifi >= REINTENTO_WIFI_MS) {
    ultimoIntentoWifi = millis();
    Serial.println("Wi-Fi desconectado; reintentando...");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASS);
  }
}

// Petición HTTPS a Django. Devuelve el código HTTP, o un número negativo si no hubo conexión.
int peticion(const char* metodo, const String& ruta, const String& cuerpo) {
  if (WiFi.status() != WL_CONNECTED) {
    return SIN_WIFI;
  }
  WiFiClientSecure cliente;
  // Prototipo: cifra pero no verifica el certificado. Para producción, fijar la
  // CA raíz de Render con cliente.setCACert(...).
  cliente.setInsecure();

  HTTPClient http;
  http.setTimeout(TIMEOUT_HTTP_MS);
  if (!http.begin(cliente, String(API_URL) + ruta)) {
    return URL_INVALIDA;
  }
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Token ") + IOT_DEVICE_TOKEN);

  int codigo = (strcmp(metodo, "POST") == 0) ? http.POST(cuerpo) : http.GET();
  if (codigo > 0) {
    Serial.printf("  respuesta: %s\n", http.getString().c_str());
  }
  http.end();
  return codigo;
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED_VERDE, OUTPUT);
  pinMode(PIN_LED_ROJO, OUTPUT);

  SPI.begin();
  rfid.PCD_Init();
  Serial.print("RC522: ");
  rfid.PCD_DumpVersionToSerial();  // "0x92" o "0x91" = lector conectado bien

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  ultimoIntentoWifi = millis();
  Serial.printf("Conectando a \"%s\"", WIFI_SSID);
  while (WiFi.status() != WL_CONNECTED && millis() - ultimoIntentoWifi < ESPERA_WIFI_INICIAL_MS) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("Wi-Fi OK, IP %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("Sin Wi-Fi por ahora: los UID se imprimen igual y se reintenta la red.");
  }
  Serial.printf("Terminal %s lista. Pasa una tarjeta.\n", TERMINAL);
}

void loop() {
  mantenerWifi();
  apagarLedSiToca();

  // Mantiene despierta la instancia gratuita de Render (750 h/mes alcanzan para un servicio).
  if (millis() - ultimoPing >= PING_MS) {
    ultimoPing = millis();
    Serial.printf("healthz -> %d\n", peticion("GET", "/healthz", ""));
  }

  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) {
    return;
  }

  String uid = leerUid();
  if (uid == ultimoUid && millis() - ultimoMs < ANTIRREBOTE_MS) {
    rfid.PICC_HaltA();
    return;
  }
  ultimoUid = uid;
  ultimoMs = millis();

  // Esta línea es la que se copia a DEMO_VIP_UIDS.
  Serial.printf("UID %s\n", uid.c_str());

  String cuerpo = String("{\"uid\":\"") + uid + "\",\"terminal\":\"" + TERMINAL + "\"}";
  int codigo = peticion("POST", "/api/rfid/scan/", cuerpo);
  if (codigo < 0 && codigo != SIN_WIFI) {
    codigo = peticion("POST", "/api/rfid/scan/", cuerpo);  // un reintento (p. ej. Render despertando)
  }
  Serial.printf("  HTTP %d\n", codigo);
  encenderLed(codigo == 200);

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
}
