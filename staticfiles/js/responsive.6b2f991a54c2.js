(function () {
    const DESKTOP_BREAKPOINT = 1200;

    const body = document.body;
    const sidebar = document.querySelector(".sidebar");
    const toggle = document.querySelector(".sidebar-toggle");
    const publicToggle = document.querySelector(".public-nav-toggle");
    const publicNav = document.querySelector(".public-navbar .navbar-nav");

    let overlay = document.querySelector(".sidebar-overlay");

    if (!overlay) {
        overlay = document.createElement("div");
        overlay.className = "sidebar-overlay";
        overlay.setAttribute("aria-hidden", "true");
        document.body.appendChild(overlay);
    }

    function openSidebar() {
        body.classList.add("sidebar-open");
        overlay.classList.add("show");
        if (toggle) toggle.setAttribute("aria-expanded", "true");
    }

    function closeSidebar() {
        body.classList.remove("sidebar-open");
        overlay.classList.remove("show");
        if (toggle) toggle.setAttribute("aria-expanded", "false");
    }

    if (sidebar && toggle) {
        toggle.addEventListener("click", function () {
            if (body.classList.contains("sidebar-open")) {
                closeSidebar();
            } else {
                openSidebar();
            }
        });

        const closeButton = sidebar.querySelector(".sidebar-close");
        if (closeButton) {
            closeButton.addEventListener("click", closeSidebar);
        }

        sidebar.querySelectorAll(".sidebar-menu a").forEach(function (link) {
            link.addEventListener("click", function () {
                if (window.innerWidth < DESKTOP_BREAKPOINT) {
                    closeSidebar();
                }
            });
        });

        overlay.addEventListener("click", closeSidebar);
    }

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            closeSidebar();
            if (publicNav) publicNav.classList.remove("show");
        }
    });

    window.addEventListener("resize", function () {
        if (window.innerWidth >= DESKTOP_BREAKPOINT) {
            closeSidebar();
        }
    });

    if (publicToggle && publicNav) {
        publicToggle.addEventListener("click", function (event) {
            event.stopPropagation();
            const open = publicNav.classList.toggle("show");
            publicToggle.setAttribute("aria-expanded", open ? "true" : "false");
        });

        document.addEventListener("click", function (event) {
            if (!publicNav.classList.contains("show")) return;
            if (publicNav.contains(event.target) || publicToggle.contains(event.target)) return;
            publicNav.classList.remove("show");
            publicToggle.setAttribute("aria-expanded", "false");
        });
    }
})();
