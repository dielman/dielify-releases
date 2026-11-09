// Dielify desktop screens. Plain JS, no build step.
// Safety: text from YouTube (titles, names) is only ever set with textContent via h(),
// never as HTML, because this window holds the PC-only key.
"use strict";

// --- key + API ---------------------------------------------------------------------
// "#t=<key>&go=album:12" opens that screen at start (used for screenshots of each screen)
const GO = (location.hash.match(/[#&]go=([\w:-]+)/) || [])[1] || null;
const PLAYING = /[#&]playing(&|$)/.test(location.hash);  // screenshots: something in the player bar
const KEY = (() => {
  const m = location.hash.match(/t=([\w-]+)/);
  if (m) {
    sessionStorage.setItem("dielify-key", m[1]);
    history.replaceState(null, "", location.pathname);  // keep the key out of the address
  }
  return sessionStorage.getItem("dielify-key");
})();

async function api(path, opts = {}) {
  const r = await fetch(path, {
    ...opts,
    headers: { "Authorization": `Bearer ${KEY}`, "Content-Type": "application/json", ...(opts.headers || {}) },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (r.status === 204) return null;
  if (r.status === 401) throw new Error("This window lost its connection to Dielify. Quit Dielify from the tray icon and open it again.");
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Something went wrong on the PC (error ${r.status}). Try again.`);
  return data;
}
const media = (url, size) => url && `${url}?token=${encodeURIComponent(KEY)}${size ? `&size=${size}` : ""}`;
const desktopApp = () => window.pywebview && window.pywebview.api;

// --- tiny DOM helpers ----------------------------------------------------------------
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const $ = (id) => document.getElementById(id);

// --- icons (Material Symbols paths, drawn inline: no fonts or files to load) ------------------
const ICONS = {
  explore: "M12 10.9c-.61 0-1.1.49-1.1 1.1s.49 1.1 1.1 1.1c.61 0 1.1-.49 1.1-1.1s-.49-1.1-1.1-1.1zM12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm2.19 12.19L6 18l3.81-8.19L18 6l-3.81 8.19z",
  library: "M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-1 9h-4v4h-2v-4H9V9h4V5h2v4h4v2z",
  groups: "M12 12.75c1.63 0 3.07.39 4.24.9 1.08.48 1.76 1.56 1.76 2.73V18H6v-1.61c0-1.18.68-2.26 1.76-2.73 1.17-.52 2.61-.91 4.24-.91zM4 13c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm1.13 1.1c-.37-.06-.74-.1-1.13-.1-.99 0-1.93.21-2.78.58C.48 14.9 0 15.62 0 16.43V18h4.5v-1.61c0-.83.23-1.61.63-2.29zM20 13c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm4 3.43c0-.81-.48-1.53-1.22-1.85-.85-.37-1.79-.58-2.78-.58-.39 0-.76.04-1.13.1.4.68.63 1.46.63 2.29V18H24v-1.57zM12 6c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3z",
  insights: "M21 8c-1.45 0-2.26 1.44-1.93 2.51l-3.55 3.56c-.3-.09-.74-.09-1.04 0l-2.55-2.55C12.27 10.45 11.46 9 10 9c-1.45 0-2.27 1.44-1.93 2.52l-4.56 4.55C2.44 15.74 1 16.55 1 18c0 1.1.9 2 2 2 1.45 0 2.26-1.44 1.93-2.51l4.55-4.56c.3.09.74.09 1.04 0l2.55 2.55C12.73 16.55 13.54 18 15 18c1.45 0 2.27-1.44 1.93-2.52l3.56-3.55c1.07.33 2.51-.48 2.51-1.93 0-1.1-.9-2-2-2z",
  settings: "M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58a.49.49 0 0 0 .12-.61l-1.92-3.32a.488.488 0 0 0-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54a.484.484 0 0 0-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.09.63-.09.94s.02.64.07.94l-2.03 1.58a.49.49 0 0 0-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z",
  search: "M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z",
  volume: "M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z",
  more: "M6 10c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm12 0c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm-6 0c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z",
  equalizer: "M10 20h4V4h-4v16zm-6 0h4v-8H4v8zM16 9v11h4V9h-4z",
  expand: "M7.41 15.41L12 10.83l4.59 4.58L18 14l-6-6-6 6z",
  collapse: "M16.59 8.59L12 13.17 7.41 8.59 6 10l6 6 6-6z",
  noTaste: "M12 7c2.76 0 5 2.24 5 5 0 .65-.13 1.26-.36 1.83l2.92 2.92c1.51-1.26 2.7-2.89 3.43-4.75-1.73-4.39-6-7.5-11-7.5-1.4 0-2.74.25-3.98.7l2.16 2.16C10.74 7.13 11.35 7 12 7zM2 4.27l2.28 2.28.46.46C3.08 8.3 1.78 10.02 1 12c1.73 4.39 6 7.5 11 7.5 1.55 0 3.03-.3 4.38-.84l.42.42L19.73 22 21 20.73 3.27 3 2 4.27zM7.53 9.8l1.55 1.55c-.05.21-.08.43-.08.65 0 1.66 1.34 3 3 3 .22 0 .44-.03.65-.08l1.55 1.55c-.67.33-1.41.53-2.2.53-2.76 0-5-2.24-5-5 0-.79.2-1.53.53-2.2zm4.31-.78l3.15 3.15.02-.16c0-1.66-1.34-3-3-3l-.17.01z",
  personAdd: "M15 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm-9-2V7H4v3H1v2h3v3h2v-3h3v-2H6zm9 4c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z",
  play: "M8 5v14l11-7z",
  add: "M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z",
  tv: "M21 3H3c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h5v2h8v-2h5c1.1 0 1.99-.9 1.99-2L23 5c0-1.1-.9-2-2-2zm0 14H3V5h18v12z",
  radio: "M3.24 6.15C2.51 6.43 2 7.17 2 8v12c0 1.1.89 2 2 2h16c1.11 0 2-.9 2-2V8c0-1.11-.89-2-2-2H8.3l8.26-3.34L15.88 1 3.24 6.15zM7 20c-1.66 0-3-1.34-3-3s1.34-3 3-3 3 1.34 3 3-1.34 3-3 3zm13-8h-2v-2h-2v2H4V8h16v4z",
  person: "M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z",
  pause: "M6 19h4V5H6v14zm8-14v14h4V5h-4z",
  next: "M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z",
  prev: "M6 6h2v12H6zm3.5 6l8.5 6V6z",
  playlistAdd: "M14 10H3v2h11v-2zm0-4H3v2h11V6zm4 8v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zM3 16h7v-2H3v2z",
  download: "M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z",
  check: "M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z",
  close: "M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z",
  up: "M4 12l1.41 1.41L11 7.83V20h2V7.83l5.58 5.59L20 12l-8-8-8 8z",
  remove: "M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z",
  shuffle: "M10.59 9.17L5.41 4 4 5.41l5.17 5.17 1.42-1.41zM14.5 4l2.04 2.04L4 18.59 5.41 20 17.96 7.46 20 9.5V4h-5.5zm.33 9.41l-1.41 1.41 3.13 3.13L14.5 20H20v-5.5l-2.04 2.04-3.13-3.13z",
  devices: "M4 6h18V4H4c-1.1 0-2 .9-2 2v11H0v3h14v-3H4V6zm19 2h-6c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h6c.55 0 1-.45 1-1V9c0-.55-.45-1-1-1zm-1 9h-4v-7h4v7z",
  sync: "M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46C19.54 15.03 20 13.57 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74C4.46 8.97 4 10.43 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z",
  edit: "M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z",
  back: "M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z",
  bedtime: "M12.34 2.02C6.59 1.82 2 6.42 2 12c0 5.52 4.48 10 10 10 3.71 0 6.93-2.02 8.66-5.02-7.51-.25-12.09-8.43-8.32-14.96z",
  mic: "M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z",
  queueMusic: "M15 6H3v2h12V6zm0 4H3v2h12v-2zM3 16h8v-2H3v2zM17 6v8.18c-.31-.11-.65-.18-1-.18-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3V8h3V6h-5z",
  queueAdd: "M4 6H2v14c0 1.1.9 2 2 2h14v-2H4V6zm16-4H8c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-1 9h-4v4h-2v-4H9V9h4V5h2v4h4v2z",
  playNext: "M3 10h11v2H3zm0-4h11v2H3zm0 8h7v2H3zm13-1v8l6-4z",
  drag: "M11 18c0 1.1-.9 2-2 2s-2-.9-2-2 .9-2 2-2 2 .9 2 2zm-2-8c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0-6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm6 4c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z",
  thumbUp: "M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z",
  thumbDown: "M15 3H6c-.83 0-1.54.5-1.84 1.22l-3.02 7.05c-.09.23-.14.47-.14.73v2c0 1.1.9 2 2 2h6.31l-.95 4.57-.03.32c0 .41.17.79.44 1.06L9.83 23l6.59-6.59c.36-.36.58-.86.58-1.41V5c0-1.1-.9-2-2-2zm4 0v12h4V3h-4z",
};
function icon(name, cls = "ico") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICONS[name]);
  svg.append(path);
  return svg;
}
// A round icon-only button; `title` is its tooltip and its name for screen readers.
const ib = (name, title, onclick, attrs = {}) =>
  h("button", { class: "ib", title, "aria-label": title, onclick: (e) => { e.stopPropagation(); onclick(e); }, ...attrs }, icon(name));
// A normal button with an icon in front of its words.
const ibtn = (name, label, attrs) => h("button", attrs, icon(name, "ico lead"), label);
const main = $("main");
let shownKey = null;
function show(...nodes) {
  // the fade-in only when it's a different page (pages that refresh themselves don't flicker)
  const key = here ? here.key : null;
  const same = key !== null && key === shownKey;
  main.classList.toggle("still", same);
  shownKey = key;
  const keep = main.scrollTop;
  main.replaceChildren(...nodes.flat(Infinity).filter((n) => n !== null && n !== undefined && n !== false));
  main.scrollTop = same ? keep : 0;  // a page refreshing itself keeps where you were
  main.querySelectorAll("input[type=range]").forEach(fill);  // sliders show where they are
}
document.addEventListener("input", (e) => { if (e.target.matches && e.target.matches("input[type=range]")) fill(e.target); });
// A ⋯ button that opens a small menu: [[icon, label, action], ...] (rarely used page actions)
function moreButton(items) {
  return ib("more", "More", (e) => {
    closeMenu();
    const r = e.currentTarget.getBoundingClientRect();
    const m = h("div", { class: "menu", style: `left:${r.left}px;top:${r.bottom + 6}px` },
      items.filter(Boolean).map(([ic, label, act]) => h("button", { onclick: () => { closeMenu(); act(); } }, icon(ic, "ico lead"), label)));
    document.body.append(m);
    menuOpen = m;
    setTimeout(() => document.addEventListener("mousedown", menuOutside, true));
  }, { class: "ib", style: "background:rgba(255,255,255,.08)" });
}
function toast(msg, ms = 3500) {
  const t = $("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast.timer); toast.timer = setTimeout(() => (t.hidden = true), ms);
}
const dur = (s) => (s ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}` : "");
function art(src, ph = "♪", cls = "art") {
  return src ? h("img", { class: cls, src, alt: "", loading: "lazy" }) : h("div", { class: `${cls} ph` }, ph);
}
// Grey shapes while a page loads (instead of "Loading…").
function skeleton(kind = "grid") {
  const cards = Array.from({ length: 8 }, () => h("div", {}, h("div", { class: "skel skel-card" }), h("div", { class: "skel skel-line" })));
  if (kind === "list") return h("div", { class: "skel-page" }, h("div", { class: "skel skel-title" }),
    ...Array.from({ length: 8 }, () => h("div", { class: "skel skel-row" })));
  return h("div", { class: "skel-page" }, h("div", { class: "skel skel-title" }), h("div", { class: "skel-grid" }, cards));
}
// The cover's colours behind a page header: style for an element (--tint dark, --hue lively).
const tintStyle = (c) => (c ? `--tint:${c.bg};--hue:${c.accent}` : "");
function failed(e) { show(h("p", { class: "pad warn" }, e.message || String(e))); }

// Back history. Each page calls enter() with how to show it again; a detail page (album,
// artist, playlist) first remembers the page you were on, with its scroll position, so its
// Back button returns there exactly (a search keeps its words, tab and results).
let here = null;            // { key, label, render }
const backStack = [];
let restoring = false;
let backAction = null;      // what this page's Back button does (also the mouse's Back button)
function enter(key, label, render, detail = false) {
  backAction = null;
  if (detail && !restoring && here && here.key !== key) {
    backStack.push({ ...here, scroll: main.scrollTop });
    if (backStack.length > 30) backStack.shift();
  }
  here = { key, label, render };
}
function backButton(fallbackLabel, fallback) {
  const prev = backStack[backStack.length - 1];
  backAction = async () => {
    if (!prev) return fallback();
    backStack.pop();
    restoring = true;
    try { await prev.render(); } finally { restoring = false; }
    requestAnimationFrame(() => { main.scrollTop = prev.scroll; });
  };
  return h("button", { onclick: backAction }, icon("back", "ico lead"), prev ? prev.label : fallbackLabel);
}
window.addEventListener("mouseup", (e) => {  // the mouse's own Back button
  if (e.button === 3 && backAction) { e.preventDefault(); backAction(); }
});

// --- the side bar: icons, and your playlists ------------------------------------------------
document.querySelectorAll(".nav-ico[data-icon]").forEach((el) => el.replaceChildren(icon(el.dataset.icon)));
document.querySelector(".search-ico").replaceChildren(icon("search"));
async function paintSide() {
  try {
    const { playlists } = await api("/api/playlists");
    const order = { user: 0, smart: 1, blend: 2, mix: 3 };
    playlists.sort((a, b) => (order[a.kind] ?? 9) - (order[b.kind] ?? 9));
    $("side-playlists").replaceChildren(...playlists.map((p) => h("button", { class: "side-item", "data-pl": p.id, onclick: () => {
      document.querySelectorAll("#nav button").forEach((b) => b.classList.remove("active"));
      view = "library"; viewPlaylist(p.id);
    } }, h("img", { src: media(p.cover_url, 80), alt: "", loading: "lazy" }),
    h("div", {}, h("div", { class: "t" }, p.name), h("div", { class: "s" },
      p.kind === "mix" ? "Dielify mix" : p.kind === "blend" ? "Blend" : p.kind === "smart" ? "Smart playlist"
        : p.shared ? (p.mine ? "Shared" : `From ${p.owner}`) : `${p.count} songs`)))));
  } catch { /* the server is busy: next time */ }
}
setInterval(paintSide, 120000);

// --- state ---------------------------------------------------------------------------
let status = null;          // /api/desktop/status
let view = "discover";  // the app opens on Discover
let libTab = "albums";

async function refreshStatus() {
  status = await api("/api/desktop/status");
  $("offline-pill").hidden = !status.offline;
  return status;
}

// --- navigation ------------------------------------------------------------------------
document.querySelectorAll("#nav button").forEach((b) => b.addEventListener("click", () => go(b.dataset.view)));
function go(v, ...args) {
  view = v;
  backStack.length = 0;  // a new section: nothing to go back to
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  $("search-input").placeholder = v === "discover" ? "Search YouTube Music" : "Search your library";
  ({ library: viewLibrary, discover: viewDiscover, downloads: viewDownloads, stats: viewStats, settings: viewSettings, jam: viewJam })[v](...args);
}
$("search").addEventListener("submit", (e) => {
  e.preventDefault();
  const q = $("search-input").value.trim();
  if (!q) return;
  if (view === "discover") viewYtSearch(q);
  else viewLibrarySearch(q);
});

// --- library -----------------------------------------------------------------------------
function welcome() {
  const p = status.profiles.find((x) => x.name === status.active_profile);
  if (p && p.youtube_signed_in && p.tracks > 0) return null;
  return h("div", { class: "panel welcome" },
    h("h2", {}, "Welcome to Dielify"),
    h("ol", { class: "steps" },
      h("li", {}, "Music is saved in ", h("b", {}, p ? p.library_path : status.library_root), ". ",
        h("button", { class: "link", onclick: () => go("settings") }, "Change folder")),
      h("li", {}, p && p.youtube_signed_in
        ? h("span", { class: "ok" }, "Signed in to YouTube Music ✓")
        : h("span", {}, h("button", { class: "primary", onclick: () => signIn(false) }, "Sign in to YouTube Music"))),
      h("li", {}, "Find music in ", h("button", { class: "link", onclick: () => go("discover") }, "Discover"),
        " and press Download. It plays here, even with no internet.")));
}

async function viewLibrary(tab = libTab) {
  libTab = tab;
  enter(`library:${tab}`, "Library", () => viewLibrary(tab));
  try {
    await refreshStatus();
    const shared = (status.people || []).length > 1;
    if (tab === "household" && !shared) tab = libTab = "albums";
    const tabs = h("div", { class: "tabs" },
      ["albums", "artists", "playlists", "recent", ...(shared ? ["household"] : [])].map((t) => h("button", { class: t === tab ? "active" : "", onclick: () => viewLibrary(t) },
        { albums: "Albums", artists: "Artists", playlists: "Playlists", recent: "Recently played", household: "Household" }[t])));
    let body;
    if (tab === "household") {
      body = await householdBody();
      if (view !== "library" || libTab !== "household") return;
    } else if (tab === "playlists") {
      show(welcome(), h("h1", {}, "Library"), tabs, skeleton());
      const [{ playlists: all }, yt, mixStatus] = await Promise.all([api("/api/playlists"),
        api("/api/yt/my-playlists").catch(() => ({ items: [] })), api("/api/mixes").catch(() => null)]);
      const playlists = all.filter((p) => p.kind !== "mix");
      const blendBox = h("div", {});
      fillBlend(blendBox);
      const mixList = all.filter((p) => p.kind === "mix");
      const synced = new Set(playlists.map((p) => p.yt_id).filter(Boolean));
      const notSynced = yt.items.filter((i) => !synced.has(i.id));
      body = [
        h("h2", {}, "Dielify mixes"),
        mixList.length ? h("div", { class: "grid" }, mixList.map(playlistCard))
          : h("p", { class: "muted small" }, mixStatus && mixStatus.artists && mixStatus.looked_up < mixStatus.artists
            ? `Dielify is learning your genres (${mixStatus.looked_up} of ${mixStatus.artists} artists looked up). Your genre, decade and vibe mixes appear when it's done.`
            : "Your genre, decade and vibe mixes appear here once your library has enough songs."),
        blendBox,
        h("div", { class: "row" }, h("h2", { style: "flex:1" }, "Your playlists"),
          h("button", { onclick: () => smartEditor() }, icon("add", "ico lead"), "Smart playlist"),
          h("button", { class: "primary", onclick: () => newPlaylist([]) }, "New playlist")),
        playlists.length ? h("div", { class: "grid" }, playlists.map(playlistCard))
          : h("p", { class: "muted" }, "None yet. Make one, or sync one of your YouTube Music playlists below."),
        notSynced.length ? [h("h2", {}, "On YouTube Music, not synced"),
          h("p", { class: "muted small" }, "Sync one to keep it in Dielify: its songs download to this PC, and changes go both ways."),
          h("div", { class: "grid" }, notSynced.map((it) => h("div", { class: "card" },
            h("div", { onclick: () => viewCollection("playlist", it.id, "library") }, art(it.thumbnail),
              h("div", { class: "t" }, it.title), h("div", { class: "s" }, it.subtitle || "")),
            h("button", { style: "margin-top:6px", onclick: async () => {
              toast(`Syncing “${it.title}”…`);
              try { const d = await api("/api/playlists/import", { method: "POST", body: { yt_id: it.id } });
                toast(`Syncing “${d.playlist.name}”: its songs are downloading`); viewPlaylist(d.playlist.id);
              } catch (e) { toast(e.message, 6000); }
            } }, "Sync"))))] : null,
      ];
      if (view !== "library" || libTab !== "playlists") return;
    } else if (tab === "artists") {
      const { artists } = await api("/api/library/artists");
      body = artists.length ? h("div", { class: "grid" }, artists.map(artistCard)) : empty();
    } else {
      const sort = tab === "recent" ? "recent" : "newest";
      const { albums } = await api(`/api/library/albums?sort=${sort}&limit=500`);
      body = albums.length ? h("div", { class: "grid" }, albums.map(albumCard)) : empty(tab === "recent" ? "Nothing played yet." : null);
    }
    show(welcome(), h("h1", {}, "Library"), tabs, body);
  } catch (e) { failed(e); }
}
const empty = (msg) => h("p", { class: "muted" }, msg || "No music yet. Find some in Discover.");

// Household: songs already on this PC that someone else in the household has and you don't.
// Adding one puts it in your library straight away (no download).
async function householdBody(q = "") {
  const box = h("div", {});
  const input = h("input", { type: "search", placeholder: "Search the household's songs", value: q, style: "max-width:360px" });
  let timer = null;
  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => fill(input.value), 300); });
  const fill = async (query) => {
    const { tracks } = await api(`/api/library/household?limit=300&q=${encodeURIComponent(query)}`);
    const add = async (ids, msg) => {
      const r = await api("/api/library/add", { method: "POST", body: { track_ids: ids } });
      toast(msg || `Added ${r.added} song${r.added === 1 ? "" : "s"} to your library`); fill(input.value);
    };
    box.replaceChildren(...(tracks.length
      ? [h("div", { class: "row", style: "margin:8px 0" }, h("span", { class: "muted small", style: "flex:1" },
            `${tracks.length}${tracks.length === 300 ? "+" : ""} song${tracks.length === 1 ? "" : "s"} on this PC that aren't in your library`),
          h("button", { onclick: () => add(tracks.map((t) => t.id)) }, icon("add", "ico lead"), "Add all shown")),
        h("table", { class: "tracks" }, h("tbody", {}, tracks.map((t, i) => h("tr", {},
          h("td", { class: "title", onclick: () => playList(tracks, i) }, t.title,
            h("div", { class: "muted small" }, t.artist, ` · ${t.album}`)),
          h("td", { class: "d" }, dur(t.duration_s)),
          h("td", { class: "a" }, ib("add", "Add to your library", () => add([t.id], `Added “${t.title}” to your library`)))))))]
      : [h("p", { class: "muted" }, query ? "No household songs match." : "Everything on this PC is already in your library.")]));
  };
  await fill(q);
  return [h("p", { class: "muted small" }, "Songs someone else in your household has on this PC. Add them to your library: no download needed."),
    input, box];
}
const cardPlay = (play) => h("button", { class: "card-play", title: "Play", onclick: (e) => { e.stopPropagation(); play(); } }, icon("play"));
const albumCard = (a) => h("div", { class: "card", onclick: () => viewAlbum(a.id) },
  cardPlay(async () => playList((await api(`/api/library/albums/${a.id}`)).tracks, 0)),
  art(media(a.cover_url, 320)), h("div", { class: "t" }, a.name), h("div", { class: "s" }, a.artist, a.year ? ` · ${a.year}` : ""));
const artistCard = (r) => h("div", { class: "card round", onclick: () => viewArtist(r.id) },
  art(media(r.image_url || r.cover_url, 320), "👤"), h("div", { class: "t" }, r.name),
  h("div", { class: "s" }, `${r.album_count} album${r.album_count === 1 ? "" : "s"}`));

async function viewArtist(id) {
  try {
    const { artist, albums } = await api(`/api/library/artists/${id}`);
    enter(`artist:${id}`, artist.name, () => viewArtist(id), true);
    const about = h("div", { class: "about" });
    show(backButton("Artists", () => { go("library"); viewLibrary("artists"); }),
      h("div", { class: "hero round", style: tintStyle(artist.colors) }, art(media(artist.image_url || artist.cover_url, 480), "👤", ""),
        h("div", {}, h("div", { class: "muted small" }, "Artist"), h("h1", {}, artist.name),
          h("div", { class: "muted" }, `${albums.length} album${albums.length === 1 ? "" : "s"} in your library`),
          h("div", { class: "row" },
            ibtn("radio", "Artist radio", { class: "primary", title: "Artist radio", onclick: () => startRadio({ artist: artist.name }, `${artist.name} radio`) }),
            followButton(artist.name), artistThumbs(artist.name)))),
      about,
      h("h2", {}, "Albums"),
      h("div", { class: "grid" }, albums.map(albumCard)));
    fillAbout(about, artist.name);
  } catch (e) { failed(e); }
}

// Follow: their new releases show in Discover's "New for you".
function followButton(name, channelId = null) {
  const b = h("button", {});
  let on = false;
  const paint = () => b.replaceChildren(icon(on ? "check" : "personAdd", "ico lead"), on ? "Following" : "Follow");
  b.onclick = async () => {
    try {
      await api("/api/follows", { method: "PUT", body: { name, channel_id: channelId, follow: !on } });
      on = !on; paint();
      toast(on ? `Following ${name}: their new releases show in Discover` : `Stopped following ${name}`);
    } catch (e) { toast(e.message, 6000); }
  };
  paint();
  api("/api/follows").then((r) => { on = r.follows.some((f) => artistKey(f.name) === artistKey(name)); paint(); }).catch(() => {});
  return b;
}
// The artist's About: bio (first lines, "More" for the rest) and links (open in the browser).
async function fillAbout(box, name) {
  box.replaceChildren(h("p", { class: "muted small" }, "Loading About…"));
  try {
    const a = await api(`/api/artists/about?name=${encodeURIComponent(name)}`);
    if (!a.description && !a.links.length) return box.replaceChildren();
    const text = h("p", { class: "bio clamp" }, a.description || "");
    const more = a.description && a.description.length > 280
      ? h("button", { class: "link", onclick: () => { text.classList.toggle("clamp"); more.textContent = text.classList.contains("clamp") ? "More" : "Less"; } }, "More") : null;
    box.replaceChildren(h("h2", {}, "About"), a.description ? text : null, more,
      a.links.length ? h("div", { class: "row links" }, a.links.map((l) =>
        h("a", { href: l.url, target: "_blank", rel: "noopener noreferrer", class: "chip" }, l.label))) : null);
  } catch { box.replaceChildren(); }
}

async function viewAlbum(id) {
  try {
    const { album, tracks } = await api(`/api/library/albums/${id}`);
    enter(`album:${id}`, album.name, () => viewAlbum(id), true);
    show(backButton("Library", () => { go("library"); viewLibrary(); }),
      h("div", { class: "hero", style: tintStyle(album.colors) }, art(media(album.cover_url, 480), "♪", ""),
        h("div", {},
          h("div", { class: "muted small" }, "ALBUM"), h("h1", {}, album.name),
          h("div", { class: "muted" }, album.artist, album.year ? ` · ${album.year}` : "", ` · ${tracks.length} songs`),
          h("div", { class: "row", style: "margin-top:12px" },
            ibtn("play", "Play", { class: "primary", onclick: () => playList(tracks, 0) }),
            ibtn("shuffle", "Shuffle", { onclick: () => playList(shuffle(tracks), 0) }),
            ibtn("queueAdd", "Add to queue", { onclick: () => addToQueue(tracks, false) }),
            moreButton([["remove", "Remove from your library", () => removeFromLibrary({ album: album.id, name: album.name, count: tracks.length })]])))),
      trackTable(tracks, false, () => viewAlbum(id)));
  } catch (e) { failed(e); }
}

async function viewLibrarySearch(q) {
  enter(`lsearch:${q}`, `“${q}”`, () => viewLibrarySearch(q));
  try {
    const r = await api(`/api/library/search?q=${encodeURIComponent(q)}`);
    show(h("h1", {}, `“${q}” in your library`),
      r.tracks.length ? trackTable(r.tracks, true) : h("p", { class: "muted" }, "No songs found."),
      r.albums.length ? [h("h2", {}, "Albums"), h("div", { class: "grid" }, r.albums.map(albumCard))] : null,
      h("p", {}, h("button", { class: "link", onclick: () => { go("discover"); viewYtSearch(q); } }, "Search YouTube Music instead →")));
  } catch (e) { failed(e); }
}

// Take songs out of your library (the file goes too, unless someone else in the household has it).
async function removeFromLibrary({ track, album, name, count = 1 }, after) {
  const what = album ? `the album “${name}” (${count} song${count === 1 ? "" : "s"})` : `“${name}”`;
  if (!confirm(`Remove ${what} from your library?\n\nThe music file is deleted from this PC too, unless someone else in your household has it.`)) return;
  try {
    const r = await api(album ? `/api/library/albums/${album}` : `/api/library/tracks/${track}`, { method: "DELETE" });
    toast(`Removed ${r.removed} song${r.removed === 1 ? "" : "s"}${r.deleted < r.removed ? " (kept on the PC for others in your household)" : ""}`);
    if (album) { if (backAction) backAction(); else { go("library"); viewLibrary(); } }
    else if (after) after();
  } catch (e) { toast(e.message, 6000); }
}

function trackTable(tracks, showAlbum = false, after = null) {
  return h("table", { class: "tracks" }, h("tbody", {}, tracks.map((t, i) =>
    h("tr", { "data-track": t.id, class: player.current && player.current.id === t.id ? "playing" : "" },
      h("td", { class: "n" }, t.track_no || i + 1),
      h("td", { class: "title", onclick: () => playList(tracks, i) }, t.title,
        h("div", { class: "muted small" }, t.artist, showAlbum ? ` · ${t.album}` : "")),
      h("td", { class: "d" }, dur(t.duration_s)),
      h("td", { class: "a" }, queueBtn(() => [t]), t.video_id ? ib("playlistAdd", "Add to playlist", () => addToPlaylist(
        [{ type: "song", id: t.video_id, title: t.title, artists: t.artist ? [t.artist] : [], album: t.album || null }])) : null,
        ib("remove", "Remove from your library", () => removeFromLibrary({ track: t.id, name: t.title },
          after || (() => main.querySelector(`tr[data-track="${t.id}"]`)?.remove()))))))));
}
const shuffle = (xs) => xs.map((x) => [Math.random(), x]).sort((a, b) => a[0] - b[0]).map((x) => x[1]);

// --- discover (YouTube) ---------------------------------------------------------------------
function offlineNotice() {
  return h("div", { class: "panel" }, h("h2", {}, "Offline mode is on"),
    h("p", { class: "muted" }, "Dielify isn't contacting YouTube, so Discover and downloads are paused. Your library still plays."),
    h("button", { onclick: async () => { await api("/api/desktop/settings", { method: "PUT", body: { offline: false } }); go("discover"); } }, "Go online"));
}
function needsSignIn() {
  const p = status.profiles.find((x) => x.name === status.active_profile);
  return !(p && p.youtube_signed_in);
}

async function viewDiscover() {
  enter("discover", "Discover", viewDiscover);
  try {
    await refreshStatus();
    if (status.offline) return show(h("h1", {}, "Discover"), offlineNotice());
    if (needsSignIn()) return show(h("h1", {}, "Discover"), welcome());
    show(skeleton());
    const [home, charts, forYou, mixStatus, fresh] = await Promise.all([api("/api/discover/home?shelves=8"),
      api("/api/discover/charts").catch(() => null), api("/api/discover/for-you").catch(() => null),
      api("/api/mixes").catch(() => null), api("/api/discover/new").catch(() => null)]);
    const newShelf = fresh && fresh.items.length ? [h("h2", {}, "New for you",
      h("span", { class: "muted small" }, ` · from the ${fresh.watching === 1 ? "artist" : fresh.watching + " artists"} you follow or play most`)),
    h("div", { class: "shelf" }, fresh.items.map((it) =>
      ytCard({ ...it, artists: [it.artists.join(", ") + (it.subtitle ? ` · ${it.subtitle}` : "") + (it.year ? ` · ${it.year}` : "")] })))] : null;
    const madeForYou = mixStatus && mixStatus.mixes.length
      ? [h("h2", {}, "Made for you"), h("div", { class: "shelf" }, mixStatus.mixes.map(playlistCard))] : null;
    const shelves = home.shelves.filter((s) => s.items.length).map((s) =>
      [h("h2", {}, s.title), h("div", { class: "shelf" }, s.items.map(ytCard))]);
    const chartShelf = charts && charts.playlists.length
      ? [h("h2", {}, `Charts · ${charts.country}`), h("div", { class: "shelf" }, charts.playlists.map(ytCard))] : null;
    const trackShelf = (title, tracks) => tracks.length ? [h("h2", {}, title), h("div", { class: "shelf" },
      tracks.map((t, i) => h("div", { class: "card", onclick: () => playList(tracks, i) },
        art(media(t.cover_url, 320)), h("div", { class: "t" }, t.title), h("div", { class: "s" }, t.artist))))] : null;
    // (no "On repeat": YouTube's home feed already has its own)
    const nowMix = forYou && forYou.now_mix && forYou.now_mix.tracks.length ? [h("h2", {}, forYou.now_mix.title, " ",
      h("button", { class: "link small", onclick: () => playList(forYou.now_mix.tracks, 0) }, "▶ Play all")),
    h("div", { class: "muted small", style: "margin:-6px 0 8px" }, forYou.now_mix.description),
    trackShelf("", forYou.now_mix.tracks)[1]] : null;
    const mine = forYou ? [forYou.more_like.length ? [h("h2", {}, "More like your top songs"), h("div", { class: "shelf" }, forYou.more_like.map(ytCard))] : null,
      trackShelf("Forgotten favourites", forYou.forgotten)] : null;
    const endless = h("div", { class: "row", style: "margin:4px 0 8px" },
      h("button", { onclick: () => startEndless() }, icon("shuffle", "ico lead"), "Never-ending discovery"),
      h("span", { class: "muted small" }, "New songs like yours. Thumbs down removes one."));
    if (view === "discover") show(discoverHero(forYou, fresh), endless, forYou && forYou.now_mix ? null : nowMix, newShelf, madeForYou, mine, shelves, chartShelf);
  } catch (e) { failed(e); }
}

// The banner at the top of Discover: the time-of-day mix (or the newest release), big.
function discoverHero(forYou, fresh) {
  const mix = forYou && forYou.now_mix && forYou.now_mix.tracks.length ? forYou.now_mix : null;
  if (mix) {
    const covers = [...new Map(mix.tracks.map((t) => [t.album, t])).values()].slice(0, 4);
    return h("div", { class: "d-hero", style: tintStyle(mix.tracks[0].colors) },
      h("div", {}, h("div", { class: "kicker" }, "Made for right now"), h("h1", {}, mix.title), h("p", {}, mix.description),
        h("div", { class: "row" }, h("button", { class: "primary", onclick: () => playList(mix.tracks, 0) }, icon("play", "ico lead"), "Play"),
          h("button", { onclick: () => playList(shuffle(mix.tracks), 0) }, icon("shuffle", "ico lead"), "Shuffle"))),
      covers.length >= 4 ? h("div", { class: "covers" }, covers.map((t) => h("img", { src: media(t.cover_url, 220), alt: "" }))) : null);
  }
  const r = fresh && fresh.items[0];
  if (r) {
    return h("div", { class: "d-hero" },
      h("div", {}, h("div", { class: "kicker" }, `New from ${r.artists.join(", ")}`), h("h1", {}, r.title),
        h("p", {}, [r.subtitle, r.year].filter(Boolean).join(" · ")),
        h("div", { class: "row" }, h("button", { class: "primary", onclick: () => viewCollection("album", r.id) }, icon("play", "ico lead"), "Open"))),
      r.thumbnail ? h("div", { class: "covers", style: "grid-template-columns:200px" }, h("img", { src: r.thumbnail, alt: "", style: "width:200px;height:200px" })) : null);
  }
  return h("h1", {}, "Discover");
}

function ytCard(item, from, list) {  // also used as .map(ytCard): (item, index, array)
  const origin = from === "library" ? "library" : "discover";
  const sub = item.artists.length ? item.artists.join(", ") : item.subtitle || "";
  const open = () => {
    if (item.type === "album" || item.type === "playlist") return viewCollection(item.type, item.id, origin);
    if (item.type === "song" || item.type === "video") return songActions(item, Array.isArray(list) ? list : [item]);
    if (item.type === "artist") return startRadio({ artist_id: item.id }, `${item.title} radio`);
  };
  return h("div", { class: "card", onclick: open, title: `${item.title}${sub ? " — " + sub : ""}` },
    art(item.thumbnail, item.type === "artist" ? "👤" : "♪"),
    h("div", { class: "t" }, item.title),
    h("div", { class: "s" }, item.library_track_id ? "✓ In library · " : "", sub));
}

// A YouTube item as something the player can play: from the library if it's there,
// otherwise relayed by Dielify from YouTube (which also downloads it next in line).
function ytAsTrack(item) {
  const lib = item.library_track_id;
  return {
    id: lib || null, video_id: item.id, title: item.title, artist: item.artists.join(", "), album: item.album || "",
    stream_url: lib ? `/api/library/tracks/${lib}/stream` : `/api/yt/stream/${encodeURIComponent(item.id)}`,
    cover_url: lib ? `/api/library/tracks/${lib}/cover` : null,
    thumb: lib ? null : item.thumbnail,  // YouTube's own picture: loaded without our key
  };
}

function songActions(item, list = [item]) {
  const songs = list.filter((i) => i.type === "song" || i.type === "video");
  const start = Math.max(0, songs.findIndex((i) => i.id === item.id));
  playList(songs.map(ytAsTrack), start);
  if (!item.library_track_id) toast(`Playing “${item.title}”, and saving it to your library`);
}

async function requestDownload(body) {
  try {
    const r = await api("/api/downloads", { method: "POST", body });
    const n = r.downloads.filter((d) => d.status !== "done").length;
    toast(n ? `Downloading ${n} song${n === 1 ? "" : "s"}… (see Downloads)` : "Already in your library");
    pollDownloads();
  } catch (e) { toast(e.message, 6000); }
}

async function viewCollection(type, id, from = "discover") {
  try {
    if (!restoring && here) backStack.push({ ...here, scroll: main.scrollTop }), (here = null);  // before "Loading…"
    show(skeleton("list"));
    const { info, tracks } = await api(`/api/yt/${type}/${encodeURIComponent(id)}`);
    const missing = tracks.filter((t) => !t.library_track_id).length;
    const have = tracks.filter((t) => t.library_track_id).map((t) => t.library_track_id);
    enter(`yt:${type}:${id}`, info.title, () => viewCollection(type, id, from), true);
    const back = from === "library"
      ? backButton("Playlists", () => { go("library"); viewLibrary("playlists"); })
      : backButton("Discover", () => go("discover"));
    show(back,
      h("div", { class: "hero" }, art(info.thumbnail, "♪", ""),
        h("div", {},
          h("div", { class: "muted small" }, type.toUpperCase()), h("h1", {}, info.title),
          h("div", { class: "muted" }, info.artists.join(", ") || info.subtitle || "", ` · ${tracks.length} songs`),
          h("div", { class: "row", style: "margin-top:12px" },
            h("button", { class: "primary", disabled: !missing, onclick: () => requestDownload({ type, id }) },
              missing ? `Download ${missing === tracks.length ? "all" : missing + " missing"}` : "All in library"),
            have.length ? h("button", { onclick: async () => playList(await Promise.all(have.map((i) => api(`/api/library/tracks/${i}`))), 0) },
              `▶ Play ${have.length} downloaded`) : null))),
      ytTrackTable(tracks));
  } catch (e) { failed(e); }
}

function ytTrackTable(items) {
  return h("table", { class: "tracks" }, h("tbody", {}, items.map((t, i) =>
    h("tr", {},
      h("td", { class: "n" }, i + 1),
      h("td", { class: "title", onclick: () => songActions(t, items) }, t.title,
        h("div", { class: "muted small" }, t.artists.join(", "), t.album ? ` · ${t.album}` : "")),
      h("td", { class: "d" }, dur(t.duration_s)),
      h("td", { class: "a" }, queueBtn(() => [ytAsTrack(t)]), ib("playlistAdd", "Add to playlist", () => addToPlaylist([t])),
        t.library_track_id
          ? h("span", { class: "ib in-lib", title: "In your library" }, icon("check"))
          : ib("download", "Download", () => requestDownload(
            { type: t.type, id: t.id, title: t.title, artists: t.artists, album: t.album, next: true })))))));
}

const searchCache = new Map();  // "type:q" -> [time, items]: going back shows the results at once
async function viewYtSearch(q, type = "song") {
  enter(`search:${type}:${q}`, `“${q}”`, () => viewYtSearch(q, type));
  try {
    await refreshStatus();
    if (status.offline) return show(h("h1", {}, "Search"), offlineNotice());
    const tabs = h("div", { class: "tabs" }, ["song", "album", "playlist", "video"].map((t) =>
      h("button", { class: t === type ? "active" : "", onclick: () => viewYtSearch(q, t) }, t[0].toUpperCase() + t.slice(1) + "s")));
    const cached = searchCache.get(`${type}:${q}`);
    let items;
    if (cached && Date.now() - cached[0] < 10 * 60 * 1000) items = cached[1];
    else {
      show(h("h1", {}, `“${q}” on YouTube Music`), tabs, h("p", { class: "muted" }, "Searching…"));
      ({ items } = await api(`/api/yt/search?q=${encodeURIComponent(q)}&type=${type}`));
      searchCache.set(`${type}:${q}`, [Date.now(), items]);
      if (searchCache.size > 30) searchCache.delete(searchCache.keys().next().value);
    }
    const body = !items.length ? h("p", { class: "muted" }, "No results.")
      : (type === "song" || type === "video") ? ytTrackTable(items) : h("div", { class: "grid" }, items.map(ytCard));
    show(h("h1", {}, `“${q}” on YouTube Music`), tabs, body);
  } catch (e) { failed(e); }
}

// --- downloads ------------------------------------------------------------------------------
let dlTimer = null;
async function pollDownloads() {
  clearTimeout(dlTimer);
  try {
    const active = await api("/api/downloads?active=true&limit=300");
    const badge = $("dl-badge");
    badge.hidden = !active.active_total; badge.textContent = active.active_total;
    if (view === "downloads") await renderDownloads(active);
    if (active.active_total || view === "downloads") dlTimer = setTimeout(pollDownloads, 1500);
  } catch { dlTimer = setTimeout(pollDownloads, 5000); }
}
async function viewDownloads() {
  enter("downloads", "Downloads", viewDownloads);
  show(h("h1", {}, "Downloads"), skeleton("list"));
  pollDownloads();
}
const minutes = (s) => (s < 90 ? "about a minute" : s < 5400 ? `about ${Math.round(s / 60)} min` : `about ${(s / 3600).toFixed(1)} hours`);

async function renderDownloads(active) {
  const { downloads: finished } = await api("/api/downloads?finished=true&limit=40");
  const { approvals } = (status.people || []).some((p) => p.role === "child")
    ? await api("/api/desktop/approvals").catch(() => ({ approvals: [] })) : { approvals: [] };
  const decide = async (ids, allow) => {
    await api("/api/desktop/approvals", { method: "POST", body: { ids, allow } });
    toast(allow ? "Allowed: it's downloading" : "Said no"); pollDownloads();
  };
  const asks = approvals.length ? [h("h2", {}, `Waiting for your OK (${approvals.length})`,
      approvals.length > 1 ? h("button", { style: "margin-left:12px; font-size:13px", onclick: () => decide(approvals.map((a) => a.id), true) }, "Allow all") : null),
    approvals.map((a) => h("div", { class: "job" },
      h("div", {}, h("div", {}, a.title), h("div", { class: "muted small" }, `${a.artist || ""} · asked by ${a.person}`)),
      h("div", { class: "row" }, h("button", { class: "primary", onclick: () => decide([a.id], true) }, "Allow"),
        h("button", { onclick: () => decide([a.id], false) }, "No"))))] : null;
  const label = { done: "Done", failed: "Failed", cancelled: "Cancelled" };
  const running = active.downloads.find((d) => d.status === "downloading" || d.status === "processing");
  const waiting = active.downloads.filter((d) => d.status === "queued" || d.status === "approval");
  const waitingTotal = active.active_total - (running ? 1 : 0);
  const pace = active.seconds_per_song || 20;
  const cancel = (d) => ib("close", "Cancel", async () => { await api(`/api/downloads/${d.id}`, { method: "DELETE" }); pollDownloads(); });
  const who = (d) => h("div", {}, h("div", {}, d.title),
    h("div", { class: "muted small" }, d.artist || "", d.error ? h("div", { class: "warn" }, d.error) : null));

  const summary = active.active_total
    ? h("p", { class: "muted" }, running ? `Downloading 1 song` : "Starting…",
        waitingTotal ? ` · ${waitingTotal} waiting · ${minutes(active.active_total * pace)} left` : "",
        " · one at a time, so YouTube doesn't mind")
    : h("p", { class: "muted" }, "Nothing waiting.");
  const now = running ? [h("h2", {}, "Now"), h("div", { class: "job" }, who(running),
    h("div", { class: "bar" }, h("div", { style: `width:${Math.round(running.progress * 100)}%` })), cancel(running))] : null;
  const line = waiting.length ? [h("h2", {}, `Waiting in line (${waitingTotal})`), waiting.map((d, i) => h("div", { class: "job" },
    who(d), h("div", { class: "small muted" }, `#${i + 1} in line · ${minutes((i + 1 + (running ? 1 : 0)) * pace)}`),
    h("div", {}, d.next || i === 0 ? null : ib("up", "Download this next", async () => { await api(`/api/downloads/${d.id}/next`, { method: "POST" }); pollDownloads(); }), cancel(d)))),
    waitingTotal > waiting.length ? h("p", { class: "muted small" }, `…and ${waitingTotal - waiting.length} more`) : null] : null;
  const clear = h("button", { style: "margin-left:12px; font-size:13px", onclick: async () => {
    const r = await api("/api/downloads/clear-finished", { method: "POST" });
    toast(`Cleared ${r.removed} finished download${r.removed === 1 ? "" : "s"}`);
    pollDownloads();
  } }, "Clear finished");
  const done = finished.length ? [h("h2", {}, "Finished", clear), finished.map((d) => h("div", { class: "job" }, who(d),
    h("div", { class: `small status-${d.status}` }, label[d.status]),
    d.track_id ? ib("play", "Play", async () => playList([await api(`/api/library/tracks/${d.track_id}`)], 0)) : h("span")))] : null;

  if (view !== "downloads") return;
  const keep = main.scrollTop;  // re-drawn every 1.5 s: don't jump back to the top
  show(h("h1", {}, "Downloads"), asks, summary, now, line, done);
  main.scrollTop = keep;
}

// --- playlists ---------------------------------------------------------------------------------
function describePlaylist(p) {
  if (p.kind === "mix") return `${p.count} songs · ${p.description || "Dielify mix"} · new every week`;
  if (p.kind === "smart") return `${p.count} songs · smart: ${p.description || ""}`;
  if (p.kind === "blend") return `${p.count} songs · Blend · new every week`;
  if (p.shared) return `${p.count} songs · ${p.mine ? "shared with the household" : `shared by ${p.owner}`}`;
  return [`${p.count} songs`, p.read_only ? "from YouTube Music (one way)" : p.yt_id ? "synced with YouTube Music" : "only in Dielify",
    p.pending ? `${p.pending} change${p.pending === 1 ? "" : "s"} waiting` : null].filter(Boolean).join(" · ");
}
const playlistCard = (p) => h("div", { class: "card", onclick: () => viewPlaylist(p.id) },
  p.id && p.count !== "" ? cardPlay(async () => { const d = await api(`/api/playlists/${p.id}`); const songs = d.entries.map((e) => e.item); if (songs.length) songActions(songs[0], songs); }) : null,
  art(p.cover_url ? media(p.cover_url, 360) : p.thumbnail),
  h("div", { class: "t" }, p.name), h("div", { class: "s" }, describePlaylist(p)));
const songIn = (i) => ({ id: i.id, type: i.type === "video" ? "video" : "song", title: i.title, artists: i.artists,
  album: i.album, duration_s: i.duration_s, thumbnail: i.thumbnail });

async function playlistAction(fn, done) {
  try { const r = await fn(); if (done) toast(done); paintSide(); return r; } catch (e) { toast(e.message, 6000); return null; }
}

// --- Blend: a weekly playlist with someone in the household (blend.py) --------------------------
async function fillBlend(box) {
  let b;
  try { b = await api("/api/blend"); } catch { return; }
  if (!b.partners.length && !b.waiting_for.length) return;  // nobody else in the household
  const toggle = async () => {
    try { await api("/api/blend", { method: "PUT", body: { on: !b.on } }); viewLibrary("playlists"); } catch (e) { toast(e.message, 6000); }
  };
  box.replaceChildren(h("div", { class: "row" }, h("h2", { style: "flex:1" }, "Blend"),
    b.allowed ? h("button", { class: b.on ? "" : "primary", onclick: toggle }, b.on ? "Turn Blend off" : "Turn Blend on") : null),
  h("p", { class: "muted small" }, !b.allowed ? "A parent needs to allow Blend for this account first."
    : !b.on ? `A weekly playlist with each person in your household who turns it on too: songs you both play, and each other's favourites.`
      : b.partners.length ? `You have a Blend with ${b.partners.join(", ")}. New every week.`
        : `Waiting for ${b.waiting_for.join(", ")} to turn Blend on.`),
  b.playlists.length ? h("div", { class: "grid" }, b.playlists.map((x) => playlistCard({ ...x, kind: "blend", count: "", thumbnail: null }))) : null);
}

// --- Jam: one shared queue for the household (jam.py) ------------------------------------------
// Every few seconds the app looks for a Jam. The host's player plays the Jam's songs and picks up
// new ones as people add them; guests see the queue and add songs.
const jamState = { jam: null, version: -1, busy: false };
async function pollJam() {
  if (jamState.busy) return;
  jamState.busy = true;
  try {
    const j = await api("/api/jam");
    const changed = (j ? j.version : -1) !== jamState.version || !!j !== !!jamState.jam;
    jamState.jam = j; jamState.version = j ? j.version : -1;
    paintJamNav();
    if (j && j.you_host && changed) hostJamSync(j);
    if (changed && view === "jam") viewJam();
  } catch { /* the server is busy or gone: try again shortly */ }
  jamState.busy = false;
}
setInterval(pollJam, 5000);
setTimeout(pollJam, 1500);
function paintJamNav() {
  const b = document.querySelector('#nav button[data-view="jam"]');
  const j = jamState.jam;
  b.classList.toggle("jam-on", !!j);
  $("jam-badge").hidden = !j;
  $("jam-badge").textContent = j ? String(j.members.length) : "";
}
const jamTrack = (s) => ({ ...ytAsTrack(s.item), jamId: s.id });
// The host: the player's list is the Jam's songs, kept on the song that's playing.
function hostJamSync(j) {
  const tracks = j.songs.map(jamTrack);
  if (!tracks.length) return;
  const cur = player.current && player.current.jamId;
  const at = cur ? tracks.findIndex((t) => t.jamId === cur) : -1;
  if (at >= 0) { player.list = tracks; player.index = at; player.endless = false; upnext.sig = ""; renderUpnext(); return; }
  if (!player.current || audio.paused || !player.jamHost) {  // start playing the Jam
    player.jamHost = true;
    player.list = tracks; player.endless = false; player.radio = null;
    playAt(Math.max(0, j.index));
  }
}
function reportJamPlaying(i) {
  const j = jamState.jam;
  if (!j || !j.you_host || !player.jamHost) return;
  api("/api/jam/playing", { method: "POST", body: { index: i } }).catch(() => {});
}
async function addToJam(tracks) {
  const songs = tracks.filter((t) => t.video_id).map((t) => ({ type: "song", id: t.video_id, title: t.title,
    artists: t.artist ? splitArtists(t.artist) : [], album: t.album || null }));
  if (!songs.length) return toast("Only songs from YouTube Music can go in a Jam");
  try {
    const j = await api("/api/jam/songs", { method: "POST", body: { songs } });
    toast(j.left_out.length ? `Added, but not: ${j.left_out.join("; ")}` : `Added to ${j.host}'s Jam`, j.left_out.length ? 7000 : 3000);
    pollJam();
  } catch (e) { toast(e.message, 6000); }
}
async function viewJam() {
  view = "jam";
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === "jam"));
  enter("jam", "Jam", viewJam);
  const j = jamState.jam;
  if (!j) {
    return show(h("h1", {}, "Jam"),
      h("p", { class: "muted" }, "One queue for everyone at home or in the car. This PC plays the music; everyone in your household can add songs from their phone or here."),
      h("button", { class: "primary", onclick: async () => {
        try {
          const keep = player.current && player.current.video_id ? [{ type: "song", id: player.current.video_id, title: player.current.title,
            artists: splitArtists(player.current.artist), album: player.current.album || null }] : [];
          jamState.jam = await api("/api/jam", { method: "POST", body: { device: (remote.devices.find((d) => d.device === remote.you) || {}).name || "the PC", songs: keep } });
          jamState.version = -1; player.jamHost = true; pollJam(); viewJam();
        } catch (e) { toast(e.message, 6000); }
      } }, "Start a Jam on this PC"));
  }
  const now = j.songs[j.index];
  const leave = async () => {
    try { await api(j.you_host ? "/api/jam" : "/api/jam/leave", { method: j.you_host ? "DELETE" : "POST" }); } catch (e) { toast(e.message, 6000); }
    player.jamHost = false; jamState.jam = null; jamState.version = -1; paintJamNav(); viewJam();
  };
  show(h("h1", {}, j.you_host ? "Your Jam" : `${j.host}'s Jam`),
    h("p", { class: "muted" }, `Playing on ${j.device} · ${j.members.join(", ")}`),
    h("div", { class: "row" },
      !j.you_host && !j.members.includes(status.active_profile) ? h("button", { class: "primary", onclick: async () => {
        try { const r = await api("/api/jam/join", { method: "POST" }); if (r.left_out.length) toast(`Taken out for the kids: ${r.left_out.join("; ")}`, 7000); pollJam(); } catch (e) { toast(e.message, 6000); }
      } }, "Join") : null,
      h("button", { onclick: leave }, j.you_host ? "End the Jam" : "Leave")),
    h("p", { class: "muted small" }, "Add songs from any song's queue menu (Add to Jam), on the PC or a phone."),
    now ? [h("h2", {}, "Playing now"), h("p", {}, h("b", {}, now.item.title), " · ", now.item.artists.join(", "), h("span", { class: "muted small" }, ` · added by ${now.added_by}`))] : null,
    h("h2", {}, "Up next"),
    h("table", { class: "tracks" }, h("tbody", {}, j.songs.slice(j.index + 1).map((x, i) => h("tr", {},
      h("td", { class: "n" }, i + 1),
      h("td", { class: "title" }, x.item.title, h("div", { class: "muted small" }, x.item.artists.join(", "), ` · added by ${x.added_by}`)),
      h("td", { class: "d" }, dur(x.item.duration_s)),
      h("td", { class: "a" }, j.you_host || x.added_by === status.active_profile ? ib("remove", "Take it out", async () => {
        try { await api(`/api/jam/songs/${x.id}`, { method: "DELETE" }); pollJam(); } catch (e) { toast(e.message, 6000); }
      }) : null))))),
    j.songs.length <= j.index + 1 ? h("p", { class: "muted" }, "Nothing queued yet.") : null);
}

// --- smart playlists (smart.py): the rule builder ---------------------------------------------
const SMART_FIELDS = {
  genre: ["Genre", "text"], artist: ["Artist", "text"], album: ["Album", "text"], title: ["Title", "text"],
  plays: ["Plays", "number"], year: ["Year", "number"], length_s: ["Length (seconds)", "number"],
  last_played: ["Last played", "days"], added: ["Added", "days"], rating: ["Rating", "rating"],
};
const SMART_OPS = {
  text: [["contains", "contains"], ["not_contains", "doesn't contain"], ["is", "is"], ["is_not", "is not"]],
  number: [["gt", "more than"], ["lt", "less than"], ["eq", "exactly"]],
  days: [["within", "in the last … days"], ["not_within", "not in the last … days"]],
  rating: [["is", "is"]],
};
const SMART_SORTS = [["random", "Shuffled (new order daily)"], ["most_played", "Most played"], ["least_played", "Least played"],
  ["recently_added", "Recently added"], ["recently_played", "Recently played"], ["title", "Title"], ["artist", "Artist"], ["year", "Year"]];
const select = (pairs, value) => {
  const el = h("select", {}, pairs.map(([v, l]) => h("option", { value: v }, l)));
  el.value = value;
  return el;
};
// New smart playlist (id = null) or change one's rules.
async function smartEditor(id = null) {
  let data = { name: "", rules: { match: "all", sort: "random", limit: 100, rules: [{ field: "genre", op: "contains", value: "" }] } };
  if (id) { try { data = await api(`/api/playlists/${id}/rules`); } catch (e) { return toast(e.message, 6000); } }
  const close = () => box.remove();
  const name = h("input", { type: "text", placeholder: "e.g. Rock I play a lot", value: data.name });
  const match = select([["all", "every rule"], ["any", "any rule"]], data.rules.match);
  const sort = select(SMART_SORTS, data.rules.sort);
  const limit = h("input", { type: "number", min: "1", max: "1000", value: String(data.rules.limit), style: "width:90px" });
  const rows = h("div", { class: "smart-rules" });
  const addRow = (r) => {
    const field = select(Object.entries(SMART_FIELDS).map(([k, [l]]) => [k, l]), r.field);
    const opBox = h("span", {}), valBox = h("span", {});
    let op, val;
    const paint = (keepOp, keepVal) => {
      const kind = SMART_FIELDS[field.value][1];
      op = select(SMART_OPS[kind], keepOp && SMART_OPS[kind].some(([v]) => v === keepOp) ? keepOp : SMART_OPS[kind][0][0]);
      val = kind === "rating" ? select([["up", "thumbs up"], ["down", "thumbs down"], ["none", "not rated"]], keepVal || "up")
        : h("input", { type: kind === "text" ? "text" : "number", value: keepVal ?? "", style: "width:160px",
          placeholder: kind === "days" ? "days" : kind === "number" ? "number" : "" });
      opBox.replaceChildren(op); valBox.replaceChildren(val);
    };
    field.addEventListener("change", () => paint());
    paint(r.op, r.value === "" || r.value == null ? "" : String(r.value));
    const row = h("div", { class: "row smart-rule" }, field, opBox, valBox,
      ib("remove", "Remove this rule", () => { row.remove(); }));
    row.read = () => ({ field: field.value, op: op.value, value: val.value });
    rows.append(row);
  };
  data.rules.rules.forEach(addRow);
  const save = async () => {
    const body = { name: name.value.trim(), rules: { match: match.value, sort: sort.value, limit: Number(limit.value) || 100,
      rules: [...rows.children].map((r) => r.read()) } };
    if (!body.name) return toast("Give it a name");
    try {
      const d = await api(id ? `/api/playlists/${id}/rules` : "/api/playlists/smart", { method: id ? "PUT" : "POST", body });
      close();
      toast(`${body.name}: ${d.entries.length} song${d.entries.length === 1 ? "" : "s"}`);
      viewPlaylist(d.playlist.id);
    } catch (e) { toast(e.message, 6000); }
  };
  const box = h("div", { class: "modal", onclick: (e) => { if (e.target === box) close(); } },
    h("div", { class: "panel smart-editor" }, h("h2", {}, id ? "Edit smart playlist" : "New smart playlist"),
      h("p", { class: "muted small" }, "Songs from your library that match the rules. The list keeps itself up to date."),
      h("label", {}, "Name ", name),
      h("div", { class: "row", style: "margin:10px 0 6px" }, "Songs that match ", match),
      rows,
      h("button", { class: "link", onclick: () => addRow({ field: "artist", op: "contains", value: "" }) }, "+ Add a rule"),
      h("div", { class: "row", style: "margin-top:10px" }, "Order ", sort, " At most ", limit, " songs"),
      h("div", { class: "row", style: "margin-top:14px" },
        h("button", { class: "primary", onclick: save }, id ? "Save" : "Create"), h("button", { onclick: close }, "Cancel"))));
  document.body.append(box);
  name.focus();
}

async function newPlaylist(items) {
  const name = (prompt("Name of the new playlist:") || "").trim();
  if (!name) return;
  const onYoutube = confirm("Also make it on YouTube Music (private), and keep the two the same?\n\nOK: on YouTube Music too\nCancel: only in Dielify");
  const d = await playlistAction(() => api("/api/playlists", { method: "POST", body: { name, on_youtube: onYoutube } }), `Created “${name}”`);
  if (d && items.length) await playlistAction(() => api(`/api/playlists/${d.playlist.id}/songs`, { method: "POST", body: { songs: items.map(songIn) } }),
    `Added to “${name}”`);
  if (d && view === "library") viewLibrary("playlists");
}

// "Add to playlist" chooser (a small pop-up over the current screen)
async function addToPlaylist(items) {
  const songs = items.filter((i) => i.type === "song" || i.type === "video");
  if (!songs.length) return;
  const { playlists } = await api("/api/playlists");
  const close = () => box.remove();
  const box = h("div", { class: "modal", onclick: (e) => { if (e.target === box) close(); } },
    h("div", { class: "panel" }, h("h2", {}, songs.length === 1 ? `Add “${songs[0].title}” to…` : `Add ${songs.length} songs to…`),
      h("button", { class: "primary", onclick: () => { close(); newPlaylist(songs); } }, "+ New playlist"),
      h("div", { class: "pick" }, playlists.filter((p) => !p.read_only).map((p) => h("button", { class: "pick-row", onclick: async () => {
        close();
        await playlistAction(() => api(`/api/playlists/${p.id}/songs`, { method: "POST", body: { songs: songs.map(songIn) } }), `Added to “${p.name}”`);
      } }, h("div", {}, p.name), h("div", { class: "muted small" }, describePlaylist(p))))),
      h("div", { class: "row", style: "margin-top:10px" }, h("button", { onclick: close }, "Cancel"))));
  document.body.append(box);
}

async function viewPlaylist(id) {
  try {
    const { playlist: p, entries } = await api(`/api/playlists/${id}`);
    enter(`playlist:${id}`, p.name, () => viewPlaylist(id), true);
    const songs = entries.map((e) => e.item);
    const have = songs.filter((s) => s.library_track_id).length;
    const rename = async () => {
      const name = (prompt("New name:", p.name) || "").trim();
      if (name && await playlistAction(() => api(`/api/playlists/${id}`, { method: "PATCH", body: { name } }), "Renamed")) viewPlaylist(id);
    };
    const del = async () => {
      if (!confirm(`Delete “${p.name}” from Dielify? Your downloaded songs are kept.`)) return;
      const both = p.yt_id && !p.read_only && confirm(`Also delete it on YouTube Music?\n\nOK: delete it there too\nCancel: keep it on YouTube Music (it stops syncing)`);
      if (await playlistAction(() => api(`/api/playlists/${id}?on_youtube=${!!both}`, { method: "DELETE" }), "Deleted") !== null) {
        go("library"); viewLibrary("playlists");
      }
    };
    const remove = async (e) => {
      if (p.yt_id && !confirm(`Remove “${e.item.title}”? This playlist is synced, so it's also removed on YouTube Music. The song stays in your library.`)) return;
      if (await playlistAction(() => api(`/api/playlists/${id}/entries/${e.entry_id}?on_youtube=${!!p.yt_id}`, { method: "DELETE" }), "Removed")) viewPlaylist(id);
    };
    show(backButton("Playlists", () => { go("library"); viewLibrary("playlists"); }),
      h("div", { class: "hero", style: tintStyle(p.colors) }, art(media(p.cover_url, 480) || p.thumbnail, "♪", ""),
        h("div", {}, h("div", { class: "muted small" }, "PLAYLIST"), h("h1", {}, p.name),
          h("div", { class: "muted" }, describePlaylist(p)),
          p.sync_error ? h("div", { class: "warn small" }, `Couldn't reach YouTube: ${p.sync_error}`) : null,
          have < songs.length ? h("div", { class: "muted small" }, `${songs.length - have} not on this PC yet: they're downloading. Play works anyway.`) : null,
          h("div", { class: "row", style: "margin-top:12px" },
            ibtn("play", "Play", { class: "primary", disabled: !songs.length, onclick: () => songActions(songs[0], songs) }),
            ibtn("shuffle", "Shuffle", { disabled: !songs.length, onclick: () => { const s = shuffle(songs); songActions(s[0], s); } }),
            ibtn("queueAdd", "Add to queue", { disabled: !songs.length, onclick: () => addToQueue(songs.map(ytAsTrack), false) }),
            p.yt_id ? ibtn("sync", "Sync now", { onclick: async () => { if (await playlistAction(() => api(`/api/playlists/${id}/sync`, { method: "POST" }), "Synced")) viewPlaylist(id); } }) : null,
            p.kind === "smart" ? ibtn("edit", "Edit rules", { onclick: () => smartEditor(p.id) }) : null,
            moreButton([
              p.read_only || !p.mine ? null : ["edit", "Rename", rename],
              p.mine && p.kind === "user" && !p.yt_id ? ["person", p.shared ? "Stop sharing" : "Share with household", async () => {
                if (await playlistAction(() => api(`/api/playlists/${id}/share`, { method: "PUT", body: { shared: !p.shared } }),
                  p.shared ? "Not shared any more" : "Shared with the household")) viewPlaylist(id); }] : null,
              p.kind === "mix" ? null : ["noTaste", isLeftOut("playlist", p.id) ? "Count in my taste again" : "Leave out of my taste",
                async () => { await setTaste("playlist", p.id, p.name, !isLeftOut("playlist", p.id)); viewPlaylist(id); }],
              p.kind === "mix" || p.kind === "blend" || !p.mine ? null : ["remove", "Delete playlist", del],
            ])),
          isLeftOut("playlist", p.id) ? h("div", { class: "muted small", style: "margin-top:6px" }, "Left out of your taste") : null)),
      h("table", { class: "tracks" }, h("tbody", {}, entries.map((e, i) => h("tr", {},
        h("td", { class: "n" }, i + 1),
        h("td", { class: "title", onclick: () => songActions(e.item, songs) }, e.item.title,
          h("div", { class: "muted small" }, e.item.artists.join(", "), e.item.album ? ` · ${e.item.album}` : "",
            p.shared && e.added_by ? ` · added by ${e.added_by}` : "")),
        h("td", { class: "d" }, dur(e.item.duration_s)),
        h("td", { class: "a" }, queueBtn(() => [ytAsTrack(e.item)]), e.item.library_track_id ? h("span", { class: "ib in-lib", title: "In your library" }, icon("check")) : null,
          p.read_only ? null : ib("remove", "Remove from this playlist", () => remove(e))))))));
  } catch (e) { failed(e); }
}

// --- stats -------------------------------------------------------------------------------------
let statsPeriod = "month";
async function viewStats(period = statsPeriod, who = null) {
  statsPeriod = period;
  enter(`stats:${who || ""}:${period}`, who ? `${who}'s stats` : "Stats", () => viewStats(period, who));
  try {
    const st = await api(who ? `/api/desktop/people/${encodeURIComponent(who)}/stats?period=${period}&limit=25`
      : `/api/stats?period=${period}&limit=25`);
    const title = who ? `${who}'s stats` : "Your stats";
    const tabs = h("div", { class: "tabs" }, [["week", "This week"], ["month", "This month"], ["year", "This year"], ["all", "All time"]]
      .map(([p, l]) => h("button", { class: p === period ? "active" : "", onclick: () => viewStats(p, who) }, l)),
      who ? null : h("button", { onclick: () => viewRecap() }, "Recaps"));
    if (!st.plays) {
      return show(h("h1", {}, title), tabs, h("p", { class: "muted" }, st.history_starts
        ? "Nothing played in this period." : "No plays recorded yet. Your history starts with the next song you play."));
    }
    const time = st.minutes < 120 ? `${st.minutes} min` : `${Math.round(st.minutes / 60)} hours`;
    const max = Math.max(1, ...st.by_hour);
    const chart = h("div", { class: "hours" }, st.by_hour.map((n, hr) =>
      h("div", { class: "bar", title: `${hr}:00 · ${n} plays`, style: `height:${Math.max(2, (n / max) * 100)}%` })));
    const songItems = st.top_songs.filter((s) => s.video_id).map((s) => ({ type: "song", id: s.video_id, title: s.title,
      artists: s.artist ? [s.artist] : [], album: s.album, thumbnail: s.thumbnail, library_track_id: s.track_id }));
    const row = (i, img, title, sub, count, onclick) => h("tr", { onclick, style: onclick ? "cursor:pointer" : "" },
      h("td", { class: "n" }, i + 1), h("td", { style: "width:52px" }, img),
      h("td", {}, title, h("div", { class: "muted small" }, sub)), h("td", { class: "d" }, count));
    const pic = (cover, thumb) => cover ? art(media(cover, 96), "♪", "mini") : thumb ? art(thumb, "♪", "mini") : art(null, "♪", "mini");
    show(h("h1", {}, "Your stats"), tabs,
      h("div", { class: "stat-cards" }, [[time, "listened"], [st.plays, "plays"], [st.songs, "songs"], [st.artists, "artists"]]
        .map(([v, l]) => h("div", { class: "panel stat" }, h("div", { class: "big" }, String(v)), h("div", { class: "muted small" }, l)))),
      h("h2", {}, "When you listen"), chart,
      h("div", { class: "muted small hours-axis" }, h("span", {}, "12am"), h("span", {}, "6am"), h("span", {}, "12pm"), h("span", {}, "6pm"), h("span", {}, "")),
      h("h2", {}, "Top songs"), h("table", { class: "tracks" }, h("tbody", {}, st.top_songs.map((s, i) =>
        row(i, pic(s.cover_url, s.thumbnail), s.title, [s.artist, s.album].filter(Boolean).join(" · "), `${s.plays}×`,
          s.video_id ? () => songActions(songItems.find((x) => x.id === s.video_id), songItems) : null)))),
      h("h2", {}, "Top artists"), h("table", { class: "tracks" }, h("tbody", {}, st.top_artists.map((a, i) =>
        row(i, pic(a.cover_url), a.name, `${a.minutes} min`, `${a.plays}×`, a.artist_id ? () => { go("library"); viewArtist(a.artist_id); } : null)))),
      h("h2", {}, "Top albums"), h("table", { class: "tracks" }, h("tbody", {}, st.top_albums.map((a, i) =>
        row(i, pic(a.cover_url), a.name, a.artist || "", `${a.plays}×`, null)))),
      h("p", { class: "muted small" }, `${st.skips} skipped (under half a song) not counted.`,
        st.history_starts ? ` History since ${new Date(st.history_starts * 1000).toLocaleDateString()}.` : ""));
  } catch (e) { failed(e); }
}

// --- recap: year in review (December edition) and any month (recap.py) ----------------------------
async function viewRecap(period = null) {
  enter(`recap:${period || ""}`, "Recap", () => viewRecap(period));
  try {
    const { periods } = await api("/api/recap/periods");
    if (!periods.length) return show(h("h1", {}, "Recaps"), h("p", { class: "muted" }, "Play some music first: recaps come from your play history."));
    period = period || periods[0].period;
    const r = await api(`/api/recap?period=${period}`);
    const pick = select(periods.map((p) => [p.period, p.title]), period);
    pick.addEventListener("change", () => viewRecap(pick.value));
    const pic = (cover, thumb) => cover ? art(media(cover, 96), "♪", "mini") : thumb ? art(thumb, "♪", "mini") : art(null, "♪", "mini");
    const hours = r.minutes < 120 ? `${r.minutes} minutes` : `${Math.round(r.minutes / 60).toLocaleString()} hours`;
    const hr = (x) => x == null ? "" : `${x % 12 || 12}${x < 12 ? "am" : "pm"}`;
    const list = (items, line) => h("ol", { class: "recap-list" }, items.map((x) => h("li", {}, ...line(x))));
    show(h("div", { class: "row" }, backButton("Stats", () => viewStats()), pick),
      h("h1", { class: "recap-title" }, r.title),
      h("div", { class: "stat-cards" }, [[hours, "of music"], [r.plays.toLocaleString(), "plays"], [r.songs, "songs"],
        [r.artists, "artists"], [r.days_listened, "days with music"], [r.longest_streak_days, "days in a row (best)"]]
        .map(([v, l]) => h("div", { class: "panel stat" }, h("div", { class: "big" }, String(v)), h("div", { class: "muted small" }, l)))),
      r.top_songs.length ? [h("h2", {}, "Your top songs"), list(r.top_songs, (s) =>
        [pic(s.cover_url, s.thumbnail), h("span", {}, h("b", {}, s.title), h("div", { class: "muted small" }, `${s.artist || ""} · ${s.plays} plays`))])] : null,
      r.top_artists.length ? [h("h2", {}, "Your top artists"), list(r.top_artists, (a) =>
        [pic(a.cover_url), h("span", {}, h("b", {}, a.name), h("div", { class: "muted small" }, `${a.plays} plays · ${a.minutes} min`))])] : null,
      r.top_genres.length ? [h("h2", {}, "Your genres"), h("div", { class: "row chips" }, r.top_genres.map((g) => h("span", { class: "chip" }, g.name)))] : null,
      r.top_albums.length ? [h("h2", {}, "Albums on repeat"), list(r.top_albums, (a) =>
        [pic(a.cover_url), h("span", {}, h("b", {}, a.name), h("div", { class: "muted small" }, `${a.artist || ""} · ${a.plays} plays`))])] : null,
      h("h2", {}, "Moments"),
      h("ul", { class: "recap-moments" },
        r.first_song ? h("li", {}, `First song: ${r.first_song.title}${r.first_song.artist ? " by " + r.first_song.artist : ""}, ${new Date(r.first_song.started_at * 1000).toLocaleDateString()}`) : null,
        r.busiest_day ? h("li", {}, `Biggest day: ${new Date(r.busiest_day.date + "T12:00").toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}, ${r.busiest_day.minutes} minutes`) : null,
        r.favourite_hour != null ? h("li", {}, `Favourite time: around ${hr(r.favourite_hour)}`) : null,
        r.new_artists ? h("li", {}, `${r.new_artists} new artist${r.new_artists === 1 ? "" : "s"}${r.top_new_artists.length ? ", most of all " + r.top_new_artists.slice(0, 3).map((a) => a.name).join(", ") : ""}`) : null));
  } catch (e) { failed(e); }
}

// --- settings --------------------------------------------------------------------------------
async function saveSettings(body, msg = "Saved") {
  try { await api("/api/desktop/settings", { method: "PUT", body }); toast(msg); } catch (e) { toast(e.message, 6000); }
  viewSettings();
}

async function signIn(fresh) {
  const app = desktopApp();
  if (!app) return toast("Sign in from the Dielify app on the PC, not from a browser.");
  toast("A sign-in window has opened. Sign in there.", 6000);
  const r = await app.sign_in(status.active_profile, fresh);
  if (r.ok) toast(`Signed in as ${r.account}`);
  else if (r.error) toast(r.error, 8000);
  go(view);
}

let settingsTab = 0;
async function viewSettings() {
  enter("settings", "Settings", viewSettings);
  try {
    const s = await refreshStatus();
    const p = s.profiles.find((x) => x.name === s.active_profile) || { library_path: s.library_root, youtube_signed_in: false };
    const app = desktopApp();
    const setting = (label, value, ...controls) => h("div", { class: "setting" }, h("div", { class: "label" }, label),
      h("div", { class: "value" }, value), ...controls);
    const select = (key, options, current) => h("select", { onchange: (e) => saveSettings({ [key]: e.target.value }) },
      Object.entries(options).map(([v, l]) => h("option", { value: v, selected: v === current }, l)));
    const toggle = (key, on, msgOn, msgOff) => h("input", { type: "checkbox", checked: on,
      onchange: (e) => saveSettings({ [key]: e.target.checked }, e.target.checked ? msgOn : msgOff) });

    const youtube = h("div", { class: "panel" }, h("h2", {}, "YouTube Music"),
      setting("Profile", s.active_profile,
        s.profiles.length > 1 ? select("active_profile", Object.fromEntries(s.profiles.map((x) => [x.name, x.name])), s.active_profile) : null,
        h("button", { onclick: addProfile }, "New profile")),
      setting("Sign-in", p.youtube_signed_in ? h("span", { class: "ok" }, "Signed in ✓") : h("span", { class: "warn" }, "Not signed in"),
        h("button", { class: p.youtube_signed_in ? "" : "primary", onclick: () => signIn(false) }, p.youtube_signed_in ? "Sign in again" : "Sign in"),
        p.youtube_signed_in ? h("button", { onclick: async () => {
          if (!confirm("Sign this profile out of YouTube Music on this PC?")) return;
          await api(`/api/desktop/youtube/${encodeURIComponent(s.active_profile)}`, { method: "DELETE" });
          if (app) await app.clear_sign_in();
          viewSettings();
        } }, "Sign out") : null),
      setting("Offline mode", s.offline ? "On: Dielify doesn't contact YouTube" : "Off",
        toggle("offline", s.offline, "Offline mode on", "Offline mode off")));

    const music = h("div", { class: "panel" }, h("h2", {}, "Music"),
      setting("Music folder", p.library_path,
        app ? h("button", { onclick: async () => {
          const dir = await app.pick_folder();
          if (dir) saveSettings({ library_root: dir }, "Music folder changed");
        } }, "Change…") : null,
        app ? h("button", { onclick: () => app.open_library() }, "Open") : null,
        h("button", { onclick: async () => {
          const r = await api("/api/desktop/scan", { method: "POST" });
          toast(`Scanned: ${r.added} added, ${r.removed} removed`); viewSettings();
        } }, "Rescan")),
      setting("Quality", "", select("quality", { auto: "Best available (Premium: ~256 kbps)", high: "High", standard: "Standard (up to ~160 kbps)" }, s.quality)),
      setting("Format", "", select("preferred_format", { auto: "Automatic (kept as YouTube sends it)", opus: "Prefer Opus", m4a: "Prefer AAC (.m4a)" }, s.preferred_format)));

    const windows = h("div", { class: "panel" }, h("h2", {}, "Windows"),
      setting("Start with Windows", s.start_with_windows ? "On: Dielify starts in the tray when you sign in" : "Off",
        toggle("start_with_windows", s.start_with_windows, "Dielify will start with Windows", "Dielify won't start with Windows")),
      setting("Keep this PC awake", s.keep_awake
        ? "On: Windows won't sleep when idle, so your phone can always reach it (the screen can still turn off)"
        : "Off: if the PC sleeps, phones can't reach it",
        toggle("keep_awake", s.keep_awake, "The PC will stay awake", "The PC may sleep again")));

    const phones = h("div", { class: "panel" }, h("h2", {}, "Phone apps"),
      h("p", { class: "muted" }, "Phones can play your library (Symfonium, or the Dielify app later). Server address:"),
      s.addresses.length
        ? s.addresses.map((a) => h("div", { class: "setting" },
            h("div", { class: "label" }, /^http:\/\/100\./.test(a) ? "Away from home (Tailscale)" : "On home Wi-Fi"),
            h("div", { class: "value secret" }, a)))
        : h("p", { class: "warn" }, "No network address found."),
      s.addresses.some((a) => /^http:\/\/100\./.test(a)) ? null
        : h("p", { class: "muted small" }, "Away from home: install Tailscale on this PC and your phone (see Phase 5 in the README)."),
      s.phone_users.map((u) => h("div", { class: "setting" },
        h("div", { class: "label" }, u.name),
        h("div", { class: "value" }, `${u.profile}'s library`,
          u.devices.map((d) => h("div", { class: "small muted" }, `${d.device_name} · last used ${d.last_used_at ? new Date(d.last_used_at * 1000).toLocaleString() : "never"} `,
            h("button", { class: "link", onclick: async () => { await api(`/api/desktop/devices/${d.id}`, { method: "DELETE" }); viewSettings(); } }, "Sign out")))),
        h("button", { onclick: async () => {
          if (!confirm(`Make a new password for ${u.name}? The old one stops working.`)) return;
          showPassword(await api(`/api/desktop/phone-users/${encodeURIComponent(u.name)}/password`, { method: "POST" }));
        } }, "New password"),
        h("button", { onclick: async () => {
          if (!confirm(`Remove the phone login ${u.name}? Its phones are signed out.`)) return;
          await api(`/api/desktop/phone-users/${encodeURIComponent(u.name)}`, { method: "DELETE" }); viewSettings();
        } }, "Remove"))),
      h("div", { class: "row", style: "margin-top:10px" }, h("button", { onclick: addPhoneUser }, "Add phone login"),
        h("button", { onclick: () => addTv() }, icon("tv", "ico lead"), "Add a TV")));

    const when = (t) => new Date(t * 1000).toLocaleString();
    const backups = h("div", { class: "panel" }, h("h2", {}, "Backups"),
      h("p", { class: "muted small" }, "A daily copy of Dielify's own data: play counts, stars, the download list, settings and logins (the logins stay encrypted, readable only by your Windows account). Not the music itself: your music files carry their own tags. The last 14 are kept."),
      s.backup_folder
        ? [setting("Folder", s.backup_folder,
            app ? h("button", { onclick: async () => {
              const dir = await app.pick_folder();
              if (dir) saveSettings({ backup_folder: dir }, "Backup folder changed");
            } }, "Change…") : null,
            h("button", { onclick: () => saveSettings({ backup_folder: "" }, "Backups off") }, "Turn off")),
          setting("Last backup", s.last_backup_at ? when(s.last_backup_at) : "None yet",
            h("button", { onclick: async () => {
              try { await api("/api/desktop/backup", { method: "POST" }); toast("Backup written"); } catch (e) { toast(e.message, 6000); }
              viewSettings();
            } }, "Back up now")),
          s.backup_error ? h("p", { class: "warn" }, `Last backup failed: ${s.backup_error}`) : null,
          h("p", { class: "muted small" }, "To restore: quit Dielify (tray icon > Quit), then run dielify-cli backup restore \"<backup file>\".")]
        : setting("Backups", "Off",
            h("button", { class: "primary", onclick: () => saveSettings({ backup_folder: s.backup_suggested }, "Backups on") },
              `Turn on (${s.backup_suggested})`),
            app ? h("button", { onclick: async () => {
              const dir = await app.pick_folder();
              if (dir) saveSettings({ backup_folder: dir }, "Backups on");
            } }, "Choose folder…") : null));

    const about = h("div", { class: "panel" }, h("h2", {}, "About"), setting("Version", `Dielify ${s.version}`),
      setting("Data folder", s.data_folder), setting("Log file", s.log_file),
      await updateSetting(setting));
    await refreshRatings();
    const sections = [
      ["Playback", [playbackPanel()]],
      ["Music & YouTube", [youtube, music]],
      ["People & phones", [peoplePanel(s), phones]],
      ["Your taste", [ratingsPanel(), tastePanel(), await newReleasesPanel()]],
      ["This PC", [windows, backups, about]],
    ];
    const body = h("div", {});
    const tabs = h("div", { class: "tabs settings-tabs" });
    const pick = (i) => {
      settingsTab = i;
      tabs.querySelectorAll("button").forEach((b, k) => b.classList.toggle("active", k === i));
      body.replaceChildren(...sections[i][1].filter(Boolean));
    };
    tabs.replaceChildren(...sections.map(([label], i) => h("button", { onclick: () => pick(i) }, label)));
    show(h("h1", {}, "Settings"), tabs, body);
    pick(Math.min(settingsTab, sections.length - 1));
  } catch (e) { failed(e); }
}

// --- updates ----------------------------------------------------------------------------------
function showUpdatePill(u) {
  const pill = $("update-pill");
  pill.hidden = !(u && u.available && !u.installing);
  if (u && u.latest) pill.textContent = `Update ${u.latest}`;
}

async function updateSetting(setting) {
  const u = await api("/api/desktop/update").catch(() => null);
  if (!u) return null;
  showUpdatePill(u);
  const checked = u.checked_at ? ` (checked ${new Date(u.checked_at * 1000).toLocaleString()})` : "";
  let text;
  if (!u.configured) text = h("span", { class: "muted" }, "Updates aren't set up yet.");
  else if (u.installing) text = "Installing the update… Dielify will close and reopen.";
  else if (u.available) text = h("span", { class: "ok" }, `Dielify ${u.latest} is available`,
    u.size ? ` (${Math.round(u.size / 1e6)} MB)` : "", u.notes ? h("div", { class: "muted small" }, u.notes) : null);
  else if (u.error) text = h("span", { class: "muted" }, u.error);
  else if (u.latest) text = `Up to date${checked}`;
  else text = "Not checked yet";
  const check = h("button", { disabled: !u.configured || u.installing, onclick: async (e) => {
    e.target.disabled = true; e.target.textContent = "Checking…";
    await api("/api/desktop/update/check", { method: "POST" }).catch((err) => toast(err.message, 6000));
    viewSettings();
  } }, "Check for updates");
  const install = u.available && !u.installing ? h("button", { class: "primary", onclick: async (e) => {
    if (!confirm(`Install Dielify ${u.latest}? Dielify closes, updates and opens again. Phones lose the connection for a minute.`)) return;
    e.target.disabled = true; e.target.textContent = "Downloading…";
    try {
      await api("/api/desktop/update/install", { method: "POST" });
      show(h("div", { class: "panel" }, h("h2", {}, "Installing the update"),
        h("p", {}, "Dielify will close now and open again in a minute.")));
    } catch (err) { toast(err.message, 8000); viewSettings(); }
  } }, "Install update") : null;
  return setting("Updates", text, check, install);
}

// People sharing this PC's music: you (parent) and kids accounts. A kids account uses this
// PC's music folder and YouTube sign-in behind the scenes, has its own library, and never
// sees your YouTube (home feed, charts, your playlists).
function peoplePanel(s) {
  const people = s.people || [];
  const songs = (n) => `${n.toLocaleString()} song${n === 1 ? "" : "s"}`;
  return h("div", { class: "panel" }, h("h2", {}, "People"),
    h("p", { class: "muted small" }, "Everyone here shares this PC's music files. Each person has their own library, play history, likes and playlists."),
    people.map((p) => h("div", { class: "setting" },
      h("div", { class: "label" }, icon("person", "ico lead"), p.name),
      h("div", { class: "value" }, p.role === "child" ? `Kids account · ${songs(p.tracks)}` : `Parent · ${songs(p.tracks)}`,
        p.waiting ? h("div", { class: "warn small" }, `${p.waiting} download${p.waiting === 1 ? "" : "s"} waiting for your OK (Downloads)`) : null,
        p.role === "child" ? h("div", { class: "small muted" },
          `Uses ${p.store}'s music folder and YouTube sign-in. Phone login: ${p.logins.join(", ") || "none"}`) : null),
      p.role === "child" ? [
        h("button", { class: "primary", onclick: () => viewKidControls(p.name) }, "Controls"),
        h("button", { onclick: async () => {
          const login = p.logins[0];
          if (!login) return toast("No phone login for this account", 5000);
          if (!confirm(`Make a new password for ${p.name}? The old one stops working.`)) return;
          showPassword(await api(`/api/desktop/phone-users/${encodeURIComponent(login)}/password`, { method: "POST" }));
        } }, "New password"),
        h("button", { onclick: async () => {
          if (!confirm(`Remove ${p.name}'s account? Their phone is signed out and their library, history and playlists are deleted. Music files stay on this PC.`)) return;
          try { await api(`/api/desktop/people/${encodeURIComponent(p.name)}`, { method: "DELETE" }); toast(`Removed ${p.name}`); }
          catch (e) { toast(e.message, 6000); }
          viewSettings();
        } }, "Remove")] : null)),
    h("div", { class: "row", style: "margin-top:10px" }, h("button", { onclick: addChild }, icon("add", "ico lead"), "Add a kids account")));
}
// A kids account's controls (PC only). Every change saves at once.
async function viewKidControls(name) {
  let c;
  try { c = await api(`/api/desktop/people/${encodeURIComponent(name)}/controls`); } catch (e) { return failed(e); }
  const save = async (changes, msg) => {
    try { c = await api(`/api/desktop/people/${encodeURIComponent(name)}/controls`, { method: "PUT", body: { ...c, ...changes } });
      if (msg) toast(msg); }
    catch (e) { toast(e.message, 6000); }
    const keep = main.scrollTop;  // stay where you were on the page
    await viewKidControls(name);
    main.scrollTop = keep;
  };
  const row = (label, help, ...controls) => h("div", { class: "setting" },
    h("div", { class: "label" }, label), h("div", { class: "value" }, help ? h("span", { class: "small muted" }, help) : ""), ...controls);
  const check = (key, label, help) => row(label, help, h("input", { type: "checkbox", checked: c[key],
    onchange: (e) => save({ [key]: e.target.checked }, `${label}: ${e.target.checked ? "on" : "off"}`) }));
  const select = (key, options) => h("select", { onchange: (e) => save({ [key]: e.target.value }) },
    Object.entries(options).map(([v, l]) => h("option", { value: v, selected: v === c[key] }, l)));
  const list = (key, label, help, placeholder) => {
    const input = h("input", { type: "text", placeholder, style: "max-width:240px" });
    const add = () => { const v = input.value.trim(); if (v) save({ [key]: [...c[key], v] }, `Added “${v}”`); };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
    return h("div", { class: "setting" }, h("div", { class: "label" }, label),
      h("div", { class: "value" }, h("div", { class: "small muted" }, help),
        h("div", { class: "chips" }, c[key].map((v, i) => h("span", { class: "chip" }, v,
          h("button", { class: "link", title: "Remove", onclick: () => save({ [key]: c[key].filter((_, j) => j !== i) }) }, " ✕"))))),
      input, h("button", { onclick: add }, "Add"));
  };

  const content = h("div", { class: "panel" }, h("h2", {}, "Songs"),
    row("Explicit songs", "YouTube Music marks explicit songs. Songs without a mark are checked before she gets them.",
      select("explicit", { block: "Block", allow: "Allow" })),
    c.explicit === "block" ? check("clean_versions", "Offer clean versions", "When a song is explicit, give her the clean version if YouTube has one") : null,
    check("lyrics_check", "Check words", "Also block songs whose title uses strong language (a built-in list, plus your words below)"),
    c.lyrics_check ? list("extra_words", "Your words", "Extra words to block", "a word") : null,
    list("blocked_artists", "Blocked artists", "She never gets these artists", "artist name"),
    c.blocked_songs.length ? h("div", { class: "setting" }, h("div", { class: "label" }, "Blocked songs"),
      h("div", { class: "value" }, h("div", { class: "chips" }, c.blocked_songs.map((b, i) => h("span", { class: "chip" }, b.title || b.id,
        h("button", { class: "link", onclick: () => save({ blocked_songs: c.blocked_songs.filter((_, j) => j !== i) }) }, " ✕")))))) : null);

  const getting = h("div", { class: "panel" }, h("h2", {}, "Getting music"),
    row("New downloads", null, select("downloads", { auto: "Download straight away", approve: "Wait for my OK (Downloads page)" })),
    row("Download limit", "New songs per day (0 = none)", h("input", { type: "number", min: 0, max: 1000, value: c.daily_limit, style: "width:90px",
      onchange: (e) => save({ daily_limit: Math.max(0, Math.min(1000, Number(e.target.value) || 0)) }, "Limit saved") })),
    check("youtube_search", "YouTube search", "Off: she only gets the household's songs and your picks"),
    check("discovery_play", "Never-ending discovery", "New songs like the ones she plays (filtered like everything else)"));

  const time = (key) => h("input", { type: "time", value: c[key], onchange: (e) => save({ [key]: e.target.value }, "Quiet hours saved") });
  const when = h("div", { class: "panel" }, h("h2", {}, "Listening"),
    check("quiet_hours", "Quiet hours", "No music in her account at these times (songs saved on her phone still play)"),
    c.quiet_hours ? row("From", null, time("quiet_from"), h("span", { class: "muted" }, " to "), time("quiet_to")) : null,
    check("blend", "Blend", "She may make a weekly Blend playlist with someone in the household (filtered for her)"),
    check("jam", "Jams", "She may join a Jam (every song in it then has to pass her controls)"),
    check("parent_sees_stats", "You can see her stats", "Her top songs and listening time, on this PC"),
    c.parent_sees_stats ? h("div", { class: "row" }, h("button", { onclick: () => viewStats("month", name) }, `See ${name}'s stats`)) : null);

  // Picked for her: a shelf on her Discover page
  const results = h("div", {});
  const q = h("input", { type: "search", placeholder: "Search YouTube Music: an album, artist or playlist", style: "max-width:360px" });
  const kind = h("select", {}, [["album", "Albums"], ["artist", "Artists"], ["playlist", "Playlists"], ["song", "Songs"]].map(([v, l]) => h("option", { value: v }, l)));
  const find = async () => {
    if (!q.value.trim()) return;
    results.replaceChildren(h("p", { class: "muted" }, "Searching…"));
    try {
      const { items } = await api(`/api/yt/search?type=${kind.value}&limit=12&q=${encodeURIComponent(q.value.trim())}`);
      const picked = new Set(c.picks.map((x) => x.id));
      results.replaceChildren(...items.map((it) => h("div", { class: "job" },
        h("div", {}, h("div", {}, it.title, it.explicit ? h("span", { class: "warn small" }, " · explicit") : null),
          h("div", { class: "muted small" }, (it.artists || []).join(", ") || it.subtitle || "")),
        picked.has(it.id) ? h("span", { class: "muted small" }, "Picked")
          : h("button", { onclick: () => save({ picks: [...c.picks, it] }, `Picked “${it.title}” for ${name}`) }, "Pick"))));
    } catch (e) { results.replaceChildren(h("p", { class: "warn" }, e.message)); }
  };
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") find(); });
  const picks = h("div", { class: "panel" }, h("h2", {}, `Picked for ${name}`),
    h("p", { class: "muted small" }, `These show at the top of ${name}'s Discover page. Explicit ones are still filtered out.`),
    c.picks.length ? c.picks.map((it, i) => h("div", { class: "job" },
      h("div", {}, h("div", {}, it.title), h("div", { class: "muted small" }, `${it.type} · ${(it.artists || []).join(", ") || it.subtitle || ""}`)),
      h("button", { onclick: () => save({ picks: c.picks.filter((_, j) => j !== i) }, "Removed") }, "Remove")))
      : h("p", { class: "muted" }, "Nothing picked yet."),
    h("div", { class: "row", style: "margin-top:10px" }, q, kind, h("button", { onclick: find }, "Search")), results);

  show(h("button", { onclick: viewSettings }, icon("back", "ico lead"), "Settings"),
    h("h1", { style: "margin-top:16px" }, `${name}'s controls`),
    h("p", { class: "muted" }, `${name} uses this PC's music and your YouTube sign-in behind the scenes, but never sees your YouTube. Everything she gets goes through these controls. Changes apply at once.`),
    content, getting, when, picks);
}

async function addChild() {
  const name = prompt("Name for the kids account (letters and numbers, e.g. emma). It's also the name they sign in with on their phone:");
  if (!name) return;
  try { showPassword(await api("/api/desktop/people", { method: "POST", body: { name: name.trim() } })); }
  catch (e) { toast(e.message, 6000); }
}

async function addProfile() {
  const name = prompt("Name for the new profile (letters and numbers, e.g. emma):");
  if (!name) return;
  try { await api("/api/desktop/profiles", { method: "POST", body: { name: name.trim() } }); toast(`Switched to ${name}`); }
  catch (e) { toast(e.message, 6000); }
  viewSettings();
}
async function addPhoneUser() {
  const name = prompt("Name for this phone login (e.g. josh):", status.active_profile);
  if (!name) return;
  try { showPassword(await api("/api/desktop/phone-users", { method: "POST", body: { name: name.trim() } })); }
  catch (e) { toast(e.message, 6000); }
}
// A TV shows a code (and a QR code for phones): type it here to sign the TV in (pair_api.py).
async function addTv(code) {
  code = code || prompt("The code on the TV (e.g. KDW7-RT3P):");
  if (!code) return;
  let info;
  try { info = await api(`/api/pair/${encodeURIComponent(code.trim())}`); } catch (e) { return toast(e.message, 6000); }
  const pick = h("select", {}, info.people.map((p) => h("option", { value: p.name, disabled: !p.can_sign_in,
    selected: p.name === info.suggested }, `${p.name}${p.role === "child" ? " (kids account)" : ""}${p.can_sign_in ? "" : " (no phone login yet)"}`)));
  show(h("h1", {}, "Sign in a TV"), h("div", { class: "panel" },
    h("p", {}, "Only allow a TV you can see showing this code."),
    h("div", { class: "setting" }, h("div", { class: "label" }, "TV"), h("div", { class: "value" }, info.device_name)),
    h("div", { class: "setting" }, h("div", { class: "label" }, "Its address"), h("div", { class: "value" }, info.address)),
    h("div", { class: "setting" }, h("div", { class: "label" }, "Code"), h("div", { class: "value" }, info.code)),
    h("div", { class: "setting" }, h("div", { class: "label" }, "Whose music it plays"), h("div", { class: "value" }, pick)),
    h("div", { class: "row", style: "margin-top:12px" },
      h("button", { class: "primary", onclick: async () => {
        try {
          const r = await api(`/api/pair/${encodeURIComponent(info.code)}/approve`, { method: "POST", body: { person: pick.value } });
          toast(`${r.device_name} is signed in for ${r.person}`);
          viewSettings();
        } catch (e) { toast(e.message, 6000); }
      } }, "Allow"),
      h("button", { onclick: async () => {
        await api(`/api/pair/${encodeURIComponent(info.code)}/refuse`, { method: "POST" }).catch(() => {});
        viewSettings();
      } }, "Don't allow"))));
}
function showPassword(login) {
  show(h("h1", {}, "Phone login"), h("div", { class: "panel" },
    h("p", {}, "Type these into the phone app now. The password is shown only this once."),
    (status.addresses || []).map((a) => h("div", { class: "setting" },
      h("div", { class: "label" }, /^http:\/\/100\./.test(a) ? "PC address away from home (Tailscale)" : "PC address on home Wi-Fi"),
      h("div", { class: "value" }, a))),
    h("div", { class: "setting" }, h("div", { class: "label" }, "Phone login name"), h("div", { class: "value secret" }, login.name)),
    h("div", { class: "setting" }, h("div", { class: "label" }, "Password"), h("div", { class: "value secret" }, login.password)),
    h("div", { class: "row", style: "margin-top:12px" }, h("button", { class: "primary", onclick: viewSettings }, "Done"))));
}

// --- player ------------------------------------------------------------------------------------
// Like Spotify Connect: the player bar shows and controls the *active* device, which may be
// this PC or a phone. Songs started here play on the active device; the device button in the
// bar moves the music between devices.
// Two audio elements: the next song loads in the spare one near the end of this one, so it
// starts without a gap (gapless albums, no loading pause). `audio` is the one playing.
const audios = [$("audio"), new Audio()];
audios[1].preload = "auto";
let audio = audios[0];
const onAudio = (ev, fn) => audios.forEach((a) => a.addEventListener(ev, (e) => { if (e.target === audio) fn(e); }));
[["btn-prev", "prev"], ["btn-play", "play"], ["btn-next", "next"], ["btn-devices", "devices"], ["btn-more", "more"]]
  .forEach(([id, name]) => $(id).replaceChildren(icon(name)));
$("btn-addpl").replaceChildren(icon("playlistAdd"), "Add to a playlist");
$("btn-eq").replaceChildren(icon("equalizer"), "Equaliser");
$("btn-np").replaceChildren(icon("expand"), "Now playing");
document.querySelector(".vol-ico").replaceChildren(icon("volume"));
$("side-new").replaceChildren(icon("add"));
$("side-new").addEventListener("click", () => newPlaylist([]));
// "More" in the player bar: add to playlist, sleep timer, equaliser, Now playing
$("btn-more").addEventListener("click", (e) => { e.stopPropagation(); $("more-menu").hidden = !$("more-menu").hidden; });
$("more-menu").addEventListener("click", () => setTimeout(() => { $("more-menu").hidden = true; }));
document.addEventListener("mousedown", (e) => { if (!$("more-menu").contains(e.target) && e.target !== $("btn-more") && !$("btn-more").contains(e.target)) $("more-menu").hidden = true; });
$("btn-eq").addEventListener("click", () => { settingsTab = 0; go("settings"); });
$("btn-np").addEventListener("click", () => openNowPlaying());
$("np-cover").addEventListener("click", () => openNowPlaying());
document.querySelector(".np-text").addEventListener("click", () => openNowPlaying());
// sliders show how far along they are
function fill(el) { el.style.setProperty("--fill", `${(el.value - el.min) / (el.max - el.min) * 100}%`); }
["seek", "volume"].forEach((id) => { $(id).addEventListener("input", () => fill($(id))); fill($(id)); });
const player = { list: [], index: -1, current: null, counted: false, endless: false, fetching: false };
player.vol = 0.8;  // the volume slider; the element's volume also has levelling and fades in it

const remote = { ws: null, you: null, active: null, devices: [], at: 0, retry: 1000, timer: null, picker: null };
// The active device, if it's another one and in use (playing, or paused under 10 minutes ago).
const elsewhere = () => {
  if (!remote.active || remote.active === remote.you) return null;
  const d = remote.devices.find((x) => x.device === remote.active);
  if (!d) return null;
  const idle = (d.idle_s || 0) + (d.state && d.state.playing ? 0 : (Date.now() - remote.at) / 1000);
  return idle < 600 ? d : null;
};

function playList(list, index) {
  const d = elsewhere();
  if (d) {
    remoteSend({ type: "command", to: d.device, command: { action: "load", queue: list.map(songOut), index, position_ms: 0, playing: true } });
    return;
  }
  player.list = list; player.endless = false; player.radio = null; playAt(index);
}

// --- never-ending discovery play (explore.py) ----------------------------------------------------
async function endlessBatch(count) {
  const ids = player.list.map((t) => t.video_id).filter(Boolean);
  const heard = player.list.slice(0, player.index + 1).map((t) => t.video_id).filter(Boolean);
  const seeds = heard.length ? heard.slice(-20) : (player.current && player.current.video_id ? [player.current.video_id] : []);
  const r = player.radio  // radio: more like the last few songs heard (library songs welcome, nothing downloaded)
    ? await api("/api/radio", { method: "POST", body: { seeds: seeds.slice(-5), exclude: ids.slice(-2000), count } })
    : await api("/api/discover/endless", { method: "POST", body: { seeds, exclude: ids.slice(-2000), count } });
  return r.items.map(ytAsTrack);
}
// Song radio / artist radio: plays at once, then keeps going with songs like it.
async function startRadio(source, label, first = null) {
  try {
    toast(`Starting ${label}…`);
    const r = await api("/api/radio", { method: "POST", body: { ...source, count: 25 } });
    const list = [...(first ? [first] : []), ...r.items.map(ytAsTrack)];
    if (!list.length) return toast("Couldn't find songs for this radio right now");
    if (elsewhere()) return playList(list, 0);  // the other device plays this batch (it doesn't top up)
    player.list = list; player.endless = true; player.radio = label;
    playAt(0);
  } catch (e) { toast(e.message, 6000); }
}
async function startEndless() {
  try {
    toast("Finding new songs…");
    const keep = player.current && !elsewhere() ? [player.current] : [];
    player.list = keep; player.index = keep.length - 1;
    const more = await endlessBatch(10);
    if (!more.length) return toast("Couldn't find new songs right now");
    if (elsewhere()) return playList(more, 0);  // the other device plays this batch (it doesn't top up)
    player.list = [...keep, ...more]; player.endless = true; player.radio = null;
    playAt(keep.length);
  } catch (e) { toast(e.message); }
}
async function topUpEndless() {
  if (!player.endless || player.fetching || player.list.length - player.index > 3) return;
  player.fetching = true;
  try { player.list.push(...await endlessBatch(10)); } catch { /* try again at the next song */ }
  player.fetching = false;
}
// Play history: how long the current song was actually heard (seeking doesn't count).
let heard = 0, lastTick = null, startedAt = null;
function reportPlay() {
  const t = player.current;
  if (!t || startedAt === null || heard < 1) return;
  const play = { track_id: t.id || null, video_id: t.video_id || null, title: t.title,
    artist: t.artist || null, album: t.album || null, duration_s: Math.round(audio.duration) || null,
    played_s: Math.round(heard), started_at: startedAt,
    client_id: `pc-${Math.round(startedAt * 1000)}-${Math.random().toString(36).slice(2, 8)}` };
  startedAt = null; heard = 0;
  api("/api/plays", { method: "POST", body: { plays: [play] } }).catch(() => {});
}
window.addEventListener("beforeunload", reportPlay);

// --- volume: slider x levelling (leveller.py) x sleep-timer fade --------------------------------
let fade = 1;
const levelOn = () => { try { return localStorage.getItem("level") !== "off"; } catch { return true; } };
function levelFactor(t) {  // only turns loud songs down (an <audio> can't go above 100%)
  const g = t && typeof t.gain_db === "number" && levelOn() ? t.gain_db : 0;
  return Math.min(1, Math.pow(10, g / 20));
}
function applyVolume() {
  audio.volume = Math.max(0, Math.min(1, player.vol * levelFactor(player.current) * fade));
}
const keyOf = (t) => t && (t.id ? `tr-${t.id}` : t.video_id);

// --- equaliser: presets + bass + treble, on this PC only (Web Audio) ---------------------------
// The audio only goes through Web Audio once the equaliser is used (not Flat), so playback
// for everyone else is exactly as before. Boosts are matched by turning the whole signal
// down, so a boosted song can't distort.
const EQ_BANDS = [60, 230, 910, 3600, 14000];
const EQ_PRESETS = {
  flat: ["Flat", [0, 0, 0, 0, 0]], bass: ["Bass boost", [6, 4, 1, 0, 0]], treble: ["Treble boost", [0, 0, 0, 3, 6]],
  vocal: ["Vocal", [-2, -1, 4, 3, 0]], rock: ["Rock", [4, 2, -2, 2, 4]], pop: ["Pop", [-1, 2, 4, 2, -1]],
  hiphop: ["Hip-hop", [5, 3, 0, 1, 2]], electronic: ["Electronic", [4, 2, 0, 2, 4]], jazz: ["Jazz", [3, 1, -1, 1, 3]],
  classical: ["Classical", [3, 2, -1, 2, 3]], acoustic: ["Acoustic", [2, 1, 1, 2, 2]], late: ["Late night (quieter bass)", [-4, -2, 0, 0, -1]],
};
const eq = { ctx: null, bands: [], bass: null, treble: null, pre: null };
function eqSettings() {
  try { return { preset: "flat", bass: 0, treble: 0, ...JSON.parse(localStorage.getItem("eq") || "{}") }; }
  catch { return { preset: "flat", bass: 0, treble: 0 }; }
}
function saveEq(st) {
  try { localStorage.setItem("eq", JSON.stringify(st)); } catch { /* private mode: this session only */ }
  applyEq(st);
}
function buildEq() {
  const ctx = new AudioContext();
  const node = (type, freq) => { const f = ctx.createBiquadFilter(); f.type = type; f.frequency.value = freq; return f; };
  eq.bass = node("lowshelf", 120);
  eq.bands = EQ_BANDS.map((f) => { const b = node("peaking", f); b.Q.value = 1.0; return b; });
  eq.treble = node("highshelf", 8000);
  eq.pre = ctx.createGain();
  const chain = [eq.pre, eq.bass, ...eq.bands, eq.treble];
  chain.reduce((a, b) => (a.connect(b), b)).connect(ctx.destination);
  audios.forEach((a) => ctx.createMediaElementSource(a).connect(eq.pre));
  eq.ctx = ctx;
}
function applyEq(st = eqSettings()) {
  const gains = (EQ_PRESETS[st.preset] || EQ_PRESETS.flat)[1];
  const flat = gains.every((g) => g === 0) && !st.bass && !st.treble;
  if (!eq.ctx) { if (flat) return; buildEq(); }
  gains.forEach((g, i) => { eq.bands[i].gain.value = g; });
  eq.bass.gain.value = st.bass; eq.treble.gain.value = st.treble;
  const peak = Math.max(0, ...gains.map((g, i) => g + (i < 2 ? st.bass : 0) + (i > 2 ? st.treble : 0)));
  eq.pre.gain.value = Math.pow(10, -peak / 20);
  if (eq.ctx.state === "suspended") eq.ctx.resume().catch(() => {});
}
applyEq();
// Near the end of a song: load the next one in the spare element.
function preloadNext() {
  if (elsewhere() || !player.current || !audio.duration || audio.duration - audio.currentTime > 25) return;
  const n = nextPlayable(player.index);
  const t = player.list[n];
  const spare = audios.find((a) => a !== audio);
  if (!t || spare.dataset.key === keyOf(t)) return;
  spare.dataset.key = keyOf(t);
  spare.src = media(t.stream_url);
  spare.load();
}

function playAt(i) {
  if (i >= 0 && i < player.list.length && banned(player.list[i])) {  // banned: never plays, wherever it is
    toast(`Skipped “${player.list[i].title}”: it's banned (Settings > Ratings)`);
    i = nextPlayable(i);
  }
  if (i < 0 || i >= player.list.length) return;
  reportPlay();
  const t = player.list[i];
  player.index = i; player.current = t; player.counted = false;
  heard = 0; lastTick = null; startedAt = Date.now() / 1000;
  const spare = audios.find((a) => a !== audio);
  if (spare.dataset.key && spare.dataset.key === keyOf(t)) {  // already loaded: switch, no gap
    const old = audio;
    audio = spare;
    old.pause(); old.removeAttribute("src"); old.load(); delete old.dataset.key;
  } else {
    audio.src = media(t.stream_url);
    if (spare.dataset.key) { spare.removeAttribute("src"); spare.load(); delete spare.dataset.key; }
  }
  delete audio.dataset.key;
  applyVolume();
  // AbortError = another song was started before this one began (e.g. a double click, or
  // Next pressed quickly): the newer one plays, so it's not an error worth showing.
  audio.play().catch((e) => { if (e.name !== "AbortError") toast(e.name === "NotSupportedError" ? "Can't play this song: the PC couldn't send it. Try again in a moment." : `Can't play this song: ${e.message}`); });
  if (t.jamId) reportJamPlaying(i); else player.jamHost = false;  // something else started: not the Jam any more
  paintBar();
  topUpEndless();
}

// --- the player bar: what's playing on the active device ---------------------------------------
let seeking = false;
function showSong(song) {  // song: {title, artist, album, cover (our cover url), thumb (YouTube picture)}
  $("np-title").textContent = song ? song.title : "Nothing playing";
  $("np-artist").textContent = song ? [song.artist, song.album].filter(Boolean).join(" · ") : "";
  const cover = $("np-cover");
  cover.hidden = !song || (!song.cover && !song.thumb);
  if (song && song.cover) cover.src = media(song.cover, 112);
  else if (song && song.thumb) cover.src = song.thumb;
}
function showTime(posS, durS, playing) {
  const want = playing ? "pause" : "play";
  if ($("btn-play").dataset.icon !== want) { $("btn-play").replaceChildren(icon(want)); $("btn-play").dataset.icon = want; }
  $("btn-play").title = playing ? "Pause" : "Play";
  $("t-cur").textContent = dur(posS) || "0:00";
  $("t-dur").textContent = dur(durS) || "0:00";
  if (!seeking) $("seek").value = durS ? Math.round((posS / durS) * 1000) : 0;
  fill($("seek"));
  document.body.classList.toggle("paused", !playing);
}
function paintBar() {
  const d = elsewhere();
  const strip = $("connect-strip");
  strip.hidden = !d;
  $("btn-devices").classList.toggle("on", !!d);
  if (d) {
    strip.textContent = `${d.kind === "pc" ? "💻" : d.kind === "tv" ? "📺" : "📱"} Playing on ${d.name}`;
    const st = d.state || {};
    const s = st.queue && st.index >= 0 ? st.queue[st.index] : null;
    showSong(s && { title: s.title, artist: s.artist, album: s.album,
      cover: s.track_id ? `/api/library/tracks/${s.track_id}/cover` : null, thumb: s.track_id ? null : s.thumbnail });
    showTime(nowPos(st) / 1000, (st.duration_ms || 0) / 1000, !!st.playing);
    if (document.activeElement !== $("volume")) $("volume").value = Math.round((st.volume ?? 1) * 100);
    document.querySelectorAll("tr[data-track]").forEach((r) => r.classList.toggle("playing", !!s && Number(r.dataset.track) === s.track_id));
    paintThumbs(); renderUpnext();
    return;
  }
  const t = player.current;
  showSong(t && { title: t.title, artist: t.artist, album: t.album, cover: t.cover_url, thumb: t.thumb });
  showTime(audio.currentTime, audio.duration || 0, !!t && !audio.paused);
  if (document.activeElement !== $("volume")) { $("volume").value = Math.round(player.vol * 100); fill($("volume")); }
  paintNowPlaying();
  document.querySelectorAll("tr[data-track]").forEach((r) => r.classList.toggle("playing", !!t && Number(r.dataset.track) === t.id));
  paintThumbs(); renderUpnext();
}
setInterval(() => { if (elsewhere()) paintBar(); }, 500);

const control = (command) => {
  const d = elsewhere();
  if (d) { remoteSend({ type: "command", to: d.device, command }); return true; }
  return false;
};
$("btn-play").addEventListener("click", () => {
  const d = elsewhere();
  if (d) return control({ action: d.state && d.state.playing ? "pause" : "play" });
  if (!player.current) return;
  audio.paused ? audio.play() : audio.pause();
});
$("btn-next").addEventListener("click", () => control({ action: "next" }) || playAt(nextPlayable(player.index)));
$("btn-prev").addEventListener("click", () => control({ action: "previous" })
  || (audio.currentTime > 3 ? (audio.currentTime = 0) : playAt(player.index - 1)));
$("btn-addpl").addEventListener("click", () => {
  const d = elsewhere();
  const st = d && d.state;
  const s = st && st.queue && st.index >= 0 ? st.queue[st.index] : null;
  const t = d ? (s && { video_id: s.video_id, title: s.title, artist: s.artist, album: s.album }) : player.current;
  if (!t || !t.video_id) return toast(t ? "Only songs from YouTube Music can go in a playlist." : "Nothing playing");
  addToPlaylist([{ type: "song", id: t.video_id, title: t.title, artists: t.artist ? [t.artist] : [], album: t.album || null }]);
});
onAudio("play", () => { if (eq.ctx && eq.ctx.state === "suspended") eq.ctx.resume().catch(() => {}); if (!elsewhere()) paintBar(); });
onAudio("pause", () => { if (!elsewhere()) paintBar(); });
onAudio("ended", () => {
  reportPlay();
  if (sleepAtSongEnd()) return;
  playAt(nextPlayable(player.index));
});
onAudio("timeupdate", () => {
  preloadNext();
  const now = audio.currentTime;
  if (lastTick !== null && !audio.paused && now > lastTick && now - lastTick < 2) heard += now - lastTick;
  lastTick = now;
  if (!elsewhere()) showTime(now, audio.duration || 0, !audio.paused);
});
$("seek").addEventListener("input", () => (seeking = true));
$("seek").addEventListener("change", (e) => {
  seeking = false;
  const d = elsewhere();
  if (d) {
    const st = d.state || {};
    if (st.duration_ms) control({ action: "seek", position_ms: Math.round((e.target.value / 1000) * st.duration_ms) });
  } else if (audio.duration) audio.currentTime = (e.target.value / 1000) * audio.duration;
});
$("volume").addEventListener("input", (e) => {
  const v = e.target.value / 100;
  if (elsewhere()) { clearTimeout(remote.vol); remote.vol = setTimeout(() => control({ action: "volume", value: v }), 150); }
  else { player.vol = v; applyVolume(); }
});
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    e.preventDefault(); $("btn-play").click();
  }
});

