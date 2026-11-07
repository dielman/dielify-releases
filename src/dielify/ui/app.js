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
  ({ library: viewLibrary, discover: viewDiscover, downloads: viewDownloads, settings: viewSettings })[v](...args);
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
      ["albums", "artists", "recent"].map((t) => h("button", { class: t === tab ? "active" : "", onclick: () => viewLibrary(t) },
        { albums: "Albums", artists: "Artists", recent: "Recently played" }[t])));
    let body;
    if (tab === "artists") {
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
    const [home, charts] = await Promise.all([api("/api/discover/home?shelves=8"),
      api("/api/discover/charts").catch(() => null)]);
    const shelves = home.shelves.filter((s) => s.items.length).map((s) =>
      [h("h2", {}, s.title), h("div", { class: "shelf" }, s.items.map(ytCard))]);
    const chartShelf = charts && charts.playlists.length
      ? [h("h2", {}, `Charts · ${charts.country}`), h("div", { class: "shelf" }, charts.playlists.map(ytCard))] : null;
    if (view === "discover") show(h("h1", {}, "Discover"), shelves, chartShelf);
  } catch (e) { failed(e); }
}

function ytCard(item) {
  const sub = item.artists.length ? item.artists.join(", ") : item.subtitle || "";
  const open = () => {
    if (item.type === "album" || item.type === "playlist") return viewCollection(item.type, item.id);
    if (item.type === "song" || item.type === "video") return songActions(item);
  };
  return h("div", { class: "card", onclick: open, title: `${item.title}${sub ? " — " + sub : ""}` },
    art(item.thumbnail, item.type === "artist" ? "👤" : "♪"),
    h("div", { class: "t" }, item.title),
    h("div", { class: "s" }, item.library_track_id ? "✓ In library · " : "", sub));
}

async function songActions(item) {
  if (item.library_track_id) {
    const t = await api(`/api/library/tracks/${item.library_track_id}`);
    return playList([t], 0);
  }
  await requestDownload({ type: item.type, id: item.id, title: item.title, artists: item.artists, album: item.album });
}

async function requestDownload(body) {
  try {
    const r = await api("/api/downloads", { method: "POST", body });
    const n = r.downloads.filter((d) => d.status !== "done").length;
    toast(n ? `Downloading ${n} song${n === 1 ? "" : "s"}… (see Downloads)` : "Already in your library");
    pollDownloads();
  } catch (e) { toast(e.message, 6000); }
}

async function viewCollection(type, id) {
  try {
    show(h("p", { class: "muted" }, "Loading…"));
    const { info, tracks } = await api(`/api/yt/${type}/${encodeURIComponent(id)}`);
    const missing = tracks.filter((t) => !t.library_track_id).length;
    show(h("button", { onclick: () => go("discover") }, "← Discover"),
      h("div", { class: "hero", style: "margin-top:16px" }, art(info.thumbnail, "♪", ""),
        h("div", {},
          h("div", { class: "muted small" }, type.toUpperCase()), h("h1", {}, info.title),
          h("div", { class: "muted" }, info.artists.join(", ") || info.subtitle || "", ` · ${tracks.length} songs`),
          h("div", { class: "row", style: "margin-top:12px" },
            h("button", { class: "primary", disabled: !missing, onclick: () => requestDownload({ type, id }) },
              missing ? `Download ${missing === tracks.length ? "all" : missing + " missing"}` : "All in library")))),
      ytTrackTable(tracks));
  } catch (e) { failed(e); }
}

