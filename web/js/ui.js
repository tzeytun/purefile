// Rendering of file cards. Cards are built from the <template> in index.html
// and re-rendered from their entry state (also when the language changes).

import { formatBytes, formatNumber, t } from "./i18n.js";

const template = document.getElementById("card-template");

const FILE_ICON = `<svg class="size-8 text-muted" viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.6" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h7l5 5v11a2 2 0 0 1-2 2H6a2
  2 0 0 1-2-2V5a2 2 0 0 1 2-2Z"/><path d="M13 3v5h5"/></svg>`;
const CHECK_ICON = `<svg class="mt-0.5 size-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 5 5 9-10"/></svg>`;
const ALERT_DOT = `<span class="size-1.5 shrink-0 rounded-full bg-coral" aria-hidden="true"></span>`;

export function isVideo(file) {
  return file.type.startsWith("video/") || /\.(mp4|m4v|mov|qt)$/i.test(file.name);
}

/** Create the card element for an entry; ``actions`` holds onRemove/onDownload. */
export function createCard(entry, actions) {
  const el = template.content.firstElementChild.cloneNode(true);
  const refs = {};
  for (const node of el.querySelectorAll("[data-ref]")) refs[node.dataset.ref] = node;
  entry.el = el;
  entry.refs = refs;
  refs.name.textContent = entry.file.name;
  refs.name.title = entry.file.name;
  refs.remove.addEventListener("click", () => actions.onRemove(entry));
  refs.download.addEventListener("click", () => actions.onDownload(entry));
  renderThumbnail(entry);
  renderCard(entry);
  return el;
}

function renderThumbnail(entry) {
  const box = entry.refs.thumb;
  const showIcon = () => {
    box.innerHTML = FILE_ICON;
  };
  entry.objectUrl = URL.createObjectURL(entry.file);
  let media;
  if (isVideo(entry.file)) {
    media = document.createElement("video");
    media.muted = true;
    media.playsInline = true;
    media.preload = "metadata";
    media.src = `${entry.objectUrl}#t=0.1`;
  } else {
    media = document.createElement("img");
    media.decoding = "async";
    media.src = entry.objectUrl;
    media.alt = "";
  }
  media.className = "size-full object-cover";
  media.addEventListener("error", showIcon); // e.g. HEIC outside Safari
  box.replaceChildren(media);
}

const STATUS_STYLE = { clean: "badge-ok", failed: "badge-alert" };

export function renderCard(entry) {
  const { refs, result } = entry;

  // Status pill and progress bar
  refs.status.className = STATUS_STYLE[entry.status] || "badge-note";
  refs.status.textContent =
    entry.status === "uploading"
      ? t("status.uploading", { percent: formatNumber(Math.round(entry.progress * 100)) })
      : t(`status.${entry.status}`);
  const busy = entry.status === "uploading" || entry.status === "scanning";
  refs.progress.hidden = !busy;
  const bar = refs.progress.firstElementChild;
  bar.classList.toggle("is-indeterminate", entry.status === "scanning");
  bar.style.width = `${Math.round(entry.progress * 100)}%`;

  // Size line
  refs.meta.textContent = result
    ? `${formatBytes(result.size_before)} → ${formatBytes(result.size_after)}`
    : formatBytes(entry.file.size);

  renderReport(entry);

  // Error
  refs.error.hidden = !entry.error;
  if (entry.error) refs.error.textContent = t(`error.${entry.error.code}`, entry.error);

  // Buttons
  refs.remove.textContent = t("card.remove");
  const downloadable = entry.status === "clean" || entry.status === "downloaded";
  refs.download.hidden = !downloadable;
  if (downloadable) {
    const done = entry.status === "downloaded";
    refs.download.textContent = t(done ? "card.downloaded" : "card.download");
    refs.download.setAttribute("aria-label", `${refs.download.textContent}: ${result.clean_name}`);
    refs.download.classList.toggle("pointer-events-none", done);
    refs.download.classList.toggle("opacity-60", done);
    if (done) {
      refs.download.removeAttribute("href");
    } else {
      refs.download.href = result.download_url;
      refs.download.download = result.clean_name;
    }
  }
}

function renderReport(entry) {
  const { refs, result } = entry;
  refs.badges.replaceChildren();
  refs.details.hidden = true;
  refs.after.hidden = true;
  if (!result) return;
  const { before, after } = result;

  for (const highlight of before.highlights) refs.badges.append(badge(highlight));

  if (before.total > 0) {
    refs.details.hidden = false;
    refs.summary.textContent = t("card.found", { count: before.total });
    refs.groups.replaceChildren(...before.groups.map(fieldGroup));
  }

  const parts = [before.total === 0 && !before.c2pa.present ? t("card.nothingFound") : t("card.after")];
  if (before.c2pa.present) parts.push(t("card.c2paRemoved"));
  if (after.kept.length) {
    parts.push(t("card.kept", { items: after.kept.map((k) => t(`kept.${k}`)).join(", ") }));
  }
  refs.after.innerHTML = CHECK_ICON;
  refs.after.append(document.createTextNode(parts.join(" ")));
  refs.after.hidden = false;
}

function highlightLabel({ kind, value }) {
  switch (kind) {
    case "c2pa":
      return value ? t("badge.c2pa", { value }) : t("badge.c2paPlain");
    case "source_type": {
      const key = `source.${value}`;
      const label = t(key);
      return label === key ? t("source.other", { value }) : label;
    }
    case "ai":
      return t("badge.ai");
    case "location":
      return t("badge.location");
    default:
      return t(`badge.${kind}`, { value });
  }
}

function badge(highlight) {
  const li = document.createElement("li");
  li.className = highlight.alert ? "badge-alert" : "badge-note";
  if (highlight.alert) li.innerHTML = ALERT_DOT;
  const text = document.createElement("span");
  text.className = "truncate";
  text.textContent = highlightLabel(highlight);
  li.append(text);
  if (highlight.value) li.title = highlight.value;
  return li;
}

function fieldGroup({ category, fields }) {
  const section = document.createElement("section");
  const heading = document.createElement("h3");
  heading.className = "mb-1.5 font-display text-sm font-medium";
  heading.textContent = t(`category.${category}`);
  if (category === "ai" || category === "provenance") {
    heading.classList.add("text-alert-ink");
  }
  const list = document.createElement("dl");
  list.className = "divide-y divide-line overflow-hidden rounded-lg border border-line text-xs";
  for (const field of fields) {
    const row = document.createElement("div");
    row.className = "grid gap-0.5 px-3 py-2 sm:grid-cols-[minmax(0,14rem)_1fr] sm:gap-3";
    const name = document.createElement("dt");
    name.className = "truncate font-mono text-muted";
    name.textContent = `${field.group}:${field.tag}`;
    name.title = name.textContent;
    const value = document.createElement("dd");
    value.className = "break-words";
    value.textContent = field.value;
    row.append(name, value);
    list.append(row);
  }
  section.append(heading, list);
  return section;
}