// --- the connection to the other devices (dielify/remote.py) -----------------------------------
function songOut(t) {
  return { track_id: t.id || undefined, video_id: t.video_id || undefined, title: t.title,
    artist: t.artist || undefined, album: t.album || undefined, thumbnail: t.thumb || undefined,
    gain_db: typeof t.gain_db === "number" ? t.gain_db : undefined };
}
function remoteTrack(s) {
  const lib = s.track_id;
  return { id: lib || null, video_id: s.video_id || null, title: s.title || "", artist: s.artist || "", album: s.album || "",
    stream_url: lib ? `/api/library/tracks/${lib}/stream` : `/api/yt/stream/${encodeURIComponent(s.video_id)}`,
    cover_url: lib ? `/api/library/tracks/${lib}/cover` : null, thumb: lib ? null : (s.thumbnail || null),
    gain_db: typeof s.gain_db === "number" ? s.gain_db : null };
}
function myState() {
  const on = !!player.current;
  return { playing: on && !audio.paused, position_ms: Math.round(audio.currentTime * 1000),
    duration_ms: Math.round((audio.duration || 0) * 1000) || null, volume: player.vol,
    index: on ? player.index : -1, queue: on ? player.list.map(songOut) : [] };
}
function remoteSend(msg) {
  if (remote.ws && remote.ws.readyState === WebSocket.OPEN) remote.ws.send(JSON.stringify(msg));
}
function sendState(now) {
  clearTimeout(remote.timer);
  remote.timer = setTimeout(() => remoteSend({ type: "state", state: myState() }), now === true ? 0 : 150);
}
["play", "pause", "seeked", "volumechange", "loadedmetadata", "ended"].forEach((e) => onAudio(e, sendState));
setInterval(() => sendState(true), 10000);