function ytTrackTable(items) {
  return h("table", { class: "tracks" }, h("tbody", {}, items.map((t, i) =>
    h("tr", {},
      h("td", { class: "n" }, i + 1),
      h("td", {}, t.title, h("div", { class: "muted small" }, t.artists.join(", "), t.album ? ` · ${t.album}` : "")),
      h("td", { class: "d" }, dur(t.duration_s)),
      h("td", { class: "a" }, t.library_track_id
        ? h("button", { onclick: () => songActions(t) }, "▶ Play")
        : h("button", { onclick: () => songActions(t) }, "Download"))))));
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
    const { downloads } = await api("/api/downloads?active=true");
    const badge = $("dl-badge");
    badge.hidden = !downloads.length; badge.textContent = downloads.length;
    if (view === "downloads") await renderDownloads();
    if (downloads.length || view === "downloads") dlTimer = setTimeout(pollDownloads, 1500);
  } catch { dlTimer = setTimeout(pollDownloads, 5000); }
}
async function viewDownloads() { show(h("h1", {}, "Downloads"), h("p", { class: "muted" }, "Loading…")); pollDownloads(); }
async function renderDownloads() {
  const { downloads } = await api("/api/downloads?limit=100");
  const label = { queued: "Waiting", downloading: "Downloading", processing: "Tagging", done: "Done", failed: "Failed", cancelled: "Cancelled" };
  const rows = downloads.map((d) => h("div", { class: "job" },
    h("div", {}, h("div", {}, d.title), h("div", { class: "muted small" }, d.artist || "", d.error ? h("div", { class: "warn" }, d.error) : null)),
    d.status === "downloading" || d.status === "processing"
      ? h("div", { class: "bar" }, h("div", { style: `width:${Math.round(d.progress * 100)}%` }))
      : h("div", { class: `small status-${d.status}` }, label[d.status]),
    ["queued", "downloading", "processing"].includes(d.status)
      ? h("button", { onclick: async () => { await api(`/api/downloads/${d.id}`, { method: "DELETE" }); pollDownloads(); } }, "Cancel")
      : d.track_id ? h("button", { onclick: async () => playList([await api(`/api/library/tracks/${d.track_id}`)], 0) }, "▶ Play") : h("span")));
  if (view === "downloads") show(h("h1", {}, "Downloads"), rows.length ? rows : h("p", { class: "muted" }, "Nothing downloaded yet."));
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
        p.youtube_signed_in ? h("button", { onclick: () => signIn(true) }, "Use another account") : null,
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
        toggle("start_with_windows", s.start_with_windows, "Dielify will start with Windows", "Dielify won't start with Windows")));

    const phones = h("div", { class: "panel" }, h("h2", {}, "Phone apps"),
      h("p", { class: "muted" }, "Phones on your home network can play your library (Symfonium, or the Dielify app later). Address: ",
        s.addresses.length ? s.addresses.join("  or  ") : "(no home-network address found)"),
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

    const about = h("div", { class: "panel" }, h("h2", {}, "About"), setting("Version", `Dielify ${s.version}`));
    show(h("h1", {}, "Settings"), youtube, music, windows, phones, about);
  } catch (e) { failed(e); }
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
function playAt(i) {
  if (i < 0 || i >= player.list.length) return;
  const t = player.list[i];
  player.index = i; player.current = t; player.counted = false;
  audio.src = media(t.stream_url);
  audio.play().catch((e) => toast(`Can't play: ${e.message}`));
  $("np-title").textContent = t.title;
  $("np-artist").textContent = `${t.artist} · ${t.album}`;
  const cover = $("np-cover");
  cover.hidden = !t.cover_url;
  if (t.cover_url) cover.src = media(t.cover_url, 112);
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
audio.addEventListener("ended", () => playAt(player.index + 1));
audio.addEventListener("timeupdate", () => {
  const d = audio.duration || 0;
  $("t-cur").textContent = dur(audio.currentTime) || "0:00";
  $("t-dur").textContent = dur(d) || "0:00";
  if (!seeking && d) $("seek").value = Math.round((audio.currentTime / d) * 1000);
  // counts as played after half the song or 4 minutes (like most scrobblers)
  if (!player.counted && d && (audio.currentTime > d / 2 || audio.currentTime > 240)) {
    player.counted = true;
    api(`/api/library/tracks/${player.current.id}/played`, { method: "POST" }).catch(() => {});
  }
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
else { go("library"); pollDownloads(); }
