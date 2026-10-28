// Purefile frontend: queue uploads, show reports, offer downloads.

import { ApiError, deleteFile, getConfig, uploadFile, zipUrl } from "./api.js";
import { initI18n, language, setLanguage, t } from "./i18n.js";
import { createCard, isVideo, renderCard } from "./ui.js";

const MB = 1024 * 1024;
const PARALLEL_UPLOADS = 2;
const ACCEPTED = /\.(jpe?g|jfif|png|webp|heic|heif|hif|mp4|m4v|mov|qt)$/i;

const $ = (id) => document.getElementById(id);
const els = {
  input: $("file-input"),
  dropzone: $("dropzone"),
  workspace: $("workspace"),
  list: $("file-list"),
  summary: $("summary"),
  clearAll: $("clear-all"),
  downloadAll: $("download-all"),
  limits: $("limits"),
  privacy: document.querySelector('[data-i18n="drop.privacy"]'),
  themeToggle: $("theme-toggle"),
};

const state = {
  config: { max_image_mb: 50, max_video_mb: 1024, file_ttl_seconds: 600 },
  entries: [],
  active: 0,
};

// --- Queue ------------------------------------------------------------------

function addFiles(files) {
  for (const file of files) {
    const entry = { file, status: "waiting", progress: 0, result: null, error: null };
    const limit = isVideo(file) ? state.config.max_video_mb : state.config.max_image_mb;
    if (!ACCEPTED.test(file.name) && !/^(image|video)\//.test(file.type)) {
      fail(entry, new ApiError("unsupported_type"));
    } else if (file.size > limit * MB) {
      fail(entry, new ApiError("too_large"), { limit });
    }
    state.entries.push(entry);
    els.list.append(createCard(entry, { onRemove: remove, onDownload: markDownloaded }));
  }
  update();
  pump();
}

function fail(entry, error, vars = {}) {
  entry.status = "failed";
  entry.error = { code: error.code || "server_error", ...vars };
}

function pump() {
  while (state.active < PARALLEL_UPLOADS) {
    const next = state.entries.find((e) => e.status === "waiting");
    if (!next) return;
    start(next);
  }
}

async function start(entry) {
  state.active += 1;
  entry.status = "uploading";
  renderCard(entry);
  entry.upload = uploadFile(entry.file, (fraction) => {
    entry.progress = fraction;
    if (fraction >= 1 && entry.status === "uploading") entry.status = "scanning";
    renderCard(entry);
  });
  try {
    entry.result = await entry.upload.promise;
    entry.status = "clean";
    renderCard(entry);
    // Let the browser paint the un-peeled corner first, then peel.
    requestAnimationFrame(() => requestAnimationFrame(() => entry.el.classList.add("is-peeled")));
  } catch (error) {
    if (!entry.removed) {
      const limit = isVideo(entry.file) ? state.config.max_video_mb : state.config.max_image_mb;
      fail(entry, error, { limit });
      renderCard(entry);
    }
  } finally {
    entry.upload = null;
    state.active -= 1;
    update();
    pump();
  }
}

// --- Actions ----------------------------------------------------------------

function remove(entry) {
  entry.removed = true;
  entry.upload?.abort();
  if (entry.result && entry.status === "clean") deleteFile(entry.result.id);
  if (entry.objectUrl) URL.revokeObjectURL(entry.objectUrl);
  entry.el.remove();
  state.entries = state.entries.filter((e) => e !== entry);
  update();
}

function markDownloaded(entry) {
  if (entry.status !== "clean") return;
  // The server deletes the file once it has been sent; the link is single-use.
  setTimeout(() => {
    entry.status = "downloaded";
    renderCard(entry);
    update();
  });
}

function downloadAll(event) {
  event.preventDefault();
  const ready = state.entries.filter((e) => e.status === "clean");
  if (!ready.length) return;
  if (ready.length === 1) {
    ready[0].refs.download.click();
    return;
  }
  const link = document.createElement("a");
  link.href = zipUrl(ready.map((e) => e.result.id));
  link.download = "purefile.zip";
  document.body.append(link);
  link.click();
  link.remove();
  for (const entry of ready) markDownloaded(entry);
}