function remoteConnect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/remote?token=${encodeURIComponent(KEY)}`);
  remote.ws = ws;
  ws.onopen = () => {
    remote.retry = 1000;
    ws.send(JSON.stringify({ type: "hello", device: "pc-desktop", kind: "pc", state: myState() }));
  };
  ws.onmessage = (e) => {
    let m;
    try { m = JSON.parse(e.data); } catch { return; }
    if (m.type === "devices") {
      remote.you = m.you; remote.active = m.active; remote.devices = m.devices; remote.at = Date.now();
      paintBar(); renderPicker();
    } else if (m.type === "command") runCommand(m.command, m.from);
    else if (m.type === "error") toast(m.message);
  };
  ws.onclose = () => {
    if (remote.ws !== ws) return;
    remote.ws = null; remote.devices = []; remote.active = null;
    paintBar(); renderPicker();
    setTimeout(remoteConnect, remote.retry);
    remote.retry = Math.min(remote.retry * 2, 30000);
  };
}

function runCommand(c, from) {
  switch (c.action) {
    case "play": if (player.current) audio.play().catch(() => {}); break;
    case "pause": audio.pause(); break;
    case "next": playAt(nextPlayable(player.index)); break;
    case "previous": if (audio.currentTime > 3) audio.currentTime = 0; else playAt(player.index - 1); break;
    case "seek": audio.currentTime = c.position_ms / 1000; break;
    case "volume": player.vol = c.value; applyVolume(); sendState(true); break;
    case "queue": {  // Up next edited on another device: new list around the song playing here
      if (!player.current || !c.queue[c.index]) break;
      const list = c.queue.map(remoteTrack);
      list[c.index] = player.current;
      player.list = list; player.index = c.index;
      sendState(true); upnext.sig = ""; renderUpnext();
      break;
    }
    case "jump": case "load": {
      if (c.action === "load") player.list = c.queue.map(remoteTrack);
      playAt(c.index);
      const pos = c.position_ms / 1000;
      audio.addEventListener("loadedmetadata", () => {
        if (pos > 1) audio.currentTime = pos;
        if (c.playing === false) audio.pause();
      }, { once: true });
      break;
    }
  }
}

const nowPos = (st) => Math.min(st.position_ms + (st.playing ? Date.now() - remote.at : 0), st.duration_ms || Infinity);

// The device list: a small pop-up above the device button. Picking one moves the music there.
function renderPicker() {
  const box = remote.picker;
  if (!box) return;
  const mine = remote.devices.find((d) => d.device === remote.you);
  const rows = [...(mine ? [mine] : []), ...remote.devices.filter((d) => d.device !== remote.you)];
  box.replaceChildren(...[h("div", { class: "picker-title" }, "Play on"),
    !remote.ws ? h("p", { class: "muted small" }, "Connecting…") : rows.map((d) => {
      const st = d.state || {};
      const s = st.queue && st.index >= 0 ? st.queue[st.index] : null;
      const on = d.device === remote.active || (!remote.active && d.device === remote.you);
      return h("button", { class: `picker-row${on ? " on" : ""}`, onclick: () => {
        closePicker();
        if (!on) remoteSend({ type: "select", device: d.device });
      } },
      h("span", { class: "picker-icon" }, d.kind === "pc" ? "💻" : d.kind === "tv" ? "📺" : "📱"),
      h("span", {}, h("div", {}, d.device === remote.you ? `This computer (${d.name})` : d.name),
        h("div", { class: "muted small" }, on ? (st.playing ? "Playing" : "Selected") : s ? `Paused: ${s.title}` : "")),
      on ? h("span", { class: "picker-tick" }, "✓") : null);
    }),
    remote.ws && rows.length < 2 ? h("p", { class: "muted small" }, "Your phone shows up here while Dielify is open or playing on it.") : null]
    .flat().filter(Boolean));
}
function closePicker() {
  if (remote.picker) { remote.picker.remove(); remote.picker = null; }
  document.removeEventListener("mousedown", pickerOutside, true);
}
function pickerOutside(e) {
  if (remote.picker && !remote.picker.contains(e.target) && e.target !== $("btn-devices")) closePicker();
}
$("btn-devices").addEventListener("click", () => {
  if (remote.picker) return closePicker();
  closeUpnext();
  remote.picker = h("div", { class: "picker" });
  document.body.append(remote.picker);
  renderPicker();
  document.addEventListener("mousedown", pickerOutside, true);
});

// --- ratings: thumbs up / down, hold thumbs down to ban (dielify/ratings.py) ----------------
const rated = { songs: new Map(), artists: new Map(), list: [] };
const UP = 1, DOWN = -1, BAN = -2;
// Same rules as ratings.py: artist_key and split_artists.
const artistKey = (name) => (name || "").normalize("NFKC").toLowerCase().replace(/&/g, "and").replace(/\s+/g, " ").trim();
const splitArtists = (text) => (text || "").split(/,|;| & | x | feat\.? | ft\.? | featuring | with /i).map((s) => s.trim()).filter(Boolean);
function loadRatings(list) {
  rated.list = list; rated.songs.clear(); rated.artists.clear();
  for (const r of list) (r.kind === "song" ? rated.songs : rated.artists).set(r.key, r.value);
}
async function refreshRatings() {
  try { loadRatings((await api("/api/ratings")).ratings); } catch { /* offline from the server: keep what we had */ }
  paintThumbs();
  refreshTaste();
}

// --- leave out of my taste (dielify/taste.py) -------------------------------------------------
const taste = { list: [], keys: new Set() };
const tasteKey = (kind, key) => `${kind}:${key}`;
function loadTaste(items) {
  taste.list = items;
  taste.keys = new Set(items.map((t) => tasteKey(t.kind, t.key)));
}
async function refreshTaste() {
  try { loadTaste((await api("/api/taste")).items); } catch { /* keep what we had */ }
}
const songTasteKey = (t) => t.video_id || (t.id ? `tr-${t.id}` : null);
const isLeftOut = (kind, key) => key != null && taste.keys.has(tasteKey(kind, String(key)));
async function setTaste(kind, key, name, out) {
  try {
    loadTaste((await api("/api/taste", { method: "PUT", body: { kind, key: String(key), name, out } })).items);
    toast(out ? `“${name}” won't shape your recommendations` : `“${name}” counts in your taste again`);
  } catch (e) { toast(e.message, 6000); }
}
// song: { video_id, id (library track id), artist }
function ratingOf(song) {
  if (!song) return 0;
  const s = rated.songs.get(song.video_id || (song.id ? `tr-${song.id}` : "")) || 0;
  const a = splitArtists(song.artist).map((n) => rated.artists.get(artistKey(n)) || 0);
  if (s === BAN || a.includes(BAN)) return BAN;
  if (s) return s;
  return a.includes(DOWN) ? DOWN : Math.max(0, ...a);
}
const banned = (song) => ratingOf(song) === BAN;
async function rate(kind, body, value, msg) {
  try {
    const res = await api("/api/ratings", { method: "PUT", body: { kind, value, ...body } });
    loadRatings(res.ratings);
    if (res.removed) {
      toast(`Thumbs down: “${res.removed}” is gone from your PC`);
      if (player.endless && !elsewhere() && player.current && player.current.video_id === body.video_id) skipNow();
    } else if (msg) toast(msg);
  } catch (e) { toast(e.message); }
  paintThumbs();
}
const songBody = (s) => ({ name: [s.title, s.artist].filter(Boolean).join(" - "), video_id: s.video_id || null, track_id: s.id || null });

