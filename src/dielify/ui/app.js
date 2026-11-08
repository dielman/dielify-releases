// Dielify desktop screens. Plain JS, no build step.
// Safety: text from YouTube (titles, names) is only ever set with textContent via h(),
// never as HTML, because this window holds the PC-only key.
"use strict";

// --- key + API ---------------------------------------------------------------------
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
  if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Error ${r.status}`);
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
  play: "M8 5v14l11-7z",
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
function show(...nodes) {
  main.replaceChildren(...nodes.flat(Infinity).filter((n) => n !== null && n !== undefined && n !== false));
  main.scrollTop = 0;
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
function failed(e) { show(h("p", { class: "pad warn" }, e.message || String(e))); }

// --- state ---------------------------------------------------------------------------
let status = null;          // /api/desktop/status
let view = "library";
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
  document.querySelectorAll("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  $("search-input").placeholder = v === "discover" ? "Search YouTube Music" : "Search your library";
  ({ library: viewLibrary, discover: viewDiscover, downloads: viewDownloads, stats: viewStats, settings: viewSettings })[v](...args);
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
  try {
    await refreshStatus();
    const tabs = h("div", { class: "tabs" },
      ["albums", "artists", "playlists", "recent"].map((t) => h("button", { class: t === tab ? "active" : "", onclick: () => viewLibrary(t) },
        { albums: "Albums", artists: "Artists", playlists: "Playlists", recent: "Recently played" }[t])));
    let body;
    if (tab === "playlists") {
      show(welcome(), h("h1", {}, "Library"), tabs, h("p", { class: "muted" }, "Loading playlists…"));
      const [{ playlists: all }, yt, mixStatus] = await Promise.all([api("/api/playlists"),
        api("/api/yt/my-playlists").catch(() => ({ items: [] })), api("/api/mixes").catch(() => null)]);
      const playlists = all.filter((p) => p.kind !== "mix");
      const mixList = all.filter((p) => p.kind === "mix");
      const synced = new Set(playlists.map((p) => p.yt_id).filter(Boolean));
      const notSynced = yt.items.filter((i) => !synced.has(i.id));
      body = [
        h("h2", {}, "Dielify mixes"),
        mixList.length ? h("div", { class: "grid" }, mixList.map(playlistCard))
          : h("p", { class: "muted small" }, mixStatus && mixStatus.artists && mixStatus.looked_up < mixStatus.artists
            ? `Dielify is learning your genres (${mixStatus.looked_up} of ${mixStatus.artists} artists looked up). Your genre, decade and vibe mixes appear when it's done.`
            : "Your genre, decade and vibe mixes appear here once your library has enough songs."),
        h("div", { class: "row" }, h("h2", { style: "flex:1" }, "Your playlists"),
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
const albumCard = (a) => h("div", { class: "card", onclick: () => viewAlbum(a.id) },
  art(media(a.cover_url, 320)), h("div", { class: "t" }, a.name), h("div", { class: "s" }, a.artist, a.year ? ` · ${a.year}` : ""));
const artistCard = (r) => h("div", { class: "card", onclick: () => viewArtist(r.id) },
  art(media(r.cover_url, 320), "👤"), h("div", { class: "t" }, r.name),
  h("div", { class: "s" }, `${r.album_count} album${r.album_count === 1 ? "" : "s"}`));

async function viewArtist(id) {
  try {
    const { artist, albums } = await api(`/api/library/artists/${id}`);
    show(h("button", { onclick: () => viewLibrary("artists") }, icon("back", "ico lead"), "Artists"),
      h("h1", { style: "margin-top:16px" }, artist.name, " ", artistThumbs(artist.name)), h("div", { class: "grid" }, albums.map(albumCard)));
  } catch (e) { failed(e); }
}

async function viewAlbum(id) {
  try {
    const { album, tracks } = await api(`/api/library/albums/${id}`);
    show(h("button", { onclick: () => viewLibrary() }, icon("back", "ico lead"), "Library"),
      h("div", { class: "hero", style: "margin-top:16px" }, art(media(album.cover_url, 400), "♪", ""),
        h("div", {},
          h("div", { class: "muted small" }, "ALBUM"), h("h1", {}, album.name),
          h("div", { class: "muted" }, album.artist, album.year ? ` · ${album.year}` : "", ` · ${tracks.length} songs`),
          h("div", { class: "row", style: "margin-top:12px" },
            ibtn("play", "Play", { class: "primary", onclick: () => playList(tracks, 0) }),
            ibtn("shuffle", "Shuffle", { onclick: () => playList(shuffle(tracks), 0) }),
            ibtn("queueAdd", "Add to queue", { onclick: () => addToQueue(tracks, false) })))),
      trackTable(tracks));
  } catch (e) { failed(e); }
}

async function viewLibrarySearch(q) {
  try {
    const r = await api(`/api/library/search?q=${encodeURIComponent(q)}`);
    show(h("h1", {}, `“${q}” in your library`),
      r.tracks.length ? trackTable(r.tracks, true) : h("p", { class: "muted" }, "No songs found."),
      r.albums.length ? [h("h2", {}, "Albums"), h("div", { class: "grid" }, r.albums.map(albumCard))] : null,
      h("p", {}, h("button", { class: "link", onclick: () => { go("discover"); viewYtSearch(q); } }, "Search YouTube Music instead →")));
  } catch (e) { failed(e); }
}

function trackTable(tracks, showAlbum = false) {
  return h("table", { class: "tracks" }, h("tbody", {}, tracks.map((t, i) =>
    h("tr", { "data-track": t.id, class: player.current && player.current.id === t.id ? "playing" : "" },
      h("td", { class: "n" }, t.track_no || i + 1),
      h("td", { class: "title", onclick: () => playList(tracks, i) }, t.title,
        h("div", { class: "muted small" }, t.artist, showAlbum ? ` · ${t.album}` : "")),
      h("td", { class: "d" }, dur(t.duration_s)),
      h("td", { class: "a" }, queueBtn(() => [t]), t.video_id ? ib("playlistAdd", "Add to playlist", () => addToPlaylist(
        [{ type: "song", id: t.video_id, title: t.title, artists: t.artist ? [t.artist] : [], album: t.album || null }])) : null)))));
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
  try {
    await refreshStatus();
    if (status.offline) return show(h("h1", {}, "Discover"), offlineNotice());
    if (needsSignIn()) return show(h("h1", {}, "Discover"), welcome());
    show(h("h1", {}, "Discover"), h("p", { class: "muted" }, "Loading your YouTube Music home…"));
    const [home, charts, forYou, mixStatus] = await Promise.all([api("/api/discover/home?shelves=8"),
      api("/api/discover/charts").catch(() => null), api("/api/discover/for-you").catch(() => null),
      api("/api/mixes").catch(() => null)]);
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
    const mine = forYou ? [forYou.more_like.length ? [h("h2", {}, "More like your top songs"), h("div", { class: "shelf" }, forYou.more_like.map(ytCard))] : null,
      trackShelf("Forgotten favourites", forYou.forgotten)] : null;
    const endless = h("div", { class: "row", style: "margin:4px 0 8px" },
      h("button", { class: "primary", onclick: () => startEndless() }, icon("shuffle"), " Never-ending discovery"),
      h("span", { class: "muted small" }, " New songs like what you play, downloaded to check out. Thumbs down deletes one again."));
    if (view === "discover") show(h("h1", {}, "Discover"), endless, madeForYou, mine, shelves, chartShelf);
  } catch (e) { failed(e); }
}

function ytCard(item, from, list) {  // also used as .map(ytCard): (item, index, array)
  const origin = from === "library" ? "library" : "discover";
  const sub = item.artists.length ? item.artists.join(", ") : item.subtitle || "";
  const open = () => {
    if (item.type === "album" || item.type === "playlist") return viewCollection(item.type, item.id, origin);
    if (item.type === "song" || item.type === "video") return songActions(item, Array.isArray(list) ? list : [item]);
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
    show(h("p", { class: "muted" }, "Loading…"));
    const { info, tracks } = await api(`/api/yt/${type}/${encodeURIComponent(id)}`);
    const missing = tracks.filter((t) => !t.library_track_id).length;
    const have = tracks.filter((t) => t.library_track_id).map((t) => t.library_track_id);
    const back = from === "library"
      ? h("button", { onclick: () => { go("library"); viewLibrary("playlists"); } }, icon("back", "ico lead"), "Playlists")
      : h("button", { onclick: () => go("discover") }, icon("back", "ico lead"), "Discover");
    show(back,
      h("div", { class: "hero", style: "margin-top:16px" }, art(info.thumbnail, "♪", ""),
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

async function viewYtSearch(q, type = "song") {
  try {
    await refreshStatus();
    if (status.offline) return show(h("h1", {}, "Search"), offlineNotice());
    const tabs = h("div", { class: "tabs" }, ["song", "album", "playlist", "video"].map((t) =>
      h("button", { class: t === type ? "active" : "", onclick: () => viewYtSearch(q, t) }, t[0].toUpperCase() + t.slice(1) + "s")));
    show(h("h1", {}, `“${q}” on YouTube Music`), tabs, h("p", { class: "muted" }, "Searching…"));
    const { items } = await api(`/api/yt/search?q=${encodeURIComponent(q)}&type=${type}`);
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

  show(h("h1", {}, "Downloads"), h("p", { class: "muted" }, "Loading…"));
  pollDownloads();
}
const minutes = (s) => (s < 90 ? "about a minute" : s < 5400 ? `about ${Math.round(s / 60)} min` : `about ${(s / 3600).toFixed(1)} hours`);

async function renderDownloads(active) {
  const { downloads: finished } = await api("/api/downloads?finished=true&limit=40");
  const label = { done: "Done", failed: "Failed", cancelled: "Cancelled" };
  const running = active.downloads.find((d) => d.status === "downloading" || d.status === "processing");
  const waiting = active.downloads.filter((d) => d.status === "queued");
  const waitingTotal = active.active_total - (running ? 1 : 0);
  const pace = active.seconds_per_song || 20;
  const cancel = (d) => ib("close", "Cancel", async () => { await api(`/api/downloads/${d.id}`, { method: "DELETE" }); pollDownloads(); });
  const who = (d) => h("div", {}, h("div", {}, d.title),
    h("div", { class: "muted small" }, d.artist || "", d.error ? h("div", { class: "warn" }, d.error) : null));

  const summary = active.active_total
    ? h("p", { class: "muted" }, running ? `Downloading 1 song` : "Starting…",
        waitingTotal ? ` · ${waitingTotal} waiting · ${minutes(active.active_total * pace)} left` : "",
        " · one at a time, to keep your account's traffic modest")
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
  show(h("h1", {}, "Downloads"), summary, now, line, done);
  main.scrollTop = keep;
}

// --- playlists ---------------------------------------------------------------------------------
function describePlaylist(p) {
  if (p.kind === "mix") return `${p.count} songs · ${p.description || "Dielify mix"} · new every week`;
  return [`${p.count} songs`, p.read_only ? "from YouTube Music (one way)" : p.yt_id ? "synced with YouTube Music" : "only in Dielify",
    p.pending ? `${p.pending} change${p.pending === 1 ? "" : "s"} waiting` : null].filter(Boolean).join(" · ");
}
const playlistCard = (p) => h("div", { class: "card", onclick: () => viewPlaylist(p.id) }, art(p.thumbnail),
  h("div", { class: "t" }, p.name), h("div", { class: "s" }, describePlaylist(p)));
const songIn = (i) => ({ id: i.id, type: i.type === "video" ? "video" : "song", title: i.title, artists: i.artists,
  album: i.album, duration_s: i.duration_s, thumbnail: i.thumbnail });

async function playlistAction(fn, done) {
  try { const r = await fn(); if (done) toast(done); return r; } catch (e) { toast(e.message, 6000); return null; }
}

async function newPlaylist(items) {
  const name = (prompt("Name of the new playlist:") || "").trim();
  if (!name) return;
  const onYoutube = confirm("Also create it on YouTube Music (private) and keep it in sync?\n\nOK = yes, Cancel = only in Dielify");
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
    const songs = entries.map((e) => e.item);
    const have = songs.filter((s) => s.library_track_id).length;
    const rename = async () => {
      const name = (prompt("New name:", p.name) || "").trim();
      if (name && await playlistAction(() => api(`/api/playlists/${id}`, { method: "PATCH", body: { name } }), "Renamed")) viewPlaylist(id);
    };
    const del = async () => {
      if (!confirm(`Delete “${p.name}” from Dielify? Your downloaded songs are kept.`)) return;
      const both = p.yt_id && !p.read_only && confirm(`Also delete it on YouTube Music?\n\nOK = delete there too, Cancel = keep it on YouTube Music (it just stops syncing)`);
      if (await playlistAction(() => api(`/api/playlists/${id}?on_youtube=${!!both}`, { method: "DELETE" }), "Deleted") !== null) {
        go("library"); viewLibrary("playlists");
      }
    };
    const remove = async (e) => {
      if (p.yt_id && !confirm(`Remove “${e.item.title}”? This playlist is synced, so it's also removed on YouTube Music. The song stays in your library.`)) return;
      if (await playlistAction(() => api(`/api/playlists/${id}/entries/${e.entry_id}?on_youtube=${!!p.yt_id}`, { method: "DELETE" }), "Removed")) viewPlaylist(id);
    };
    show(h("button", { onclick: () => { go("library"); viewLibrary("playlists"); } }, icon("back", "ico lead"), "Playlists"),
      h("div", { class: "hero", style: "margin-top:16px" }, art(p.thumbnail, "♪", ""),
        h("div", {}, h("div", { class: "muted small" }, "PLAYLIST"), h("h1", {}, p.name),
          h("div", { class: "muted" }, describePlaylist(p)),
          p.sync_error ? h("div", { class: "warn small" }, `Couldn't reach YouTube: ${p.sync_error}`) : null,
          have < songs.length ? h("div", { class: "muted small" }, `${songs.length - have} not on this PC yet: they're downloading. Play works anyway.`) : null,
          h("div", { class: "row", style: "margin-top:12px" },
            ibtn("play", "Play", { class: "primary", disabled: !songs.length, onclick: () => songActions(songs[0], songs) }),
            ibtn("shuffle", "Shuffle", { disabled: !songs.length, onclick: () => { const s = shuffle(songs); songActions(s[0], s); } }),
            ibtn("queueAdd", "Add to queue", { disabled: !songs.length, onclick: () => addToQueue(songs.map(ytAsTrack), false) }),
            p.yt_id ? ibtn("sync", "Sync now", { onclick: async () => { if (await playlistAction(() => api(`/api/playlists/${id}/sync`, { method: "POST" }), "Synced")) viewPlaylist(id); } }) : null,
            p.read_only ? null : ibtn("edit", "Rename", { onclick: rename }),
            p.kind === "mix" ? null : ibtn("remove", "Delete", { onclick: del })))),
      h("table", { class: "tracks" }, h("tbody", {}, entries.map((e, i) => h("tr", {},
        h("td", { class: "n" }, i + 1),
        h("td", { class: "title", onclick: () => songActions(e.item, songs) }, e.item.title,
          h("div", { class: "muted small" }, e.item.artists.join(", "), e.item.album ? ` · ${e.item.album}` : "")),
        h("td", { class: "d" }, dur(e.item.duration_s)),
        h("td", { class: "a" }, queueBtn(() => [ytAsTrack(e.item)]), e.item.library_track_id ? h("span", { class: "ib in-lib", title: "In your library" }, icon("check")) : null,
          p.read_only ? null : ib("remove", "Remove from this playlist", () => remove(e))))))));
  } catch (e) { failed(e); }
}

// --- stats -------------------------------------------------------------------------------------
let statsPeriod = "month";
async function viewStats(period = statsPeriod) {
  statsPeriod = period;
  try {
    const st = await api(`/api/stats?period=${period}&limit=25`);
    const tabs = h("div", { class: "tabs" }, [["week", "This week"], ["month", "This month"], ["year", "This year"], ["all", "All time"]]
      .map(([p, l]) => h("button", { class: p === period ? "active" : "", onclick: () => viewStats(p) }, l)));
    if (!st.plays) {
      return show(h("h1", {}, "Your stats"), tabs, h("p", { class: "muted" }, st.history_starts
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

// --- settings --------------------------------------------------------------------------------
async function saveSettings(body, msg = "Saved") {
  try { await api("/api/desktop/settings", { method: "PUT", body }); toast(msg); } catch (e) { toast(e.message, 6000); }
  viewSettings();
}

async function signIn(fresh) {
  const app = desktopApp();
  if (!app) return toast("Sign-in works in the Dielify app window.");
  toast("A sign-in window has opened. Sign in there.", 6000);
  const r = await app.sign_in(status.active_profile, fresh);
  if (r.ok) toast(`Signed in as ${r.account}`);
  else if (r.error) toast(r.error, 8000);
  go(view);
}

async function viewSettings() {
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
      setting("Quality", "", select("quality", { auto: "Best available (Premium: ~256 kbps)", high: "High", standard: "Standard (~160 kbps max)" }, s.quality)),
      setting("Format", "", select("preferred_format", { auto: "Automatic (no re-encoding)", opus: "Prefer Opus", m4a: "Prefer AAC (.m4a)" }, s.preferred_format)));

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
        h("div", { class: "value" }, `plays profile ${u.profile}`,
          u.devices.map((d) => h("div", { class: "small muted" }, `${d.device_name} · last used ${d.last_used_at ? new Date(d.last_used_at * 1000).toLocaleString() : "never"} `,
            h("button", { class: "link", onclick: async () => { await api(`/api/desktop/devices/${d.id}`, { method: "DELETE" }); viewSettings(); } }, "sign out")))),
        h("button", { onclick: async () => {
          if (!confirm(`Make a new password for ${u.name}? The old one stops working.`)) return;
          showPassword(await api(`/api/desktop/phone-users/${encodeURIComponent(u.name)}/password`, { method: "POST" }));
        } }, "New password"),
        h("button", { onclick: async () => {
          if (!confirm(`Remove the phone login ${u.name}? Its phones are signed out.`)) return;
          await api(`/api/desktop/phone-users/${encodeURIComponent(u.name)}`, { method: "DELETE" }); viewSettings();
        } }, "Remove"))),
      h("div", { class: "row", style: "margin-top:10px" }, h("button", { onclick: addPhoneUser }, "Add phone login")));

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
    show(h("h1", {}, "Settings"), youtube, music, playbackPanel(), windows, phones, backups, ratingsPanel(), about);
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

async function addProfile() {
  const name = prompt("Name for the new profile (letters and digits, e.g. emma):");
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
function showPassword(login) {
  show(h("h1", {}, "Phone login"), h("div", { class: "panel" },
    h("p", {}, "Type these into the phone app now. The password is shown only this once."),
    h("div", { class: "setting" }, h("div", { class: "label" }, "Server address"), h("div", { class: "value" }, status.addresses[0] || "")),
    h("div", { class: "setting" }, h("div", { class: "label" }, "User"), h("div", { class: "value secret" }, login.name)),
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
[["btn-prev", "prev"], ["btn-play", "play"], ["btn-next", "next"], ["btn-addpl", "playlistAdd"], ["btn-devices", "devices"]]
  .forEach(([id, name]) => $(id).replaceChildren(icon(name)));
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
  player.list = list; player.endless = false; playAt(index);
}

// --- never-ending discovery play (explore.py) ----------------------------------------------------
async function endlessBatch(count) {
  const ids = player.list.map((t) => t.video_id).filter(Boolean);
  const heard = player.list.slice(0, player.index + 1).map((t) => t.video_id).filter(Boolean);
  const seeds = heard.length ? heard.slice(-20) : (player.current && player.current.video_id ? [player.current.video_id] : []);
  const r = await api("/api/discover/endless", { method: "POST", body: { seeds, exclude: ids.slice(-2000), count } });
  return r.items.map(ytAsTrack);
}
async function startEndless() {
  try {
    toast("Finding new songs…");
    const keep = player.current && !elsewhere() ? [player.current] : [];
    player.list = keep; player.index = keep.length - 1;
    const more = await endlessBatch(10);
    if (!more.length) return toast("Couldn't find new songs right now");
    if (elsewhere()) return playList(more, 0);  // the other device plays this batch (it doesn't top up)
    player.list = [...keep, ...more]; player.endless = true;
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
  audio.play().catch((e) => toast(`Can't play: ${e.message}`));
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
}
function paintBar() {
  const d = elsewhere();
  const strip = $("connect-strip");
  strip.hidden = !d;
  $("btn-devices").classList.toggle("on", !!d);
  if (d) {
    strip.textContent = `${d.kind === "pc" ? "💻" : "📱"} Playing on ${d.name}`;
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
  if (document.activeElement !== $("volume")) $("volume").value = Math.round(player.vol * 100);
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
  if (!t || !t.video_id) return toast(t ? "This song has no YouTube id, so it can't go in a playlist." : "Nothing playing");
  addToPlaylist([{ type: "song", id: t.video_id, title: t.title, artists: t.artist ? [t.artist] : [], album: t.album || null }]);
});
onAudio("play", () => { if (!elsewhere()) paintBar(); });
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
      h("span", { class: "picker-icon" }, d.kind === "pc" ? "💻" : "📱"),
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
      toast(`Thumbs down: deleted “${res.removed}” from your PC`);
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
      ib("thumbUp", v === UP ? "You like this artist (click to clear)" : "Like this artist",
        async () => { await rate("artist", { name }, v === UP ? 0 : UP); paint(); }, { class: `ib${v === UP ? " on" : ""}` }),
      ib("thumbDown", v === DOWN ? "Thumbed down (click to clear)" : "Less of this artist (hold to ban)",
        async () => { if (!heldA) { await rate("artist", { name }, v === DOWN ? 0 : DOWN); paint(); } }, { class: `ib${v === DOWN ? " on" : ""}` }),
      v === BAN ? h("span", { class: "muted small" }, " Banned · ",
        h("button", { class: "link", onclick: async () => { await rate("artist", { name }, 0, `Unbanned ${name}`); paint(); } }, "unban")) : null);
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
  return h("div", { class: "panel" }, h("h2", {}, "Playback on this PC"),
    h("label", { class: "row", style: "gap:8px" }, box, "Even out volume"),
    h("p", { class: "muted small" }, "Loud songs are turned down to match the rest, so the volume doesn't jump between songs. "
      + "Dielify measures each song once in the background (new downloads within a few minutes)."));
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
    h("button", { onclick: () => { closeMenu(); addToQueue(tracks, false); } }, icon("queueAdd", "ico lead"), "Add to queue"));
  document.body.append(m);
  if (r.bottom + 4 + m.offsetHeight > innerHeight - 90) m.style.top = `${r.top - m.offsetHeight - 4}px`;
  menuOpen = m;
  setTimeout(() => document.addEventListener("mousedown", menuOutside, true));
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
      : cur ? h("p", { class: "muted small" }, player.endless && !q.d ? "Finding more new songs…"
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

// --- lyrics (dielify/lyrics.py): over the page, scrolling along with the song ----------------------
const lyr = { box: null, key: "", data: null, cache: new Map(), line: -2, timer: null };
function lyricsSong() {
  const d = elsewhere();
  if (d) {
    const st = d.state || {};
    const s = st.queue && st.index >= 0 ? st.queue[st.index] : null;
    return s && { video_id: s.video_id || null, id: s.track_id || null, title: s.title, artist: s.artist || "",
      album: s.album || "", duration_s: st.duration_ms ? Math.round(st.duration_ms / 1000) : null };
  }
  const t = player.current;
  return t && { video_id: t.video_id || null, id: t.id || null, title: t.title, artist: t.artist || "",
    album: t.album || "", duration_s: Math.round(audio.duration) || null };
}
const lyricsPos = () => { const d = elsewhere(); return d ? nowPos(d.state || {}) : audio.currentTime * 1000; };
async function loadLyrics(s) {
  const key = s.video_id || `tr-${s.id}`;
  if (lyr.cache.has(key)) return lyr.cache.get(key);
  const q = new URLSearchParams();
  if (s.id) q.set("track_id", s.id);
  if (s.video_id) q.set("video_id", s.video_id);
  if (!s.id) { q.set("title", s.title); if (s.artist) q.set("artist", s.artist); if (s.album) q.set("album", s.album); }
  if (s.duration_s) q.set("duration_s", s.duration_s);
  let data = null;
  try { data = await api(`/api/lyrics?${q}`); } catch (e) { data = { error: /No lyrics/.test(e.message) ? null : e.message }; }
  if (data && !data.error) lyr.cache.set(key, data);
  return data;
}
async function paintLyrics() {
  const box = lyr.box;
  if (!box) return;
  const s = lyricsSong();
  const key = s ? s.video_id || `tr-${s.id}` : "";
  if (key !== lyr.key) {
    lyr.key = key; lyr.data = null; lyr.line = -2;
    const head = h("div", { class: "lyr-head" }, h("div", {}, h("b", {}, s ? s.title : "Nothing playing"),
      h("div", { class: "muted small" }, s ? s.artist : "")), ib("close", "Close lyrics", closeLyrics));
    const body = h("div", { class: "lyr-body" }, s ? h("p", { class: "muted" }, "Looking for lyrics…") : null);
    box.replaceChildren(head, body);
    if (!s) return;
    const data = await loadLyrics(s);
    if (lyr.key !== key || !lyr.box) return;  // the song changed meanwhile
    lyr.data = data;
    if (!data || data.error) {
      body.replaceChildren(h("p", { class: "muted" }, data && data.error ? `Couldn't get lyrics: ${data.error}` : "No lyrics for this song."));
      return;
    }
    const seek = (ms) => { if (!control({ action: "seek", position_ms: ms })) audio.currentTime = ms / 1000; };
    body.replaceChildren(...(data.synced
      ? data.lines.map((l) => h("div", { class: "lyr-line", onclick: () => seek(l.ms) }, l.text || "♪"))
      : data.text.split("\n").map((t) => h("div", { class: "lyr-line plain" }, t || " "))),
      h("p", { class: "muted small lyr-src" }, data.source ? `Lyrics: ${data.source}` : ""));
  }
  const data = lyr.data;
  if (!data || !data.synced) return;
  const pos = lyricsPos() + 200;  // show a line a moment early, like karaoke
  let i = -1;
  while (i + 1 < data.lines.length && data.lines[i + 1].ms <= pos) i++;
  if (i === lyr.line) return;
  lyr.line = i;
  const rows = box.querySelectorAll(".lyr-line");
  rows.forEach((r, k) => { r.classList.toggle("now", k === i); r.classList.toggle("past", k < i); });
  const cur = rows[Math.max(0, i)];
  if (cur) cur.scrollIntoView({ block: "center", behavior: "smooth" });
}
function closeLyrics() {
  if (lyr.box) { lyr.box.remove(); lyr.box = null; }
  clearInterval(lyr.timer);
  $("btn-lyrics").classList.remove("on");
}
$("btn-lyrics").replaceChildren(icon("mic"));
$("btn-lyrics").addEventListener("click", () => {
  if (lyr.box) return closeLyrics();
  const top = document.querySelector("header.top").getBoundingClientRect().bottom;
  const bottom = innerHeight - $("player").getBoundingClientRect().top;
  lyr.box = h("div", { class: "lyrics", style: `top:${top}px;bottom:${bottom}px` });
  document.body.append(lyr.box);
  lyr.key = null;
  $("btn-lyrics").classList.add("on");
  paintLyrics();
  lyr.timer = setInterval(paintLyrics, 250);
});

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
$("btn-sleep").replaceChildren(icon("bedtime"));
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

// --- start ----------------------------------------------------------------------------------------
if (!KEY) show(h("p", { class: "pad warn" }, "Open Dielify from its desktop app."));
else {
  go("library"); pollDownloads(); remoteConnect(); refreshRatings();
  $("update-pill").addEventListener("click", () => go("settings"));
  // the app checks in the background shortly after starting; pick up the result
  setTimeout(() => api("/api/desktop/update").then(showUpdatePill).catch(() => {}), 45000);
}
