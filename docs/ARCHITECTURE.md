# Arquitectura del Sistema - Bake & Made VIP Experience

> Este documento es la **visión y las reglas** del proyecto, y manda sobre todo lo demás. Cómo quedó implementado está en [sistema-actual.md](sistema-actual.md), y el orden en que se hizo en [historial-de-cambios.md](historial-de-cambios.md).

## 1. Visión General
Este documento define la arquitectura, decisiones de diseño y flujo de ciclo de vida para el proyecto "Bake & Made VIP". El sistema integra hardware IoT (ESP32 + RFID) con una plataforma de comercio electrónico dinámica (Django), permitiendo una experiencia O2O (Online-to-Offline) donde interacciones físicas desencadenan cambios en tiempo real en la interfaz web (descuentos, calendarios y contenido multimedia interactivo).

---

## 2. Diagrama de Arquitectura de Alto Nivel

El sistema se compone de cuatro capas principales:

1.  **Capa Física (Hardware):** Lector RFID RC522 acoplado a un microcontrolador ESP32.
2.  **Capa Lógica (Backend):** API REST y renderizado de plantillas desarrollado en Python/Django.
3.  **Capa de Persistencia (Datos y Medios):** Base de datos PostgreSQL para datos relacionales y AWS S3 para archivos estáticos/multimedia.
4.  **Capa de Interfaz (Frontend):** HTML/CSS/Vanilla JS operando bajo un esquema de Short-Polling.

---

## 3. Decisiones de Diseño y Fundamentación (Elegibilidad)

Para mantener el repositorio limpio y alineado con los requerimientos, se han tomado las siguientes decisiones arquitectónicas:

*   **Django como framework Monolítico + API:** Se elige Django por su robusto ORM, que mapea perfectamente el modelo relacional (Usuarios, Suscripciones, Pedidos, Menú). Se usará para servir las vistas HTML y exponer un único endpoint `/api/rfid/scan/` para el hardware.
*   **Polling (Vanilla JS) vs WebSockets:** Para la sincronización de estado web, se utilizará *Polling* (consultas HTTP GET cada 3-5 segundos desde el cliente) en lugar de WebSockets. *Implementado:* cada 2 s (`IOT_POLL_SEGUNDOS`), para que el inicio de sesión por tarjeta tarde 4 s o menos (ver IOT_VIP_SPEC.md).
    *   *Fundamento:* Simplifica drásticamente el despliegue en infraestructuras Serverless/PaaS como Render, evitando la complejidad de mantener conexiones persistentes (ASGI/Redis), ideal para la escala actual del proyecto.
*   **Despliegue en Render (PaaS):** 
    *   *Fundamento:* Permite integración CI/CD directa con GitHub. Ofrece PostgreSQL administrado y gestión automática de certificados SSL (HTTPS), requisito indispensable para las peticiones del ESP32.
*   **Almacenamiento en AWS S3:** 
    *   *Fundamento:* El sistema de archivos de Render es efímero (se borra en cada despliegue). Los videos generados para códigos QR y archivos estáticos (CSS/JS mediante WhiteNoise) deben externalizarse para garantizar persistencia y rendimiento.

---

## 4. Guías de Código Limpio (Optimizado para Claude Code / AI Agents)

Para que los agentes de IA y los desarrolladores puedan leer, mantener y escalar el código eficientemente, el repositorio debe adherirse a las siguientes reglas:

*   **Modularidad de Aplicaciones (Django Apps):** Separar responsabilidades lógicas. Ejemplo: `tienda` (productos, carritos), `usuarios` (autenticación, perfiles VIP), `iot` (endpoints para el ESP32).
*   **Tipado Estático (Type Hinting):** Usar sugerencias de tipos en Python para todas las funciones y métodos (ej. `def procesar_rfid(uid: str) -> dict:`). Esto mejora drásticamente la capacidad de análisis estático del código por parte de la IA.
*   **Docstrings (PEP 257):** Cada clase, modelo y función debe tener un docstring que explique su *qué* y *por qué*, no solo el *cómo*.
*   **Gestión de Entornos (Separation of Concerns):** El archivo `settings.py` debe leer variables de entorno (usando `python-dotenv`) para credenciales. Nunca hacer *hardcode* de claves de AWS, bases de datos o UIDs de tarjetas.
*   **Fat Models, Skinny Views:** La lógica de negocio (ej. calcular si un usuario tiene descuento de cumpleaños) debe residir en los métodos de los Modelos de Django, manteniendo las Vistas (Views) únicamente para el manejo de peticiones HTTP.

---

## 5. Flujo de Ciclo de Vida del Desarrollo

El desarrollo se divide en cuatro fases secuenciales.

> En la práctica, la capa VIP/RFID se construyó en las fases 0 a 11 de [IOT_VIP_SPEC.md](IOT_VIP_SPEC.md#fases-para-claude-code), que recorren estas cuatro: modelos y contrato de la API (fases 0, 1 y 4), construcción (2 a 8 y 10), pruebas (los tests de cada fase) y despliegue (9 y 11). Las cuatro están hechas; de la prueba en producción faltan 3 pruebas manuales.

### Fase 1: Planteamiento (Planning)
*   **Diseño de Base de Datos:** Traducción del diagrama ER a modelos de Django.
*   **Mapeo de Hardware:** Asignación física de pines SPI en el ESP32 y registro temporal de los 3 UIDs de tarjetas VIP en el sistema.
*   **Definición de Contratos (API):** Establecer la estructura del JSON que el ESP32 enviará a Django.

### Fase 2: Construcción (Building)
*   **Backend:** Implementación de modelos, endpoints API protegidos por tokens estáticos, y vistas de sesión VIP.
*   **Frontend:** Desarrollo de la interfaz e integración de la lógica de *Polling* en JavaScript para escuchar cambios de sesión.
*   **Hardware (C++):** Programación del ESP32 usando `MFRC522.h` y `HTTPClient.h` para enviar los UIDs.
*   **Medios:** Configuración de `django-storages` y conexión con bucket de S3.

### Fase 3: Pruebas (Testing)
*   **Pruebas Unitarias:** Creación de tests en Django (`pytest` o `unittest`) para la lógica de descuentos y validación de UIDs.
*   **Pruebas de Integración (Postman/Curl):** Simular peticiones del ESP32 hacia el endpoint de Django localmente para asegurar el cambio de estado.
*   **Pruebas de Hardware:** Uso del monitor serie para validar la correcta conexión a la red Wi-Fi y el envío de payloads al pasar el llavero físico.

### Fase 4: Despliegue (Deployment)
*   **Preparación de Entorno:** Configuración de `requirements.txt`, script `gunicorn`, y adaptación de WhiteNoise para estáticos.
*   **CI/CD Pipeline:** Conexión del repositorio de GitHub con Render.
*   **Provisión de Servicios:** Creación de la base de datos PostgreSQL en Render y ejecución de migraciones (`python manage.py migrate`).
*   **Prueba en Producción (Smoke Test):** Pase físico de la tarjeta sobre el módulo RFID y verificación del cambio dinámico en la URL de producción (HTTPS).