// What's playing now, here or on the active device.
function nowSong() {
  const d = elsewhere();
  if (d) {
    const st = d.state || {};
    const s = st.queue && st.index >= 0 ? st.queue[st.index] : null;
    return s && { video_id: s.video_id || null, id: s.track_id || null, title: s.title, artist: s.artist || "" };
  }
  const t = player.current;
  return t && { video_id: t.video_id || null, id: t.id || null, title: t.title, artist: t.artist || "" };
}
function paintThumbs() {
  const s = nowSong();
  const own = s ? (rated.songs.get(s.video_id || (s.id ? `tr-${s.id}` : "")) || 0) : 0;
  $("btn-up").classList.toggle("on", own === UP);
  $("btn-down").classList.toggle("on", own === DOWN);
  $("btn-up").disabled = $("btn-down").disabled = !s;
}
function skipNow() {
  if (!control({ action: "next" })) playAt(nextPlayable(player.index));
}
// The next song in the list that isn't banned (or past the end).
function nextPlayable(from) {
  let i = from + 1;
  while (i < player.list.length && banned(player.list[i])) i++;
  return i;
}

$("btn-up").replaceChildren(icon("thumbUp"));
$("btn-down").replaceChildren(icon("thumbDown"));
$("btn-up").addEventListener("click", () => {
  const s = nowSong();
  if (s) rate("song", songBody(s), $("btn-up").classList.contains("on") ? 0 : UP);
});
// Thumbs down: a click rates the song; holding it for 0.7 s offers a ban.
let holdTimer = null, held = false;
$("btn-down").addEventListener("pointerdown", () => {
  held = false;
  holdTimer = setTimeout(() => { held = true; banChooser(); }, 700);
});
["pointerup", "pointerleave"].forEach((e) => $("btn-down").addEventListener(e, () => clearTimeout(holdTimer)));
$("btn-down").addEventListener("click", () => {
  if (held) return;
  const s = nowSong();
  if (s) rate("song", songBody(s), $("btn-down").classList.contains("on") ? 0 : DOWN);
});
function banChooser() {
  const s = nowSong();
  if (!s) return;
  const close = () => box.remove();
  const artists = splitArtists(s.artist);
  const box = h("div", { class: "modal", onclick: (e) => { if (e.target === box) close(); } },
    h("div", { class: "panel" }, h("h2", {}, "Never play again?"),
      h("div", { class: "pick" },
        h("button", { class: "pick-row", onclick: async () => { close(); await rate("song", songBody(s), BAN, `Banned “${s.title}”`); skipNow(); } },
          h("div", {}, `This song: ${s.title}`), h("div", { class: "muted small" }, "Skipped in every list, left out of discovery and mixes")),
        artists.map((a) => h("button", { class: "pick-row", onclick: async () => { close(); await rate("artist", { name: a }, BAN, `Banned ${a}`); skipNow(); } },
          h("div", {}, `The artist: ${a}`), h("div", { class: "muted small" }, "All their songs, everywhere")))),
      h("p", { class: "muted small" }, "Undo in Settings > Ratings."),
      h("div", { class: "row", style: "margin-top:10px" }, h("button", { onclick: close }, "Cancel"))));
  document.body.append(box);
}
// Thumbs on an artist's page (hold thumbs down to ban the artist).
function artistThumbs(name) {
  const key = artistKey(name);
  const box = h("span", { class: "thumbs" });
  const paint = () => {
    const v = rated.artists.get(key) || 0;
    box.replaceChildren(
      ib("thumbUp", v === UP ? "You like this artist (click to undo)" : "Like this artist",
        async () => { await rate("artist", { name }, v === UP ? 0 : UP); paint(); }, { class: `ib${v === UP ? " on" : ""}` }),
      ib("thumbDown", v === DOWN ? "Less of this artist (click to undo)" : "Less of this artist (hold to ban)",
        async () => { if (!heldA) { await rate("artist", { name }, v === DOWN ? 0 : DOWN); paint(); } }, { class: `ib${v === DOWN ? " on" : ""}` }),
      v === BAN ? h("span", { class: "muted small" }, " Banned · ",
        h("button", { class: "link", onclick: async () => { await rate("artist", { name }, 0, `Unbanned ${name}`); paint(); } }, "unban")) : "");
    const down = box.children[1];
    let t = null, heldA = false;
    down.addEventListener("pointerdown", () => { heldA = false; t = setTimeout(async () => { heldA = true; await rate("artist", { name }, BAN, `Banned ${name}`); paint(); }, 700); });
    ["pointerup", "pointerleave"].forEach((e) => down.addEventListener(e, () => clearTimeout(t)));
  };
  paint();
  return box;
}
function playbackPanel() {
  const box = h("input", { type: "checkbox", id: "level-on" });
  box.checked = levelOn();
  box.addEventListener("change", () => {
    try { localStorage.setItem("level", box.checked ? "on" : "off"); } catch { /* private mode: this session only */ }
    applyVolume();
  });
  const st = eqSettings();
  const preset = select(Object.entries(EQ_PRESETS).map(([k, [l]]) => [k, l]), st.preset);
  const slider = (key) => {
    const out = h("span", { class: "muted small", style: "width:52px" }, `${st[key] > 0 ? "+" : ""}${st[key]} dB`);
    const r = h("input", { type: "range", min: "-12", max: "12", step: "1", value: String(st[key]), style: "flex:1" });
    r.addEventListener("input", () => {
      const now = { ...eqSettings(), [key]: Number(r.value) };
      out.textContent = `${now[key] > 0 ? "+" : ""}${now[key]} dB`;
      saveEq(now);
    });
    return [r, out];
  };
  preset.addEventListener("change", () => saveEq({ ...eqSettings(), preset: preset.value }));
  const reset = h("button", { class: "link", onclick: () => { saveEq({ preset: "flat", bass: 0, treble: 0 }); viewSettings(); } }, "Reset");
  return h("div", { class: "panel" }, h("h2", {}, "Playback on this PC"),
    h("label", { class: "row", style: "gap:8px" }, box, "Even out volume"),
    h("p", { class: "muted small" }, "Loud songs are turned down to match the rest, so the volume doesn't jump between songs. "
      + "Each song is measured once, in the background."),
    h("h3", {}, "Equaliser"),
    h("div", { class: "row", style: "gap:8px" }, "Sound ", preset, reset),
    h("div", { class: "row", style: "gap:8px;margin-top:6px" }, h("span", { style: "width:60px" }, "Bass"), ...slider("bass")),
    h("div", { class: "row", style: "gap:8px" }, h("span", { style: "width:60px" }, "Treble"), ...slider("treble")),
    h("p", { class: "muted small" }, "On this PC only. Changes are heard straight away."));
}
function tastePanel() {
  return h("div", { class: "panel" }, h("h2", {}, "Left out of your taste"),
    h("p", { class: "muted small" }, "These still play, but don't shape For you, mixes, the time-of-day mix or new releases. "
      + "Leave a song out from its queue menu, a playlist from its page."),
    taste.list.length ? taste.list.map((t) => h("div", { class: "setting" },
      h("div", { class: "label" }, t.kind === "playlist" ? "Playlist" : "Song"), h("div", { class: "value" }, t.name),
      h("button", { onclick: async () => { await setTaste(t.kind, t.key, t.name, false); viewSettings(); } }, "Count again")))
      : h("p", { class: "muted small" }, "Nothing left out."));
}
async function newReleasesPanel() {
  let r, follows;
  try { [r, follows] = await Promise.all([api("/api/discover/new"), api("/api/follows")]); } catch { return null; }
  const box = h("input", { type: "checkbox" });
  box.checked = r.auto_download;
  box.addEventListener("change", async () => {
    try { await api("/api/discover/new/settings", { method: "PUT", body: { auto_download: box.checked } }); }
    catch (e) { box.checked = !box.checked; toast(e.message, 6000); }
  });
  return h("div", { class: "panel" }, h("h2", {}, "New releases"),
    h("p", { class: "muted small" }, `Dielify checks ${r.watching} artist${r.watching === 1 ? "" : "s"} once a day: the ones you follow and your 20 most played. `
      + "What's new shows in Discover > New for you."),
    h("label", { class: "row", style: "gap:8px" }, box, "Download new albums automatically"),
    h("p", { class: "muted small" }, "Only albums that come out from now on, never an artist's older music."),
    h("h3", {}, "Following"),
    follows.follows.length ? follows.follows.map((f) => h("div", { class: "setting" }, h("div", { class: "value" }, f.name),
      h("button", { onclick: async () => { await api("/api/follows", { method: "PUT", body: { name: f.name, follow: false } }); viewSettings(); } }, "Unfollow")))
      : h("p", { class: "muted small" }, "Nobody yet. Follow an artist from their page."));
}
function ratingsPanel() {
  const bans = rated.list.filter((r) => r.value === BAN);
  const ups = rated.list.filter((r) => r.value === UP).length, downs = rated.list.filter((r) => r.value === DOWN).length;
  return h("div", { class: "panel" }, h("h2", {}, "Ratings"),
    h("p", { class: "muted small" }, `${ups} thumbs up · ${downs} thumbs down. Thumbs up: mixes play it more. `
      + "Thumbs down: it goes to the back of discovery. Banned: never played, never suggested."),
    bans.length ? bans.map((r) => h("div", { class: "setting" }, h("div", { class: "label" }, r.kind === "artist" ? "Artist" : "Song"),
      h("div", { class: "value" }, r.name),
      h("button", { onclick: async () => { await rate(r.kind, r.kind === "artist" ? { name: r.name } : { name: r.name, video_id: r.key.startsWith("tr-") ? null : r.key, track_id: r.key.startsWith("tr-") ? Number(r.key.slice(3)) : null }, 0, `Unbanned ${r.name}`); viewSettings(); } }, "Unban")))
      : h("p", { class: "muted small" }, "Nothing banned. Hold thumbs down (player bar, or an artist's page) to ban."));
}

