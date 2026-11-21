// Applied before first paint (classic script, loaded from 'self') so a saved theme never flashes.
(function () {
  try {
    var saved = localStorage.getItem("bird.theme");
    if (saved === "light" || saved === "dark")
      document.documentElement.dataset.theme = saved;
    var lang = localStorage.getItem("bird.lang");
    if (lang === "en" || lang === "fr") document.documentElement.lang = lang;
  } catch (e) {
    /* storage unavailable: follow the system theme */
  }
})();
