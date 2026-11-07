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
      show(welcome(), h("h1", {}, "Library"), tabs, h("p", { class: "muted" }, "Loading your YouTube Music playlists…"));
      const { items } = await api("/api/yt/my-playlists");
      body = items.length
        ? [h("p", { class: "muted small" }, "Your playlists on YouTube Music. Open one to download the songs you don't have yet."),
           h("div", { class: "grid" }, items.map((it) => ytCard(it, "library")))]
        : empty("No playlists on your YouTube Music account.");
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
    show(h("button", { onclick: () => viewLibrary("artists") }, "← Artists"),
      h("h1", { style: "margin-top:16px" }, artist.name), h("div", { class: "grid" }, albums.map(albumCard)));
  } catch (e) { failed(e); }
}

async function viewAlbum(id) {
  try {
    const { album, tracks } = await api(`/api/library/albums/${id}`);
    show(h("button", { onclick: () => viewLibrary() }, "← Library"),
      h("div", { class: "hero", style: "margin-top:16px" }, art(media(album.cover_url, 400), "♪", ""),
        h("div", {},
          h("div", { class: "muted small" }, "ALBUM"), h("h1", {}, album.name),
          h("div", { class: "muted" }, album.artist, album.year ? ` · ${album.year}` : "", ` · ${tracks.length} songs`),
          h("div", { class: "row", style: "margin-top:12px" },
            h("button", { class: "primary", onclick: () => playList(tracks, 0) }, "▶ Play"),
            h("button", { onclick: () => playList(shuffle(tracks), 0) }, "Shuffle")))),
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
      h("td", { class: "d" }, dur(t.duration_s))))));
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
    const [home, charts, forYou] = await Promise.all([api("/api/discover/home?shelves=8"),
      api("/api/discover/charts").catch(() => null), api("/api/discover/for-you").catch(() => null)]);
    const shelves = home.shelves.filter((s) => s.items.length).map((s) =>
      [h("h2", {}, s.title), h("div", { class: "shelf" }, s.items.map(ytCard))]);
    const chartShelf = charts && charts.playlists.length
      ? [h("h2", {}, `Charts · ${charts.country}`), h("div", { class: "shelf" }, charts.playlists.map(ytCard))] : null;
    const trackShelf = (title, tracks) => tracks.length ? [h("h2", {}, title), h("div", { class: "shelf" },
      tracks.map((t, i) => h("div", { class: "card", onclick: () => playList(tracks, i) },
        art(media(t.cover_url, 320)), h("div", { class: "t" }, t.title), h("div", { class: "s" }, t.artist))))] : null;
    const mine = forYou ? [trackShelf("On repeat", forYou.on_repeat),
      forYou.more_like.length ? [h("h2", {}, "More like your top songs"), h("div", { class: "shelf" }, forYou.more_like.map(ytCard))] : null,
      trackShelf("Forgotten favourites", forYou.forgotten)] : null;
    if (view === "discover") show(h("h1", {}, "Discover"), mine, shelves, chartShelf);
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
      ? h("button", { onclick: () => { go("library"); viewLibrary("playlists"); } }, "← Playlists")
      : h("button", { onclick: () => go("discover") }, "← Discover");
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
      h("td", {}, t.title, h("div", { class: "muted small" }, t.artists.join(", "), t.album ? ` · ${t.album}` : "")),
      h("td", { class: "d" }, dur(t.duration_s)),
      h("td", { class: "a" }, h("button", { onclick: () => songActions(t, items) }, "▶ Play"),
        t.library_track_id ? null : h("button", { onclick: () => requestDownload(
          { type: t.type, id: t.id, title: t.title, artists: t.artists, album: t.album, next: true }) }, "Download"))))));
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
  const cancel = (d) => h("button", { onclick: async () => { await api(`/api/downloads/${d.id}`, { method: "DELETE" }); pollDownloads(); } }, "Cancel");
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
    h("div", {}, d.next || i === 0 ? null : h("button", { title: "Download this next", onclick: async () => { await api(`/api/downloads/${d.id}/next`, { method: "POST" }); pollDownloads(); } }, "Move up"), cancel(d)))),
    waitingTotal > waiting.length ? h("p", { class: "muted small" }, `…and ${waitingTotal - waiting.length} more`) : null] : null;
  const done = finished.length ? [h("h2", {}, "Finished"), finished.map((d) => h("div", { class: "job" }, who(d),
    h("div", { class: `small status-${d.status}` }, label[d.status]),
    d.track_id ? h("button", { onclick: async () => playList([await api(`/api/library/tracks/${d.track_id}`)], 0) }, "▶ Play") : h("span")))] : null;

  if (view !== "downloads") return;
  const keep = main.scrollTop;  // re-drawn every 1.5 s: don't jump back to the top
  show(h("h1", {}, "Downloads"), summary, now, line, done);
  main.scrollTop = keep;
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
    show(h("h1", {}, "Settings"), youtube, music, windows, phones, backups, about);
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
const audio = $("audio");
const player = { list: [], index: -1, current: null, counted: false };
audio.volume = 0.8;