// --- Up next: the songs coming up (here, or on the active device) ------------------------------
// The list being played and where we are in it: { list (player tracks), index, d (other device or null) }.
function queueNow() {
  const d = elsewhere();
  if (d) {
    const st = d.state || {};
    return { list: (st.queue || []).map(remoteTrack), index: st.index ?? -1, d };
  }
  return { list: player.list, index: player.current ? player.index : -1, d: null };
}
// Change the list around the song playing now (it keeps playing). index = its place in `list`.
function setQueue(list, index) {
  const d = elsewhere();
  if (d) remoteSend({ type: "command", to: d.device, command: { action: "queue", queue: list.map(songOut), index } });
  else { player.list = list; player.index = index; sendState(true); }
  upnext.sig = ""; renderUpnext();
}
function jumpTo(i) {
  if (!control({ action: "jump", index: i, position_ms: 0 })) playAt(i);
}
// Play next / Add to queue. Nothing playing: just plays them.
function addToQueue(tracks, next) {
  if (!tracks.length) return;
  const q = queueNow();
  if (q.index < 0 || !q.list.length) { playList(tracks, 0); return; }
  const at = next ? q.index + 1 : q.list.length;
  setQueue([...q.list.slice(0, at), ...tracks, ...q.list.slice(at)], q.index);
  const what = tracks.length === 1 ? `“${tracks[0].title}”` : `${tracks.length} songs`;
  toast(next ? `${what} will play next` : `Added ${what} to the queue`);
}
// The small "Play next / Add to queue" menu for a song row's queue button.
function queueMenu(btn, tracks) {
  closeMenu();
  const r = btn.getBoundingClientRect();
  const m = h("div", { class: "menu", style: `right:${Math.max(8, innerWidth - r.right)}px;top:${r.bottom + 4}px` },
    h("button", { onclick: () => { closeMenu(); addToQueue(tracks, true); } }, icon("playNext", "ico lead"), "Play next"),
    h("button", { onclick: () => { closeMenu(); addToQueue(tracks, false); } }, icon("queueAdd", "ico lead"), "Add to queue"),
    tracks.length === 1 && tracks[0].video_id
      ? h("button", { onclick: () => { closeMenu(); startRadio({ video_id: tracks[0].video_id }, `Radio: ${tracks[0].title}`, tracks[0]); } },
        icon("radio", "ico lead"), "Start radio") : null,
    jamState.jam ? h("button", { onclick: () => { closeMenu(); addToJam(tracks); } }, icon("queueAdd", "ico lead"),
      `Add to ${jamState.jam.you_host ? "your" : jamState.jam.host + "'s"} Jam`) : null,
    tracks.length === 1 && songTasteKey(tracks[0]) ? tasteMenuItem(tracks[0]) : null);
  document.body.append(m);
  if (r.bottom + 4 + m.offsetHeight > innerHeight - 90) m.style.top = `${r.top - m.offsetHeight - 4}px`;
  menuOpen = m;
  setTimeout(() => document.addEventListener("mousedown", menuOutside, true));
}
function tasteMenuItem(t) {
  const key = songTasteKey(t), out = isLeftOut("song", key);
  return h("button", { title: "It still plays; it just doesn't shape For you, mixes and new releases",
    onclick: () => { closeMenu(); setTaste("song", key, `${t.title}${t.artist ? " - " + t.artist : ""}`, !out); } },
    icon("noTaste", "ico lead"), out ? "Count in my taste again" : "Leave out of my taste");
}
let menuOpen = null;
function closeMenu() {
  if (menuOpen) { menuOpen.remove(); menuOpen = null; }
  document.removeEventListener("mousedown", menuOutside, true);
}
function menuOutside(e) { if (menuOpen && !menuOpen.contains(e.target)) closeMenu(); }
const queueBtn = (tracks) => ib("queueAdd", "Play next / add to queue", (e) => queueMenu(e.currentTarget, tracks()));

