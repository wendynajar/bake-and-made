document.documentElement.classList.add("js-ready");

document.addEventListener("DOMContentLoaded", () => {

    // Animaciones al desplazarse
    const elementos = document.querySelectorAll(".reveal");

    if ("IntersectionObserver" in window) {
        const observer = new IntersectionObserver(
            (entradas) => {
                entradas.forEach((entrada) => {
                    if (entrada.isIntersecting) {
                        entrada.target.classList.add("visible");
                        observer.unobserve(entrada.target);
                    }
                });
            },
            {
                threshold: 0.08,
                rootMargin: "0px 0px 40px 0px"
            }
        );

        elementos.forEach((elemento) => {
            observer.observe(elemento);
        });
    } else {
        elementos.forEach((elemento) => {
            elemento.classList.add("visible");
        });
    }

    // Encabezado con efecto al hacer scroll
    const header = document.querySelector(".premium-header");

    function actualizarHeader() {
        if (header) {
            header.classList.toggle(
                "scrolled",
                window.scrollY > 30
            );
        }
    }

    window.addEventListener("scroll", actualizarHeader, {
        passive: true
    });

    actualizarHeader();

    // Menú móvil
    const botonMenu = document.querySelector(
        ".mobile-menu-toggle"
    );

    const navegacion = document.querySelector(
        ".premium-nav"
    );

    if (botonMenu && navegacion) {
        botonMenu.addEventListener("click", () => {
            const abierto = navegacion.classList.toggle("open");

            botonMenu.setAttribute(
                "aria-expanded",
                String(abierto)
            );
        });

        navegacion.querySelectorAll("a").forEach((enlace) => {
            enlace.addEventListener("click", () => {
                navegacion.classList.remove("open");

                botonMenu.setAttribute(
                    "aria-expanded",
                    "false"
                );
            });
        });
    }

});


/* Notificaciones que desaparecen automáticamente */
document.addEventListener("DOMContentLoaded", function () {
    const notificaciones = document.querySelectorAll(".cart-messages");

    notificaciones.forEach(function (contenedor) {
        setTimeout(function () {
            contenedor.style.transition = "opacity 0.6s ease, transform 0.6s ease";
            contenedor.style.opacity = "0";
            contenedor.style.transform = "translateX(30px)";
            contenedor.style.pointerEvents = "none";

            setTimeout(function () {
                contenedor.remove();
            }, 600);
        }, 3500);
    });
});

