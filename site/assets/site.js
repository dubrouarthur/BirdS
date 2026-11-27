/* Bird Models — script unique (thème, menu, liens « Essayer », contact, apparitions, scènes). */
(function () {
  "use strict";
  var root = document.documentElement;
  root.classList.add("js");

  // Thème : choix mémorisé, sinon réglage du système.
  var KEY = "bird-theme";
  try {
    var saved = localStorage.getItem(KEY);
    if (saved === "light" || saved === "dark")
      root.setAttribute("data-theme", saved);
  } catch (e) {}

  function currentTheme() {
    var t = root.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia &&
      matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function ready() {
    // Liens « Essayer Bird » : une seule constante dans /config.js.
    var cfg = window.BIRD_CONFIG || {};
    var url =
      typeof cfg.TRY_URL === "string" && cfg.TRY_URL ? cfg.TRY_URL : "#essayer";
    var tries = document.querySelectorAll("[data-try]");
    for (var i = 0; i < tries.length; i++) {
      tries[i].setAttribute("href", url);
      if (/^https?:/i.test(url)) tries[i].setAttribute("rel", "noopener");
    }

    // Adresse de contact : une seule constante dans /config.js.
    var mail =
      typeof cfg.CONTACT_EMAIL === "string" &&
      /^[^\s@]+@[^\s@]+$/.test(cfg.CONTACT_EMAIL)
        ? cfg.CONTACT_EMAIL
        : "";
    if (mail) {
      // [data-contact-href] : boutons « Nous écrire », seul le lien change.
      var ch = document.querySelectorAll("[data-contact-href]");
      for (var h = 0; h < ch.length; h++)
        ch[h].setAttribute(
          "href",
          "mailto:" + mail + (ch[h].getAttribute("data-contact-href") || ""),
        );
      var cs = document.querySelectorAll("[data-contact]");
      for (var c = 0; c < cs.length; c++) {
        cs[c].setAttribute("href", "mailto:" + mail);
        cs[c].textContent = mail;
      }
    }

    // Bouton de thème.
    var tb = document.querySelector(".theme-btn");
    if (tb) {
      var sync = function () {
        tb.setAttribute(
          "aria-pressed",
          currentTheme() === "dark" ? "true" : "false",
        );
      };
      sync();
      tb.addEventListener("click", function () {
        var next = currentTheme() === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        try {
          localStorage.setItem(KEY, next);
        } catch (e) {}
        sync();
      });
    }

    // Menu mobile. Le menu suit le bouton dans le DOM : Tab mène directement aux liens.
    var mb = document.querySelector(".menu-btn");
    var nav = document.getElementById("nav");
    if (mb && nav) {
      var isOpen = function () {
        return nav.classList.contains("is-open");
      };
      var close = function () {
        nav.classList.remove("is-open");
        mb.setAttribute("aria-expanded", "false");
      };
      mb.addEventListener("click", function () {
        var open = !isOpen();
        nav.classList.toggle("is-open", open);
        mb.setAttribute("aria-expanded", open ? "true" : "false");
      });
      nav.addEventListener("click", function (e) {
        if (e.target.closest("a")) close();
      });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && isOpen()) {
          close();
          mb.focus();
        }
      });
      document.addEventListener("click", function (e) {
        if (isOpen() && !nav.contains(e.target) && !mb.contains(e.target))
          close();
      });
      nav.addEventListener("focusout", function (e) {
        var to = e.relatedTarget;
        if (isOpen() && to && !nav.contains(to) && to !== mb) close();
      });
    }

    // En-tête : filet au défilement.
    var header = document.querySelector(".site-header");
    if (header) {
      var onScroll = function () {
        header.classList.toggle("is-scrolled", window.scrollY > 8);
      };
      onScroll();
      window.addEventListener("scroll", onScroll, { passive: true });
    }

    scenes();

    // Apparitions discrètes : le contenu est visible par défaut (CSS). L'animation ne se joue que pour un
    // élément encore sous l'écran, quand il s'apprête à entrer ; déjà visible ou dépassé, il ne bouge pas.
    var items = document.querySelectorAll(".reveal");
    if (
      !items.length ||
      !("IntersectionObserver" in window) ||
      !window.matchMedia ||
      matchMedia("(prefers-reduced-motion: reduce)").matches
    )
      return;
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (en) {
          if (!en.isIntersecting) return;
          if (en.boundingClientRect.top >= window.innerHeight - 1)
            en.target.classList.add("is-in");
          io.unobserve(en.target);
        });
      },
      { rootMargin: "0px 0px 25% 0px", threshold: 0 },
    );
    for (var k = 0; k < items.length; k++) io.observe(items[k]);
  }

  // Scènes : un échange rejoué en HTML. Sans JavaScript ou en mouvement réduit, l'état final s'affiche.
  //   data-at="ms" : l'élément apparaît ; data-out="ms" : il disparaît ;
  //   data-type / data-stream : son texte s'écrit lettre à lettre / mot à mot pendant data-dur ms.
  function scenes() {
    var list = document.querySelectorAll("[data-scene]");
    if (!list.length) return;
    var still =
      !window.matchMedia ||
      matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still || !("IntersectionObserver" in window)) return;
    Array.prototype.forEach.call(list, function (scene) {
      var items = Array.prototype.slice.call(
        scene.querySelectorAll("[data-at]"),
      );
      var timers = [];
      var end = 0;
      items.forEach(function (el) {
        var at = +el.getAttribute("data-at") || 0;
        var dur = +el.getAttribute("data-dur") || 0;
        var out = +el.getAttribute("data-out") || 0;
        if (el.hasAttribute("data-type") || el.hasAttribute("data-stream"))
          el._full = el.textContent;
        end = Math.max(end, at + dur, out);
      });
      var hold = +scene.getAttribute("data-hold") || 4000;
      var playing = false;
      // data-first="shown" : le premier échange s'affiche déjà rempli, puis la scène se rejoue.
      var shownFirst = scene.getAttribute("data-first") === "shown";
      function later(fn, ms) {
        timers.push(setTimeout(fn, ms));
      }
      function stop() {
        timers.forEach(clearTimeout);
        timers = [];
        playing = false;
      }
      function write(el, dur, words) {
        var parts = words
          ? el._full.match(/\S+\s*/g) || [el._full]
          : el._full.split("");
        var step = Math.max(16, dur / parts.length);
        var shown = "";
        el.textContent = "";
        parts.forEach(function (part, i) {
          later(function () {
            shown += part;
            el.textContent = shown;
          }, i * step);
        });
      }
      function play() {
        stop();
        playing = true;
        scene.classList.add("is-live");
        items.forEach(function (el) {
          el.classList.remove("is-on", "is-off");
          if (el._full != null) el.textContent = "";
        });
        items.forEach(function (el) {
          var dur = +el.getAttribute("data-dur") || 0;
          later(
            function () {
              el.classList.add("is-on");
              if (el._full != null)
                write(el, dur, el.hasAttribute("data-stream"));
            },
            +el.getAttribute("data-at") || 0,
          );
          if (el.hasAttribute("data-out"))
            later(function () {
              el.classList.add("is-off");
            }, +el.getAttribute("data-out"));
        });
        later(function () {
          if (playing) play();
        }, end + hold);
      }
      var replay = scene.parentNode.querySelector(".scene-replay");
      if (replay) {
        replay.hidden = false;
        replay.addEventListener("click", play);
      }
      new IntersectionObserver(
        function (entries) {
          entries.forEach(function (en) {
            if (en.isIntersecting && !playing) {
              if (shownFirst) {
                shownFirst = false;
                playing = true;
                later(play, hold);
              } else play();
            }
            else if (!en.isIntersecting && playing) stop();
          });
        },
        { threshold: 0.35 },
      ).observe(scene);
    });
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", ready);
  else ready();
})();