const upnext = { box: null, sig: "", drag: -1 };
function renderUpnext() {
  const box = upnext.box;
  if (!box) return;
  const q = queueNow();
  const sig = `${q.d ? q.d.device : ""}|${q.index}|${q.list.map((t) => t.video_id || t.id).join(",")}`;
  if (sig === upnext.sig) return;
  upnext.sig = sig;
  const cur = q.index >= 0 ? q.list[q.index] : null;
  const coming = q.list.map((t, i) => [t, i]).slice(q.index + 1);
  const row = (t, i, isNow) => {
    const el = h("div", { class: `uq-row${isNow ? " now" : ""}${banned(t) ? " banned" : ""}`, draggable: !isNow,
      title: isNow ? "" : "Click to play. Drag to move." },
      isNow ? h("span", { class: "uq-grip" }, icon("play")) : h("span", { class: "uq-grip" }, icon("drag")),
      h("div", { class: "uq-t", onclick: isNow ? null : () => jumpTo(i) },
        h("div", { class: "t" }, t.title), h("div", { class: "muted small" }, t.artist || "")),
      isNow ? null : ib("playNext", "Play next", () => {
        const l = q.list.slice(); const [s] = l.splice(i, 1); l.splice(q.index + 1, 0, s); setQueue(l, q.index);
      }),
      isNow ? null : ib("close", "Remove from the queue", () => {
        const l = q.list.slice(); l.splice(i, 1); setQueue(l, q.index);
      }));
    if (!isNow) {
      el.addEventListener("dragstart", (e) => { upnext.drag = i; e.dataTransfer.effectAllowed = "move"; el.classList.add("dragging"); });
      el.addEventListener("dragend", () => { upnext.drag = -1; el.classList.remove("dragging"); });
      el.addEventListener("dragover", (e) => { if (upnext.drag >= 0) { e.preventDefault(); el.classList.add("over"); } });
      el.addEventListener("dragleave", () => el.classList.remove("over"));
      el.addEventListener("drop", (e) => {
        e.preventDefault(); el.classList.remove("over");
        const from = upnext.drag;
        if (from < 0 || from === i) return;
        const l = q.list.slice(); const [s] = l.splice(from, 1); l.splice(i, 0, s);  // lands where it was dropped
        setQueue(l, q.index);
      });
    }
    return el;
  };
  box.replaceChildren(...[
    h("div", { class: "uq-head" }, h("b", {}, "Up next"),
      q.d ? h("span", { class: "muted small" }, ` on ${q.d.name}`) : null,
      h("span", { style: "flex:1" }),
      coming.length ? h("button", { class: "link", onclick: () => setQueue(q.list.slice(0, q.index + 1), q.index) }, "Clear") : null,
      ib("close", "Close", closeUpnext)),
    cur ? [h("div", { class: "uq-label" }, "Now playing"), row(cur, q.index, true)] : h("p", { class: "muted small" }, "Nothing playing."),
    coming.length ? [h("div", { class: "uq-label" }, `Next · ${coming.length} song${coming.length === 1 ? "" : "s"}`),
      h("div", { class: "uq-list" }, coming.map(([t, i]) => row(t, i, false)))]
      : cur ? h("p", { class: "muted small" }, player.endless && !q.d ? (player.radio ? `${player.radio}: finding more…` : "Finding more new songs…")
        : "Nothing after this song. Use the queue button on any song to add it.") : null,
  ].flat().filter(Boolean));
}
function closeUpnext() {
  if (upnext.box) { upnext.box.remove(); upnext.box = null; }
  $("btn-queue").classList.remove("on");
}
$("btn-queue").replaceChildren(icon("queueMusic"));
$("btn-queue").addEventListener("click", () => {
  if (upnext.box) return closeUpnext();
  closePicker();
  upnext.box = h("div", { class: "upnext" }); upnext.sig = "";
  document.body.append(upnext.box);
  $("btn-queue").classList.add("on");
  renderUpnext();
});

