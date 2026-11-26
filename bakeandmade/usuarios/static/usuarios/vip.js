/*
 * Página VIP: registro del cumpleaños (con aviso), calendario y borrado de fechas.
 * Habla con /api/vip/fechas/ y /api/vip/cumpleanios/ usando la sesión y el token CSRF.
 */
(function () {
    'use strict';

    var raiz = document.getElementById('vip');
    if (!raiz) {
        return;
    }

    var URL_FECHAS = raiz.dataset.urlFechas;
    var URL_CUMPLE = raiz.dataset.urlCumpleanios;
    var CSRF = raiz.dataset.csrf;

    var MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
        'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

    // --- Utilidades ----------------------------------------------------------

    function pedir(url, metodo, datos) {
        return fetch(url, {
            method: metodo,
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
            body: datos ? JSON.stringify(datos) : undefined
        });
    }

    function mostrarError(id, texto) {
        var nodo = document.getElementById(id);
        nodo.textContent = texto;
        nodo.hidden = !texto;
    }

    function primerError(cuerpo) {
        if (cuerpo && cuerpo.error) {
            return cuerpo.error;
        }
        if (cuerpo && cuerpo.errores) {
            var claves = Object.keys(cuerpo.errores);
            return claves.length ? cuerpo.errores[claves[0]][0] : '';
        }
        return 'No se pudo guardar. Inténtalo de nuevo.';
    }

    /* Diálogo propio de confirmación; resuelve true con "Sí" y false con "Cancelar" o Esc. */
    function confirmar(texto, textoBoton) {
        var dialogo = document.getElementById('dialogo');
        document.getElementById('dialogo-texto').textContent = texto;
        document.getElementById('dialogo-confirmar').textContent = textoBoton;
        return new Promise(function (resolver) {
            function cerrar(respuesta) {
                dialogo.removeEventListener('click', alHacerClic);
                dialogo.removeEventListener('cancel', alCancelar);
                dialogo.close();
                resolver(respuesta);
            }
            function alHacerClic(evento) {
                var respuesta = evento.target.dataset.respuesta;
                if (respuesta) {
                    cerrar(respuesta === 'si');
                }
            }
            function alCancelar(evento) {
                evento.preventDefault();
                cerrar(false);
            }
            dialogo.addEventListener('click', alHacerClic);
            dialogo.addEventListener('cancel', alCancelar);
            dialogo.showModal();
        });
    }

    // --- Cumpleaños ----------------------------------------------------------

    var formCumple = document.getElementById('form-cumple');
    if (formCumple) {
        formCumple.addEventListener('submit', function (evento) {
            evento.preventDefault();
            var valor = document.getElementById('fecha-cumple').value;
            if (!valor) {
                mostrarError('error-cumple', 'Elige tu fecha de nacimiento.');
                return;
            }
            mostrarError('error-cumple', '');
            var partes = valor.split('-');
            var legible = parseInt(partes[2], 10) + ' de ' + MESES[parseInt(partes[1], 10) - 1];

            confirmar(
                'Vas a registrar el ' + legible + ' como tu cumpleaños. ' +
                'Después no podrás cambiarlo. ¿Confirmas?',
                'Sí, guardar'
            ).then(function (si) {
                if (!si) {
                    return;
                }
                pedir(URL_CUMPLE, 'POST', { fecha: valor }).then(function (respuesta) {
                    if (respuesta.status === 201) {
                        window.location.reload();
                        return;
                    }
                    respuesta.json().then(function (cuerpo) {
                        mostrarError('error-cumple', primerError(cuerpo));
                    });
                });
            });
        });
    }

    // --- Calendario ----------------------------------------------------------

    var nodoCalendario = document.getElementById('calendario');
    if (!nodoCalendario || !window.FullCalendar) {
        if (nodoCalendario) {
            nodoCalendario.textContent = 'No se pudo cargar el calendario. Recarga la página.';
        }
        return;
    }

    var calendario = new window.FullCalendar.Calendar(nodoCalendario, {
        initialView: 'dayGridMonth',
        locale: 'es',
        height: 'auto',
        headerToolbar: { left: 'prev,next today', center: 'title', right: '' },
        buttonText: { today: 'Hoy' },
        events: URL_FECHAS,
        eventClick: function (info) {
            if (!info.event.extendedProps.borrable) {
                return;
            }
            confirmar('¿Borrar "' + info.event.title + '" de tu calendario?', 'Sí, borrar')
                .then(function (si) {
                    if (!si) {
                        return;
                    }
                    pedir(URL_FECHAS + info.event.id + '/', 'DELETE').then(function () {
                        calendario.refetchEvents();
                    });
                });
        }
    });
    calendario.render();

    document.getElementById('form-fecha').addEventListener('submit', function (evento) {
        evento.preventDefault();
        var datos = {
            nombre_evento: document.getElementById('nombre-evento').value,
            fecha_evento: document.getElementById('fecha-evento').value,
            tipo: document.getElementById('tipo-evento').value
        };
        pedir(URL_FECHAS, 'POST', datos).then(function (respuesta) {
            if (respuesta.status === 201) {
                mostrarError('error-fecha', '');
                evento.target.reset();
                calendario.refetchEvents();
                return;
            }
            respuesta.json().then(function (cuerpo) {
                mostrarError('error-fecha', primerError(cuerpo));
            });
        });
    });
}());
