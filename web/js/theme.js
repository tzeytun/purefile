// Runs before first paint: apply the saved theme, or follow the system setting.
// Loaded as a classic (blocking) script so the page never flashes the wrong theme.
(function () {
  var saved = null;
  try {
    saved = localStorage.getItem("purefile-theme");
  } catch (e) {
    // Storage can be unavailable (private mode, blocked site data).
  }
  var dark = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.classList.toggle("dark", dark);
})();