// --- Now playing: the whole window, in the song's colours, with what plays next ---------------------
var np = { box: null, key: "" };  // var: the player bar may paint before this line runs
function nowShown() {
  const d = elsewhere();
  if (d) {
    const st = d.state || {};
    const x = st.queue && st.index >= 0 ? st.queue[st.index] : null;
    return x && { title: x.title, artist: x.artist, album: x.album, cover: x.track_id ? `/api/library/tracks/${x.track_id}/cover` : null,
      thumb: x.track_id ? null : x.thumbnail, colors: null, key: `${x.track_id || x.video_id}` };
  }
  const t = player.current;
  return t && { title: t.title, artist: t.artist, album: t.album, cover: t.cover_url, thumb: t.thumb, colors: t.colors || null, key: keyOf(t) };
}
function openNowPlaying() {
  if (np.box) return;
  np.box = h("div", { class: "nowplaying" });
  document.body.append(np.box);
  np.key = ""; np.sig = "";
  paintNowPlaying();
  np.timer = setInterval(paintNowPlaying, 1000);
}
function closeNowPlaying() {
  if (!np.box) return;
  clearInterval(np.timer);
  np.box.remove(); np.box = null;
}
function paintNowPlaying() {
  if (!np.box) return;
  const s = nowShown();
  const key = s ? s.key : "-";
  if (key === np.key) return paintNpNext();
  np.key = key;
  np.box.setAttribute("style", tintStyle(s && s.colors));
  const right = np.box.querySelector(".np-right") || h("div", { class: "np-right" });
  np.box.replaceChildren(
    h("button", { class: "np-close", onclick: closeNowPlaying }, icon("collapse", "ico lead"), "Close"),
    h("div", { class: "np-left" },
      s ? h("img", { class: "np-art", alt: "", src: s.cover ? media(s.cover, 1000) : s.thumb || "" }) : h("div", { class: "np-art" }),
      h("div", { class: "np-name" }, s ? s.title : "Nothing playing"),
      h("div", { class: "np-by" }, s ? [s.artist, s.album].filter(Boolean).join(" · ") : "")),
    right);
  np.sig = "";
  paintNpNext();
}
// The right half of Now playing: the next songs (click one to play it).
function paintNpNext() {
  const right = np.box && np.box.querySelector(".np-right");
  if (!right) return;
  const q = queueNow();
  const coming = q.list.map((t, i) => [t, i]).slice(q.index + 1, q.index + 13);
  const sig = `${q.index}|${coming.map(([t]) => t.video_id || t.id).join(",")}`;
  if (sig === np.sig) return;
  np.sig = sig;
  right.replaceChildren(h("div", { class: "np-next" },
    h("div", { class: "np-next-label" }, "Up next"),
    coming.length ? coming.map(([t, i]) => h("button", { class: "np-next-row", onclick: () => jumpTo(i) },
      h("b", {}, t.title), h("span", {}, t.artist || "")))
      : h("p", { class: "muted" }, "Nothing after this song.")));
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeNowPlaying(); });
// --- sleep timer: pause after N minutes (fading out over the last 15 s) or at the end of the song --
const sleep = { at: 0, songEnd: false, songKey: null, timer: null };
const FADE_S = 15;
function nowKey() {
  const d = elsewhere();
  if (d) { const st = d.state || {}; const s = st.queue && st.index >= 0 ? st.queue[st.index] : null; return s ? `${d.device}|${st.index}|${s.track_id || s.video_id}` : null; }
  return player.current ? `here|${player.index}|${keyOf(player.current)}` : null;
}
function stopForSleep() {
  if (!control({ action: "pause" })) audio.pause();
  clearSleep();
  toast("Sleep timer: paused. Good night 🌙");
}
function clearSleep() {
  sleep.at = 0; sleep.songEnd = false; sleep.songKey = null;
  clearInterval(sleep.timer); sleep.timer = null;
  if (fade !== 1) { fade = 1; applyVolume(); }
  paintSleep();
}
// The "ended" event: true = the timer stopped the music here instead of the next song.
function sleepAtSongEnd() {
  if (!sleep.songEnd || elsewhere()) return false;
  clearSleep();
  toast("Sleep timer: stopped at the end of the song. Good night 🌙");
  return true;
}
function tickSleep() {
  if (sleep.songEnd) {  // on another device: stop once it moves on to the next song
    if (elsewhere() && nowKey() !== sleep.songKey) stopForSleep();
    return;
  }
  const left = (sleep.at - Date.now()) / 1000;
  if (left <= 0) return stopForSleep();
  if (!elsewhere()) {
    const f = left < FADE_S ? Math.max(0.05, left / FADE_S) : 1;
    if (f !== fade) { fade = f; applyVolume(); }
  }
  paintSleep();
}
function setSleep(minutes) {
  clearSleep();
  if (minutes === "song") {
    if (!nowKey()) return toast("Nothing playing");
    sleep.songEnd = true; sleep.songKey = nowKey();
    toast("Sleep timer: stops at the end of this song");
  } else if (minutes) {
    sleep.at = Date.now() + minutes * 60000;
    toast(`Sleep timer: pauses in ${minutes} minutes`);
  } else return toast("Sleep timer off");
  sleep.timer = setInterval(tickSleep, 1000);
  paintSleep();
}
function paintSleep() {
  const b = $("btn-sleep");
  const on = !!(sleep.at || sleep.songEnd);
  b.classList.toggle("on", on);
  b.title = !on ? "Sleep timer" : sleep.songEnd ? "Sleep timer: end of this song"
    : `Sleep timer: ${Math.max(1, Math.ceil((sleep.at - Date.now()) / 60000))} min left`;
}
$("btn-sleep").replaceChildren(icon("bedtime", "ico"), "Sleep timer");
$("btn-sleep").addEventListener("click", (e) => {
  closeMenu();
  const btn = e.currentTarget, r = btn.getBoundingClientRect();
  const opt = (label, v) => h("button", { onclick: () => { closeMenu(); setSleep(v); } }, label);
  const on = sleep.at || sleep.songEnd;
  const m = h("div", { class: "menu", style: `right:${Math.max(8, innerWidth - r.right)}px;bottom:${innerHeight - r.top + 6}px` },
    h("div", { class: "muted small", style: "padding:6px 10px" }, on ? btn.title : "Sleep timer"),
    opt("15 minutes", 15), opt("30 minutes", 30), opt("45 minutes", 45), opt("1 hour", 60), opt("End of this song", "song"),
    on ? opt("Turn off", 0) : null);
  document.body.append(m);
  menuOpen = m;
  setTimeout(() => document.addEventListener("mousedown", menuOutside, true));
});

