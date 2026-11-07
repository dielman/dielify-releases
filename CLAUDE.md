# CLAUDE.md — working notes for Claude sessions

Read this first in every session. Keep it current: update **Current status** at the
end of each working session and record any new decision under **Decisions log**.

## What this project is

A self-hosted YouTube Music system for Josh's Windows 11 PC. It signs in to YouTube
Music (Premium), searches and discovers music, downloads audio to a configurable
local folder with full tags and cover art, plays it offline, and serves the library
over LAN and Tailscale to a custom native Android app. Multi-user: each person has
their own profile, library folder and YouTube login. Name: **Dielify** (Josh's choice, 7 Nov 2026;
the working name until then was `ymp`).

The full brief is `docs/HANDOFF.md`.

## Decisions already made — do NOT change without asking Josh

1. **Terms of service:** Josh has accepted the ToS considerations and keeps his
   YouTube subscription active. No warnings or refusals on this basis.
2. **Android app:** custom native app (Kotlin, Compose, Media3) — one app for
   discovery, search, tap-to-download, download queue and playback. Not a PWA.
3. **Server compatibility:** expose the Subsonic/OpenSubsonic API so Symfonium,
   Ultrasonic and DSub work as a fallback and test harness.
4. **Remote access:** Tailscale only. Never exposed to the public internet, no port
   forwarding.
5. **Platform:** Windows 11 PC, Android phone.
6. **Extensibility:** design for the extension list in `docs/HANDOFF.md` §10.
7. **Discovery:** YouTube Music's own home feed, mixes, similar tracks and charts.

## Working agreements

- Phase by phase. Do not start the next phase until the current phase's acceptance
  criteria pass **and Josh confirms**.
- Small, runnable steps. Run after each change and show the result.
- Explain Windows setup plainly.
- Flag security concerns directly; never quietly work around them.
- Never commit secrets, the database, or music. Never log cookies or tokens.
- **AppData is redirected for anything started from the Claude desktop app** (it's an
  MSIX package). Writes under `%LOCALAPPDATA%`/`%APPDATA%` from Claude's shell, and
  from programs Claude starts, land in
  `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Local\...`, and Claude's reads
  see that copy first. Dielify started normally (Start menu, installer) uses the real
  folder, which Claude can't see. So: never "fix" Josh's data from Claude's shell, never
  judge the installed app by files Claude can read, don't start the installed app
  yourself for testing. `E:\` is not redirected. To see the real app's state, ask Josh
  (Settings > About shows data folder + log file; errors show their message on screen).
- In every instruction for Josh, list what he needs **before** the step: which
  password, which terminal (admin or not), whether `.venv` must be active (prefer
  `.venv\Scripts\python` / `.venv\Scripts\dielify` so it doesn't matter), which
  site/window. Don't let him discover a requirement by failing.

## Architecture

```
Android app (Kotlin) --Tailscale / LAN--> Server (Python, FastAPI)       [Phase 2+]
Desktop GUI (web UI in native window) --> Server (same engine)           [Phase 4]

