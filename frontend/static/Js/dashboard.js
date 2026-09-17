$(document).ready(function () {
    console.log("dashboard.js loaded");

    $("#toggleSidebar").on("click", function () {
        console.log("toggle clicked");
        $("#sidebar").toggleClass("show");
        $("#sidebarOverlay").fadeToggle(200);
    });

    $("#sidebarOverlay").on("click", function () {
        closeSidebar();
    });

    $(".menu-toggle").on("click", function (e) {
        e.preventDefault();
        e.stopPropagation();

        $(".submenu").not($(this).next()).slideUp(200);
        $(".menu-toggle").not($(this)).removeClass("active");

        $(this).toggleClass("active");
        $(this).next(".submenu").slideToggle(200);
    });

    $(".submenu a").on("click", function () {
        if ($(window).width() < 992) {
            closeSidebar();
        }
    });

    $(".sidebar > a:not(.menu-toggle)").on("click", function () {
        if ($(window).width() < 992) {
            closeSidebar();
        }
    });

    function closeSidebar() {
        $("#sidebar").removeClass("show");
        $("#sidebarOverlay").fadeOut(200);
    }

    setTimeout(function () {
        $(".alert").slideUp("slow", function () {
            $(this).alert("close");
        });
    }, 3000);
});