// A screen by name: discover, library, library:artists, album:<id>, artist:<id>, playlist:<id>, stats,
// recap, settings, downloads, jam, nowplaying.
async function demoPlay() {
  const { albums } = await api("/api/library/albums");
  const a = albums.find((x) => x.name === "Afterglow Avenue") || albums[0];
  if (a) playList((await api(`/api/library/albums/${a.id}`)).tracks, 1);
}
function openRoute(r) {
  if (PLAYING) demoPlay().catch(() => {});
  const [what, arg] = r.split(":");
  const id = Number(arg);
  const inLibrary = () => { view = "library"; document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === "library")); };
  if (what === "album") { inLibrary(); return viewAlbum(id); }
  if (what === "artist") { inLibrary(); return viewArtist(id); }
  if (what === "playlist") { inLibrary(); return viewPlaylist(id); }
  if (what === "library") return go("library", arg || undefined);
  if (what === "recap") { view = "stats"; document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === "stats")); return viewRecap(); }
  if (what === "jam") return viewJam();
  if (what === "nowplaying") { go("discover"); return setTimeout(openNowPlaying, 1500); }
  return go(["discover", "stats", "settings", "downloads"].includes(what) ? what : "discover");
}

// --- start ----------------------------------------------------------------------------------------
if (!KEY) show(h("p", { class: "pad warn" }, "Open Dielify from its desktop app."));
else {
  // opens on Discover; in offline mode (no YouTube) on your library instead
  refreshStatus().then(() => GO ? openRoute(GO) : go(status.offline ? "library" : "discover")).catch(() => go("library"));
  pollDownloads(); remoteConnect(); refreshRatings(); paintSide();
  $("update-pill").addEventListener("click", () => go("settings"));
  // the app checks in the background shortly after starting; pick up the result
  setTimeout(() => api("/api/desktop/update").then(showUpdatePill).catch(() => {}), 45000);
}
