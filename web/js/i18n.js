// Minimal i18n: JSON message catalogs in /locales, {name} placeholders and
// ICU-style "{count, plural, one {# file} other {# files}}" plurals.

const SUPPORTED = ["en", "tr"];
const STORAGE_KEY = "purefile-lang";
const catalogs = {};
let current = "en";

async function load(lang) {
  if (!catalogs[lang]) {
    const response = await fetch(`/locales/${lang}.json`);
    catalogs[lang] = await response.json();
  }
  return catalogs[lang];
}

function preferredLanguage() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (SUPPORTED.includes(saved)) return saved;
  } catch {
    // Storage unavailable; fall back to the browser language.
  }
  return (navigator.language || "en").toLowerCase().startsWith("tr") ? "tr" : "en";
}

export function language() {
  return current;
}

export async function setLanguage(lang) {
  if (!SUPPORTED.includes(lang)) lang = "en";
  await Promise.all([load("en"), load(lang)]); // English is the fallback
  current = lang;
  document.documentElement.lang = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // Not persisted; the choice still applies to this page.
  }
  apply(document);
  document.dispatchEvent(new CustomEvent("languagechange", { detail: lang }));
}

export function initI18n() {
  return setLanguage(preferredLanguage());
}

const PLURAL = /\{(\w+), plural, one \{([^}]*)\} other \{([^}]*)\}\}/g;

export function t(key, vars = {}) {
  let text = catalogs[current]?.[key] ?? catalogs.en?.[key] ?? key;
  const rules = new Intl.PluralRules(current);
  text = text.replace(PLURAL, (_, name, one, other) => {
    const n = Number(vars[name] ?? 0);
    return (rules.select(n) === "one" ? one : other).replace("#", formatNumber(n));
  });
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in vars ? String(vars[name]) : match));
}

export function formatNumber(n) {
  return new Intl.NumberFormat(current).format(n);
}

export function formatBytes(bytes) {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1;
  return `${new Intl.NumberFormat(current, { maximumFractionDigits: digits }).format(value)} ${units[unit]}`;
}

/** Translate every element under ``root`` that carries data-i18n attributes. */
export function apply(root) {
  for (const el of root.querySelectorAll("[data-i18n]")) {
    const vars = el.dataset.i18nVars ? JSON.parse(el.dataset.i18nVars) : {};
    el.textContent = t(el.dataset.i18n, vars);
  }
  for (const el of root.querySelectorAll("[data-i18n-aria-label]")) {
    el.setAttribute("aria-label", t(el.dataset.i18nAriaLabel));
  }
}