src/dielify/
  yt_adapter.py   ytmusicapi + yt-dlp behind ONE interface. The only module that
                  imports them. When YouTube breaks something, fix it here.
  downloader.py   fetch -> tag -> move into Artist/Album/Track. (Queue/retries: Ph.3)
  tagging.py      mutagen tags + embedded cover art for m4a / opus / mp3 / flac
  credstore.py    per-profile YouTube credentials, encrypted with Windows DPAPI
  settings.py     JSON settings: library root, quality, format, cache limit
  paths.py        app data dirs + Windows-safe filename handling
  cli.py          `dielify` command (Phase 1 user interface)
  library.py      SQLite index (dielify.db); files are the truth, a scan rebuilds it
  auth.py         server users (Subsonic logins, DPAPI store "server_users"), lockout
  subsonic_api.py /rest/* Subsonic + OpenSubsonic, JSON and XML
  server.py       FastAPI app + uvicorn on explicit sockets (never 0.0.0.0)
  custom_api.py   /api/*: discovery, YouTube catalogue, downloads, library, settings,
                  device-token login. Pydantic models = the Android contract;
                  regenerate docs/openapi.json with `dielify server openapi --out ...`
  downloads.py    persistent queue, 1 worker, 3 attempts (30s/120s back-off),
                  cancel, holds jobs while the YouTube sign-in is dead
  desktop.py      the desktop app: pywebview window (WebView2) + pystray tray + server
                  on a background thread; in-window YouTube sign-in (Bridge.sign_in)
  desktop_api.py  /api/desktop/*: PC-only settings, profiles, phone logins
                  (desktop key only; phones get 403)
  winint.py       single instance (named mutex + show event), HKCU Run key, MessageBox
  ui/             desktop screens: index.html, app.js, app.css (no build step)
  # planned (Phase 5): Tailscale binding, token management CLI, rate limits
```

### Key technical facts (verified 7 Nov 2026)

- **YouTube sign-in:** ytmusicapi *browser-header* auth (paste request headers from
  DevTools). Google removed ytmusicapi's shared OAuth client in Nov 2024; OAuth now
  needs a personal Google Cloud client and gives no cookies for stream access, so we
  do not use it. **Headers must come from an Incognito window that is then closed**
  (verified 7 Nov 2026: headers from Josh's normal Chrome went stale within hours,
  because Chrome rotates __Secure-*PSIDTS cookies and Google invalidates old copies).
  The queue re-checks the sign-in (≤ every 10 min) and holds jobs while it's dead,
  because yt-dlp otherwise silently falls back to non-Premium formats (~128k).
- **yt-dlp needs a JavaScript runtime for YouTube** (since 2025.11.12). Deno is the
  default and recommended: `winget install --id=DenoLand.Deno`. `dielify doctor` checks.
- **Premium quality:** with Premium cookies, YouTube offers ~256 kbps Opus (itag 774,
  verified live 7 Nov 2026) and 256 kbps AAC (itag 141). `auto` picked 774. Without
  Premium the best is ~160 kbps Opus (itag 251).
- **Sign-in headers must come from music.youtube.com.** Headers copied from
  www.youtube.com got a signed-out response; `parse_browser_headers` rejects them
  up front. It also normalises every DevTools copy format first, because
  ytmusicapi's own parser fails on Windows line endings and Chrome's views.
- **`get_account_info()` is broken** in ytmusicapi 1.12.3 (account-menu layout
  changed). `account_name()` falls back to searching the raw menu response. We pass the signed-in cookies to
  yt-dlp via a temporary Netscape cookie file that is deleted after each download.
- **No re-encoding:** audio is remuxed only (webm/opus -> .opus, AAC -> .m4a).
- **Custom tag `DIELIFY_VIDEOID`** (m4a: `----:com.dielify:videoId`) in every file so the
  Phase 2 library index can map files back to YouTube.

### Data locations (Windows)

- Settings: `%LOCALAPPDATA%\Dielify\settings.json`
- Credentials: `%LOCALAPPDATA%\Dielify\credentials\<profile>.dpapi` (DPAPI, current
  Windows user only)
- Music: `<library_root>\<profile>\<Artist>\<Album>\<NN Title>.<ext>`
- Database: `%LOCALAPPDATA%\Dielify\dielify.db` (tracks keyed by profile + path relative
  to the profile folder, so moving `library_root` keeps play counts and stars)
- Server logins: `%LOCALAPPDATA%\Dielify\server_users\<name>.dpapi`

## Phases

| # | Phase | Acceptance | Status |
|---|---|---|---|
| 1 | Server core (CLI) | CLI run produces a tagged audio file that plays in VLC with no internet | **Done** 2026-11-07 (Josh confirmed VLC offline playback) |
| 2 | Library + Subsonic API | Symfonium/Ultrasonic on the home network browses and plays | **Done** 2026-11-07 (Josh played a track in Symfonium over home Wi-Fi) |
| 3 | Discovery + request endpoints | Test client discovers, requests, watches progress, plays | **Done** 2026-11-07 (Josh's acceptance run: PASS) |
| 4 | Desktop GUI + Windows integration | Non-technical user installs, signs in, plays offline, no terminal | **In progress** — app works (Josh tested); installer + updater next |
| 5 | Secure remote access | Phone plays over mobile data, no router ports open | Not started |
| 6 | Android app | Find, request and listen on the road | Not started |
| 7 | Polish + multi-user install | Second PC, second profile, backups | Not started |

## Current status

**Phase 1 — done** (7 Nov 2026), on Josh's PC:
- Verified live: sign-in (profile `josh`, DPAPI), search, and download of
  `BaxnrepwXck` (Queen — Under Pressure) to `E:\Music\ymp\josh\Queen\Hot Space\`
  as 252 kbps Opus with title/artist/album/year/track/video-id tags and cover art.
- `pytest`: 35 pass on Windows, including a real DPAPI round-trip.
- Acceptance passed: Josh played the file in VLC with the network off, tags and
  cover art shown.

**Phase 2 — done** (7 Nov 2026):
- Built: library index + `dielify library scan`, auto-index after download, Subsonic
  API (browse, folders, search3 incl. empty-query full sync, album lists, stream
  with Range, cover art with resize, star, scrobble), server users, lockout,
  `dielify serve` (also logs to `%LOCALAPPDATA%\Dielify\logs\server.log`: each Subsonic
  call with its parameters, never p/t/s/apiKey). 52 tests pass.
- Verified live: a scripted client on the LAN address (192.168.1.249:4747) pinged,
  browsed, searched, streamed the full file, seeked (HTTP 206) and got cover art;
  wrong password rejected; server listened on 127.0.0.1 + 192.168.1.249 only; log
  showed no tokens.
- Security finding: Josh's Ethernet is categorised **Public**, and Windows'
  firewall prompt created "python.exe" allow rules for Public, any port. README
  Phase 2 step 1 has Josh switch to Private, remove those, and add a port-4747,
  Private-only rule (admin; Claude must not change firewall settings).
- Firewall fixed by Josh and verified: Ethernet is Private, python.exe Public rules
  removed, only "dielify server (private networks)" (TCP 4747, Private) remains.
- Acceptance passed: Symfonium (Subsonic API 1.13.0) synced via search3, streamed,
  fetched cover art and scrobbled; no failed or unimplemented calls in the log.
  It also called getAlbumInfo2, getArtistInfo2, getGenres, getBookmarks,
  getPlaylists (all answered empty for now).

**Phase 3 — done** (7 Nov 2026):
- Built: adapter discovery (home, similar = radio, charts = chart playlists + artists,
  typed search, album, playlist) normalised to `YTItem`; download queue; device-token
  auth (sha256-hashed, per device, revocable, die with the user); /api endpoints;
  `tools/acceptance_phase3.py`. 67 tests pass.
- Live run (127.0.0.1:4748, temp user, real YouTube): discovered "Somebody To Love"
  via Under Pressure's radio, requested, progress, done, streamed + Range. PASS.
- Found during it: Josh's saved sign-in had gone stale (normal-window cookies), so
  that download silently came out at 126 kbps Opus (itag 251) instead of Premium.
  Fixed: queue holds jobs until the sign-in works; README now says Incognito.
- Also fixed: Ctrl+C hung `dielify serve` while a paused phone held a stream open;
  graceful shutdown now caps at 3 s (`timeout_graceful_shutdown`).
- Acceptance passed (Josh, after Incognito sign-in): personalised home feed
  ("Listen again", "Mixed for you"), discovered "Loser" (Tame Impala), queued →
  downloading → processing → done, 264 kbps Opus (Premium), streamed + seek.
- Still at standard quality: track 2 "Somebody To Love" (poobWJNbucs, 126 kbps).
  Fix: `dielify download poobWJNbucs --overwrite`.

**Phase 4 — in progress** (started 7 Nov 2026, branch `phase-4`):
- Built and tested by Josh ("All worked"): `dielify-desktop` window + tray + built-in
  server; library/player/discover/downloads/settings screens; in-window YouTube
  sign-in with a "Use this account" bar; offline mode; start with Windows; profiles;
  phone logins. 75 tests pass.
- Josh decided: updates from GitHub Releases, no paid code-signing certificate for
  now, Inno Setup installed (6.7.3, per-user).
- Built: `packaging\build.py` (PyInstaller one-folder: Dielify.exe + dielify-cli.exe,
  then Inno Setup -> dist\Dielify-setup-<ver>.exe, ~172 MB with FFmpeg + Deno in
  {app}\bin). Silent install/uninstall tested OK, data kept. Version is 0.4.0.
  Found + fixed in source (not yet rebuilt): Dielify.exe vs dielify.exe clash.
- Updater wired up and tested (`updater.py`, Settings → About → Updates); releases
  via `tools\release.py` to github.com/dielman/dielify-releases (gh signed in as
  dielman; signing key in %LOCALAPPDATA%\Dielify-release, backed up by Josh).
  Published 0.4.0; 0.4.2 is the first one installed copies should update to.
- Josh installed the app on his PC (route B, not Windows Sandbox). Found and fixed:
  1. 500s on every screen after in-app sign-in: cause never captured (windowed app
     discarded uvicorn errors). Now logged: uvicorn loggers -> server.log, request
     crashes logged, stderr -> logs\desktop.log.
  2. Sign-in went stale: sign-in window shared the main window's cookie store, whose
     music.youtube.com image loads rotated the cookies. Now sign-in runs in its own
     process with a private (in-memory) profile; main window clears cookies on load.
  3. Queue hammered YouTube (~1 sign-in check/s with 71 waiting): now one check per
     SIGNIN_WAIT_S (300 s) per profile; new requests join the pause.
  4. Downloads screen looked dead (newest-first list): now Now / Waiting in line (in
     download order, positions + ETA from recent pace) / Finished.
- Known: some music *videos* fail with "Track ... not found" (get_track uses the
  watch playlist); fix next. Remaining for Phase 4: Josh's clean no-terminal install
  test (Windows Sandbox suggested) and the first in-app update (0.4.1 -> 0.4.2).
- Size note: each update re-downloads ~172 MB (FFmpeg full build is 217 MB per exe);
  a slimmer FFmpeg build would need Josh's OK to download.

## Open questions for Josh

- Default audio quality/format (currently `auto`: best available, ~256k Opus with
  Premium)
- Auto-download while streaming, or on demand only
- Default cache size limit and eviction behaviour (setting exists, not enforced yet)
- Daughter's install: shared library or fully separate
- Wake-on-LAN wanted?

## Decisions log

- 2026-11-07: Working name `dielify`. Browser-header auth chosen over OAuth (see above).
  Pillow added as a dependency to square-crop non-square video thumbnails for cover
  art. Credentials refuse to save unencrypted on non-Windows unless the explicit
  dev-only env var `DIELIFY_INSECURE_DEV_STORE=1` is set (used by tests).
- 2026-11-07 (Phase 2): FastAPI 0.162 / Uvicorn 0.54 / Starlette 1.10 on Python 3.15.
  Subsonic passwords are random, dielify-generated and DPAPI-encrypted (token auth
  needs the plaintext, so hashing isn't possible). No transcoding: stream always
  sends the original file. Port 4747. IDs are typed strings (ar-/al-/tr-).
  Unsupported features (playlists, genres, lyrics...) return valid empty results.
- 2026-11-07 (Phase 3): Our API uses per-device bearer tokens (`dielify_` + 32 random
  bytes, stored as sha256) from POST /api/auth/login with the server user's password.
  Settings PUT allows quality/format/cache only; library_root is PC-only. Any server
  user may change settings (roles could come in Phase 7). Downloads are one at a time.
  /api/docs and /api/openapi.json are public on the LAN (they hold no data).
- 2026-11-07 (Phase 4): Josh chose a **real installer with an updater** in Phase 4.
  Sign-in: Josh rejected a hidden/headless Chrome capture ("super suspect"). Chosen:
  sign in inside Dielify's own WebView2 window and read cookies from it (Google allowed
  it, verified with Josh's account; tools/signin_window_test.py). Facts found: in
  Chrome 157 merely opening --remote-debugging-port sets navigator.webdriver=true.
  The desktop window holds a per-launch key (memory only, passed in the URL fragment);
  media URLs accept ?token= because <audio>/<img> can't send headers. UI uses
  textContent only + a strict CSP. Never put an object holding the window on the
  pywebview js_api object under a public name: pywebview walks it recursively and hangs.
- 2026-11-07: **Renamed `ymp` → Dielify** (Josh). Package `dielify`, commands `dielify` and
  `dielify-desktop`, data folder `%LOCALAPPDATA%\Dielify`, DB `dielify.db`, tags
  `DIELIFY_VIDEOID` / `----:com.dielify:videoId`, token prefixes `dielify_`. Old data is
  carried over on first run: the old `%LOCALAPPDATA%\` + `ymp` folder and `ymp.db` are
  renamed, DPAPI files saved with the old entropy prefix are re-saved, old tags are still
  read (verified on Josh's PC: 17 tracks, YouTube and phone logins intact). Kept as-is:
  Josh's music folder `E:\Music\ymp`, the project folder `E:\Legit\Code\` + `ymp`, and
  his firewall rule, still named "`ymp` server (private networks)" (works the same).
- 2026-11-07: Default `auto` keeps the Premium Opus stream (itag 774) over 256k AAC:
  same quality class, no re-encode. Josh can set `preferred_format m4a` for AAC.
