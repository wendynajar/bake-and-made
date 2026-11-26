/*
 * Polling del kiosco (docs/IOT_VIP_SPEC.md, sección Frontend).
 *
 * Cada IOT_POLL_SEGUNDOS pregunta a /api/iot/estado/. Esa petición es la que
 * inicia o cierra la sesión según la tarjeta que leyó el ESP32; aquí solo se
 * redibuja la página cuando el servidor lo pide y se muestran los avisos.
 */
(function () {
    'use strict';

    var config = document.getElementById('kiosco');
    if (!config) {
        return;
    }

    var URL_ESTADO = config.dataset.estadoUrl;
    var URL_SALIR = config.dataset.salirUrl;
    var CSRF = config.dataset.csrf;
    var POLL_MS = parseInt(config.dataset.pollMs, 10) || 2000;
    var AVISO_MS = 3000;

    var versionVista = parseInt(config.dataset.version, 10) || 0;
    var ocupado = false;

    var AVISOS = {
        desconocida: 'Tarjeta no registrada.',
        sin_sweet: 'Tu Sweet Plan venció. Renuévalo para usar tu tarjeta.'
    };

    function mostrarAviso(texto, alTerminar) {
        var aviso = document.getElementById('kiosco-aviso');
        aviso.textContent = texto;
        aviso.hidden = false;
        window.setTimeout(function () {
            aviso.hidden = true;
            if (alTerminar) {
                alTerminar();
            }
        }, AVISO_MS);
    }

    function recargar() {
        window.location.reload();
    }

    function consultar() {
        if (ocupado) {
            return;
        }
        ocupado = true;
        fetch(URL_ESTADO, { credentials: 'same-origin', cache: 'no-store' })
            .then(function (respuesta) {
                return respuesta.ok ? respuesta.json() : null;
            })
            .then(function (estado) {
                if (!estado) {
                    return;
                }
                var cambio = estado.version !== versionVista;
                versionVista = estado.version;

                if (cambio && estado.rechazo && AVISOS[estado.rechazo]) {
                    // El aviso se lee completo antes de redibujar la página.
                    mostrarAviso(AVISOS[estado.rechazo], estado.recargar ? recargar : null);
                } else if (estado.recargar || cambio) {
                    recargar();
                }
            })
            .catch(function () {
                // Sin red o Render despertando: se reintenta en el siguiente ciclo.
            })
            .finally(function () {
                ocupado = false;
            });
    }

    function salir() {
        fetch(URL_SALIR, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-CSRFToken': CSRF }
        }).finally(recargar);
    }

    var botonSalir = document.getElementById('kiosco-salir');
    if (botonSalir) {
        botonSalir.addEventListener('click', salir);
    }

    window.setInterval(consultar, POLL_MS);
}());