function clearAll() {
  for (const entry of [...state.entries]) remove(entry);
}

// --- Page state -------------------------------------------------------------

function update() {
  const count = state.entries.length;
  const clean = state.entries.filter((e) => e.status === "clean" || e.status === "downloaded").length;
  const ready = state.entries.some((e) => e.status === "clean");
  els.workspace.hidden = count === 0;
  els.summary.textContent = t("actions.summary", { count, clean });
  els.downloadAll.setAttribute("aria-disabled", String(!ready));
  els.downloadAll.classList.toggle("pointer-events-none", !ready);
  els.downloadAll.classList.toggle("opacity-50", !ready);
}

function renderStatic() {
  const { max_image_mb, max_video_mb, file_ttl_seconds } = state.config;
  els.limits.dataset.i18n = "drop.limits";
  els.limits.dataset.i18nVars = JSON.stringify({ image: max_image_mb, video: max_video_mb });
  els.limits.textContent = t("drop.limits", { image: max_image_mb, video: max_video_mb });
  const minutes = Math.round(file_ttl_seconds / 60);
  els.privacy.dataset.i18nVars = JSON.stringify({ minutes });
  els.privacy.textContent = t("drop.privacy", { minutes });
  for (const button of document.querySelectorAll(".lang-btn")) {
    const active = button.dataset.lang === language();
    button.setAttribute("aria-pressed", String(active));
    button.classList.toggle("bg-navy", active);
    button.classList.toggle("text-white", active);
    button.classList.toggle("dark:bg-white", active);
    button.classList.toggle("dark:text-navy", active);
    button.classList.toggle("text-muted", !active);
  }
}

function toggleTheme() {
  const dark = document.documentElement.classList.toggle("dark");
  try {
    localStorage.setItem("purefile-theme", dark ? "dark" : "light");
  } catch {
    // Not persisted; the theme still applies to this page.
  }
}

function bindDragAndDrop() {
  const root = document.documentElement;
  let depth = 0;
  const hasFiles = (event) => [...(event.dataTransfer?.types || [])].includes("Files");
  document.addEventListener("dragenter", (event) => {
    if (!hasFiles(event)) return;
    depth += 1;
    root.classList.add("is-dragging");
  });
  document.addEventListener("dragleave", () => {
    depth = Math.max(0, depth - 1);
    if (depth === 0) root.classList.remove("is-dragging");
  });
  document.addEventListener("dragover", (event) => {
    if (hasFiles(event)) event.preventDefault();
  });
  document.addEventListener("drop", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    depth = 0;
    root.classList.remove("is-dragging");
    addFiles(event.dataTransfer.files);
  });
}

async function init() {
  await initI18n();
  state.config = await getConfig().catch(() => state.config);
  renderStatic();
  bindDragAndDrop();

  els.input.addEventListener("change", () => {
    addFiles(els.input.files);
    els.input.value = ""; // allow picking the same file again
  });
  els.dropzone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      els.input.click();
    }
  });
  document.addEventListener("paste", (event) => {
    if (event.clipboardData?.files.length) addFiles(event.clipboardData.files);
  });
  els.downloadAll.addEventListener("click", downloadAll);
  els.clearAll.addEventListener("click", clearAll);
  els.themeToggle.addEventListener("click", toggleTheme);
  for (const button of document.querySelectorAll(".lang-btn")) {
    button.addEventListener("click", () => setLanguage(button.dataset.lang));
  }
  document.addEventListener("languagechange", () => {
    renderStatic();
    for (const entry of state.entries) renderCard(entry);
    update();
  });
  // Files that were cleaned but never downloaded are deleted when the page closes.
  window.addEventListener("pagehide", () => {
    for (const entry of state.entries) {
      if (entry.status === "clean") deleteFile(entry.result.id);
    }
  });
}

init();