function playList(list, index) {
  player.list = list; playAt(index);
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

function playAt(i) {
  if (i < 0 || i >= player.list.length) return;
  reportPlay();
  const t = player.list[i];
  player.index = i; player.current = t; player.counted = false;
  heard = 0; lastTick = null; startedAt = Date.now() / 1000;
  audio.src = media(t.stream_url);
  audio.play().catch((e) => toast(`Can't play: ${e.message}`));
  $("np-title").textContent = t.title;
  $("np-artist").textContent = `${t.artist} · ${t.album}`;
  const cover = $("np-cover");
  cover.hidden = !t.cover_url && !t.thumb;
  if (t.cover_url) cover.src = media(t.cover_url, 112);
  else if (t.thumb) cover.src = t.thumb;
  document.querySelectorAll("tr[data-track]").forEach((r) => r.classList.toggle("playing", Number(r.dataset.track) === t.id));
}
$("btn-play").addEventListener("click", () => {
  if (!player.current) return;
  audio.paused ? audio.play() : audio.pause();
});
$("btn-next").addEventListener("click", () => playAt(player.index + 1));
$("btn-prev").addEventListener("click", () => (audio.currentTime > 3 ? (audio.currentTime = 0) : playAt(player.index - 1)));
audio.addEventListener("play", () => ($("btn-play").textContent = "⏸"));
audio.addEventListener("pause", () => ($("btn-play").textContent = "▶"));
audio.addEventListener("ended", () => { reportPlay(); playAt(player.index + 1); });
audio.addEventListener("timeupdate", () => {
  const d = audio.duration || 0;
  const now = audio.currentTime;
  if (lastTick !== null && !audio.paused && now > lastTick && now - lastTick < 2) heard += now - lastTick;
  lastTick = now;
  $("t-cur").textContent = dur(audio.currentTime) || "0:00";
  $("t-dur").textContent = dur(d) || "0:00";
  if (!seeking && d) $("seek").value = Math.round((audio.currentTime / d) * 1000);
});
let seeking = false;
$("seek").addEventListener("input", () => (seeking = true));
$("seek").addEventListener("change", (e) => {
  if (audio.duration) audio.currentTime = (e.target.value / 1000) * audio.duration;
  seeking = false;
});
$("volume").addEventListener("input", (e) => (audio.volume = e.target.value / 100));
document.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName)) {
    e.preventDefault(); $("btn-play").click();
  }
});

// --- start ----------------------------------------------------------------------------------------
if (!KEY) show(h("p", { class: "pad warn" }, "Open Dielify from its desktop app."));
else {
  go("library"); pollDownloads();
  $("update-pill").addEventListener("click", () => go("settings"));
  // the app checks in the background shortly after starting; pick up the result
  setTimeout(() => api("/api/desktop/update").then(showUpdatePill).catch(() => {}), 45000);
}
