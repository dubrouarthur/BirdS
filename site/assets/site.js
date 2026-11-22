/* Bird Models — script unique (thème, menu, liens « Essayer », contact, apparitions). */
(function () {
  "use strict";
  var root = document.documentElement;
  root.classList.add("js");

  // Thème : choix mémorisé, sinon réglage du système.
  var KEY = "bird-theme";
  try {
    var saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
  } catch (e) {}

  function currentTheme() {
    var t = root.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function ready() {
    // Liens « Essayer Bird » : une seule constante dans /config.js.
    var cfg = window.BIRD_CONFIG || {};
    var url = typeof cfg.TRY_URL === "string" && cfg.TRY_URL ? cfg.TRY_URL : "#essayer";
    var tries = document.querySelectorAll("[data-try]");
    for (var i = 0; i < tries.length; i++) {
      tries[i].setAttribute("href", url);
      if (/^https?:/i.test(url)) tries[i].setAttribute("rel", "noopener");
    }

    // Adresse de contact : une seule constante dans /config.js.
    var mail = typeof cfg.CONTACT_EMAIL === "string" && /^[^\s@]+@[^\s@]+$/.test(cfg.CONTACT_EMAIL) ? cfg.CONTACT_EMAIL : "";
    if (mail) {
      var cs = document.querySelectorAll("[data-contact]");
      for (var c = 0; c < cs.length; c++) { cs[c].setAttribute("href", "mailto:" + mail); cs[c].textContent = mail; }
    }

    // Bouton de thème.
    var tb = document.querySelector(".theme-btn");
    if (tb) {
      var sync = function () { tb.setAttribute("aria-pressed", currentTheme() === "dark" ? "true" : "false"); };
      sync();
      tb.addEventListener("click", function () {
        var next = currentTheme() === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        try { localStorage.setItem(KEY, next); } catch (e) {}
        sync();
      });
    }

    // Menu mobile. Le menu suit le bouton dans le DOM : Tab mène directement aux liens.
    var mb = document.querySelector(".menu-btn");
    var nav = document.getElementById("nav");
    if (mb && nav) {
      var isOpen = function () { return nav.classList.contains("is-open"); };
      var close = function () { nav.classList.remove("is-open"); mb.setAttribute("aria-expanded", "false"); };
      mb.addEventListener("click", function () {
        var open = !isOpen();
        nav.classList.toggle("is-open", open);
        mb.setAttribute("aria-expanded", open ? "true" : "false");
      });
      nav.addEventListener("click", function (e) { if (e.target.closest("a")) close(); });
      document.addEventListener("keydown", function (e) { if (e.key === "Escape" && isOpen()) { close(); mb.focus(); } });
      document.addEventListener("click", function (e) { if (isOpen() && !nav.contains(e.target) && !mb.contains(e.target)) close(); });
      nav.addEventListener("focusout", function (e) {
        var to = e.relatedTarget;
        if (isOpen() && to && !nav.contains(to) && to !== mb) close();
      });
    }

    // En-tête : filet au défilement.
    var header = document.querySelector(".site-header");
    if (header) {
      var onScroll = function () { header.classList.toggle("is-scrolled", window.scrollY > 8); };
      onScroll();
      window.addEventListener("scroll", onScroll, { passive: true });
    }

    // Apparitions discrètes (désactivées si mouvement réduit : voir CSS).
    var items = document.querySelectorAll(".reveal");
    if (!("IntersectionObserver" in window)) {
      for (var j = 0; j < items.length; j++) items[j].classList.add("is-in");
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add("is-in"); io.unobserve(en.target); }
      });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.05 });
    for (var k = 0; k < items.length; k++) io.observe(items[k]);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();
})();
