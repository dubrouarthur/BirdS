// Applied before first paint (classic script, loaded from 'self') so a saved theme never flashes.
(function () {
  try {
    var prefs = JSON.parse(localStorage.getItem("bird.prefs") || "{}") || {};
    if (prefs.theme === "light" || prefs.theme === "dark") document.documentElement.dataset.theme = prefs.theme;
    if (prefs.lang === "en" || prefs.lang === "fr") document.documentElement.lang = prefs.lang;
    if (localStorage.getItem("bird.side") === "0") document.documentElement.dataset.side = "closed";
  } catch (e) {
    /* storage unavailable: follow the system theme */
  }
})();
