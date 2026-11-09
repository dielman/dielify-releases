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
  remote.py       /api/remote WebSocket: devices of one profile see + control each other
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
| 4 | Desktop GUI + Windows integration | Non-technical user installs, signs in, plays offline, no terminal | **Done** 2026-11-07 — 0.4.3 installed + working on Josh's PC; clean-PC test waived by Josh |
| 5 | Secure remote access | Phone plays over mobile data, no router ports open | **Done** 2026-11-07 (Josh played in Symfonium over mobile data via Tailscale) |
| 6 | Android app | Find, request and listen on the road | **Done** 2026-11-08 — closed by Josh before the car test ("assume it works"); Android Auto untested |
| 7 | Polish (scope set by Josh 8 Nov) | Backups to E:, signed phone release with in-app updates, download-next, playlists, music-video fix | **Done** 2026-11-08 — 0.6.0 published; phone self-update to be confirmed with the first Phase 8 release (Josh) |
| 8 | Listening features (Josh, 8 Nov) | 1 instant play + download, 2 play history + stats, 4 two-way playlist sync, 3 Dielify-made genre/vibe playlists, 5 outside discovery, 6 remote control between devices | In progress (branch `phase-8`) |
| 9 | Road to 1.0 (Josh, 9 Nov) | Releases 0.9.1-0.9.9 in `docs/ROADMAP.md`: household + kids accounts first, then discovery, library, sound, phone, together, hardening | In progress: 0.9.9 published |

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
  dielman; signing key now in E:\Legit\Code\dielify-release-keys, see Phase 7).
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

**Phase 6 — in progress** (started 8 Nov 2026, branch `phase-6`):
- Toolchain: Android Studio (JBR = Java 25) at C:\Program Files\Android\Android Studio,
  SDK at `E:\Android\Sdk` (kept off AppData on purpose), Gradle 9.9.0 wrapper, AGP 9.5.1,
  Kotlin 2.4.21, Compose BOM 2026.09.00, Media3 1.11.1, OkHttp 5, Coil 3. compile/target
  SDK 37, minSdk 29. Build from Claude's shell:
  `JAVA_HOME="/c/Program Files/Android/Android Studio/jbr" ./gradlew assembleDebug` in
  `android/`, install with `E:\Android\Sdk\platform-toolsdb.exe install -r ...`.
  Josh's Pixel 9 Pro (Android 17) is authorised for USB debugging.
- Step 1 done (Josh: "It plays"): sign in with a phone login (device token encrypted by
  the Android Keystore, backups off), auto-pick home vs Tailscale address via
  /api/health, library albums/artists/recent/search, streaming via `dielify://server/...`
  URIs resolved at fetch time, background playback + lock-screen controls (Media3).
- **Android 17 fact:** apps targeting SDK 37 need the runtime permission
  `ACCESS_LOCAL_NETWORK` (shown as "Nearby devices") to reach LAN addresses; without it
  connections fail silently. Symfonium (older target) isn't affected.
- Step 2 done (Josh: "It worked"): bottom tabs; Discover (home feed + charts), YouTube
  search, tap-to-download, album/playlist "download missing", similar songs, live queue.
- Step 3 built (0aab1f3): "Save on phone" (WorkManager; files in app-private
  filesDir/saved + index.json); player and covers use the phone copy first; Library
  "On phone" tab, shown automatically when the PC can't be reached. Saving verified on
  the Pixel; offline playback not yet tested by Josh.
- Step 3 done (Josh: "It plays offline").
- Step 4 built: PlaybackService is a MediaLibraryService (browse tree Recently added /
  Albums / On this phone; a song tapped in the car plays on through its album);
  ArtProvider serves covers as content://com.dielify.app.art/{track|album}/<id> (saved
  cover, else fetched once into cacheDir/art). Sideloaded apps only show in Android Auto
  with AA developer settings > "Unknown sources" ticked. Not yet tested in a car.
- Closed 8 Nov 2026 by Josh ("lets assume it works and progress, any issues arising later
  we can fix"). He turned on Android Auto "Unknown sources". Not verified: Android Auto
  in a car, and the full "request a new song and hear it on the road" run.

**Phase 7 — in progress** (started 8 Nov 2026, branch `phase-7`; scope in Decisions log):
- Built (0.6.0, all tests pass: 105): download next (`downloads.priority` = ms when marked
  next, 0 = normal; phone song taps default to next; Move up on PC + phone);
  music videos missing from YouTube Music's catalogue fall back to the video's own
  details (`get_song`, title split "Artist - Title"); Library > Playlists (your YouTube
  Music playlists, `/api/yt/my-playlists`); backups (`backup.py`: daily zip of db +
  settings + DPAPI login files, keep 14, Settings > Backups, `dielify-cli backup
  now|restore`, restore takes a non-pruning safety copy first).
- Phone release: `tools/release.py android-keygen|android-export-key|android-import-key|
  android-build`; keystore + DPAPI'd password in `E:\Legit\Code\dielify-release-keys` (beside the
  repo, not in it). Both release keys were first made under %LOCALAPPDATA% from Claude's
  shell, i.e. only in the redirected copy, invisible to Josh's terminals; moved 8 Nov
  (`release.py check-keys` unlocks both from Josh's own terminal too). Release build 4 MB (R8), test builds are
  `com.dielify.app.debug`. App checks the GitHub manifest's "android" entry daily,
  verifies SHA-256, hands the APK to Android's installer. `publish` uploads the APK too.
- 8 Nov: Josh installed PC 0.6.0 and the signed phone app (old test build uninstalled),
  "everything's working so far". Published v0.6.0 to dielman/dielify-releases (Josh's OK;
  installer + APK + signed manifest with "android" entry, verified online). Not yet: an
  end-to-end phone in-app update (needs a later release, e.g. 0.6.1).

**Phase 8 — in progress** (started 8 Nov 2026, branch `phase-8`):
- Item 1 built and published as **v0.7.0**: instant play. `GET /api/yt/stream/{video_id}`
  (media auth): yt-dlp `stream_info` (Premium cookies, same format rule as downloads),
  waits for the format's `available_at` (YouTube 403s before it; yt-dlp also sleeps),
  relays with Range, caches the address 30 min, re-resolves once on 403/410; the first
  request queues the download next in line; library songs are served from the file.
  Phone: song taps play the list from that song (`yt-<videoId>` media ids); PC app the
  same. First play ~7 s (lookup + wait), seeks ~0.1 s. **Confirmed by Josh** ("instant
  play worked"): phone self-updated 0.6.0 -> 0.7.0 in-app (Play Protect scan prompt is
  expected for sideloaded apps), PC updated via its updater (first check hit a dead
  pooled connection, ConnectionResetError 10054; fixed in 3623778 with retrying
  sessions). Real queue checked read-only via a run_in_terminal tab (sees real AppData):
  "Champion" requested by `pixel`, marked next, downloaded first try; ~265-294 songs/hour.
  Only failure in the queue: an old Riptide VEVO video (#48, from before the 0.6.0 fix).
- Item 2 built and published as **v0.8.0**: play history (`plays` table in library.py
  SCHEMA, `history.py`; counts after half the song or 240 s, skips kept, grouped by
  video id; client_id makes resends safe), `POST /api/plays` (batch), `GET /api/stats`,
  `GET /api/discover/for-you` (on repeat / forgotten favourites / more like your top
  songs via YT radio of the top seeds). Subsonic scrobbles and /played feed it. Phone:
  PlayReporter (pending_plays.json, flushed on start and after each play), Stats screen
  (top-bar Insights icon), For-you shelves on Discover. PC: Stats tab, heard-time
  reporting, For-you shelves. History starts at 0.8.0 (old plays are counts only).
  Not yet confirmed by Josh on device.
- 0.7.0 -> 0.8.0 automatic PC update did NOT install (Josh installed dist\ by hand).
  Cause (reproduced with a test installer): the app starts the silent installer, then
  quits 1.5 s later; Inno's AppMutex check found Dielify still open and, with
  /SUPPRESSMSGBOXES, defaulted to Cancel -> exit 1 in 0.5 s. Fix (in the installer, so
  it applies when updating FROM any version): [Code] InitializeSetup waits up to 60 s
  for the mutex when silent; updater passes /LOG=updates\install.log. First proof will
  be the next PC update (0.8.0 -> next).
- Item 4 built (0.8.1): two-way playlist sync. `playlists.py` (+ tables playlists /
  playlist_items / playlist_ops in library.py), `playlist_api.py` (/api/playlists...),
  adapter write calls (create/add/remove/rename/delete, playlist_entries with
  setVideoId). YouTube is master for synced lists: Dielify edits go out at once or wait in
  playlist_ops; sync every 20 min + "Sync now" pushes waiting edits then takes YouTube's
  list (+ waiting adds); new songs download; removing on a synced list / deleting on
  YouTube needs on_youtube=true (apps ask first). Liked Music (LM) is one-way. No reorder
  yet. Subsonic getPlaylists/getPlaylist (library songs only). Phone: Library >
  Playlists (yours + "on YouTube, not synced" with Sync), playlist page, Add to playlist
  (song menus + Now playing). PC: same + "+ Playlist" buttons + player-bar ＋. Tested
  with a fake YouTube (tests/test_playlists.py). Published as **v0.8.1**. **Confirmed by
  Josh** ("both work"): the PC updated 0.8.0 -> 0.8.1 by itself and restarted (the
  installer mutex-wait fix works), and playlist sync works with his real YouTube account.
- Item 3 built (0.8.2): Dielify mixes. `tags.py`: artist genres from MusicBrainz (search
  `artist:"x" OR alias:"x"`, exact name/alias match required: plain top hit gave a
  "Kanye West Tribute Band"; Kanye is "Ye" with alias; 1 req/1.1 s, backs off on 503,
  artist_tags cached 90 days; only artist names leave the PC). `mixes.py`: weekly
  read-only playlists (kind=mix, stable ids per mix_key): up to 6 genres (>=15 songs,
  <60% overlap), 3 decades, vibes Chill / High energy / Feel good guessed from genre
  words; play-weighted weekly sample of 50 + up to 10 new finds (YouTube similar) in
  genre mixes. MixMaker: every 30 min tags up to 300 artists, builds once >=80% looked
  up, rebuilds weekly. GET /api/mixes, POST /api/mixes/refresh. Apps: "Made for you"
  on Discover, "Dielify mixes" in Library > Playlists. Also fixed: settings.json save
  retries when Windows briefly locks it (intermittent Access denied). Published
  **v0.8.2**. On Josh's PC it stopped at 300 artists: tag_some had limit=300 and the loop
  waits 30 min, and his library has 1,084 album artists (so ~2 h to the 80% needed).
  0.8.3 (published): looks up the whole library in one pass (~20-25 min at 1/s), then
  builds mixes. **Confirmed by Josh** ("Mixes look good").
- Item 5 built (0.8.4): outside discovery. `discovery.py`: ABC public plays API
  (music.abcradio.net.au/api/v1/plays/search.json, station triplej / doublej / unearthed,
  from/to + offset paging, ~2,300-3,000 plays a week each; there is no charts endpoint)
  counted into "most played this week"; ListenBrainz sitewide recordings (week, max 2
  per artist: BTS filled the top); ListenBrainz labs similar-artists (algorithm string in
  LB_ALGORITHM) for the top 3 played artists with MusicBrainz ids -> artists not in the
  library -> 2 YouTube songs each. Matches cached 30 days in ext_matches (artist must
  match); lists in discovery_lists, rebuilt daily (first run 3 min after start). Live
  trial: triple j top 8 all matched correctly. GET /api/discover/outside (+ /refresh).
  Apps: "From around the web" section in Discover.
  Published **v0.8.4** (8 Nov). Removed from Discover in 0.8.9 at Josh's request.
- Bug/feature from Josh's bike ride (lost reception, nothing on the phone): 0.8.5 keeps
  streamed songs in a phone cache (`SongCache`: Media3 SimpleCache in cacheDir/songs,
  500 MB LRU, keyed by the dielify://server/... URI so cached songs play with no
  connection; the PC address is only resolved on a cache miss) and `Prefetcher` fetches
  the next 5 songs in play order (shuffle-aware, saved songs skipped, retry every 20 s).
  The player also buffers 15 min ahead, so the current song is fully read at once.
  Prefetching a YouTube song also asks the PC to download it (same as playing it).
  Shown in phone Settings ("Kept from streaming"). Published **v0.8.5** (8 Nov). **Confirmed by Josh** ("all working"): PC log showed the playing song + next 5 fetched within 75 s, then quiet; played in flight mode.
- Idea for later: pre-resolve the next song in a list so skipping feels instant (the
  0.8.5 prefetch now covers this for the phone).

- Item 6 built (0.8.6): remote control. `remote.py` hub (in memory, per profile; hello /
  state / command / transfer; songs = track_id or video_id; queue capped at 1,000; server
  extrapolates positions). PC: player-bar 📱 Devices panel (control, volume, seek, "Play
  it here", "Move my music to X"); PC is named after the computer (platform.node()).
  Phone: `RemoteClient` (OkHttp WebSocket, connected while PlaybackService runs = app
  open, playing, or recently paused), Devices screen from the top bar. Tested: 4 server
  tests; PC panel live in the browser against a fake phone (pause, next, play here, move
  there). Published **v0.8.6** (8 Nov). Not yet: phone on a device. Step 2 (phone lock screen controls the PC) not built.

- 0.8.6 was a separate control panel; Josh: "shithouse", he'd asked for Spotify Connect
  from the start. Rebuilt in 0.8.7 as Spotify Connect: the server keeps one **active
  device** per profile (whoever starts playing; the one before is paused; "select" moves
  the music; gone when it disconnects; apps ignore it after 10 min paused, `idle_s`).
  Every player bar shows and controls the active device, songs tapped anywhere play
  there, green "Playing on X" strip, speaker button opens a short "Play on" list.
  Phone: `RemoteDevicePlayer` (Media3 SimpleBasePlayer for the other device) is swapped
  into the media session while another device is active, so the app screens,
  notification, lock screen and headset buttons control the PC (= step 2). Tested: 5
  server tests; PC bar + picker live against a fake phone. Published **v0.8.7** (8 Nov). Not yet on Josh's devices.

- 0.8.7 bug (Josh: "music plays for approx 1 second and pauses, no matter how its
  played"): race in the hub. The device told to pause often had a "playing" report
  already in flight; the hub took it as a new start, made it active again and paused the
  device that had just taken over (then the late pause stopped the other: silence).
  Reproduced in test_stale_playing_report_after_a_pause_is_ignored. Fix (0.8.8): hub
  remembers each pause it sends (`told_pause_at`) and ignores "playing" reports from that
  device until it reports paused or PAUSE_GRACE_S (3 s) pass. dielify.remote now logs
  at INFO (moves, commands, connects) to server.log. Published **v0.8.8** (8 Nov).
- Still pausing on 0.8.8 (Josh: "if im on the phone and i play a song on the pc, its
  less than a second before the pause"). The new remote log showed the PHONE sending
  "Pixel 9 Pro -> Gamerig: pause" 0.05-0.5 s after each start/play. Not app code (only
  the play button pauses): Media3 pauses only for controller requests, so something
  outside the app (likely earbuds/watch auto-pause, via the platform session) paused the
  session's RemoteDevicePlayer. 0.8.9: Callback.onPlayerCommandRequest accepts
  play/pause/stop for the remote player only from this app, System UI and Android Auto,
  and every request is logged on the PC ("Remote: Pixel 9 Pro says: ... from <package>").
  Josh: "headphones on my phone shouldnt cause the pc audio to break". Also
  Callback.onMediaButtonEvent: while the session shows another device, every hardware /
  Bluetooth media button (incl. earbud auto-pause) is ignored; only the media
  notification's own buttons pass. Headphones still control music playing on the phone.
  Not yet confirmed on device.
- 0.8.9 also (Josh, 8 Nov): "From around the web" removed from Discover in both apps
  ("i wanted playlists not a fucktonne of single songs"); the daily Discovery thread is
  no longer started (discovery.py and /api/discover/outside kept). Downloads: "Clear
  finished" (POST /api/downloads/clear-finished) removes done + cancelled rows (songs
  stay in the library; failed rows stay). Published **v0.8.9** (8 Nov).
- "Nothing loading" on Discover (8 Nov, PC on 0.8.9): opening a YouTube mix (id "RD...")
  asked ytmusicapi for 5,000 songs; mixes never end, so ~50 paced pages = 97 s, and every
  other YouTube call (one at a time per profile) waited behind it (home 34 s, For you
  41 s). Fix 0.8.10: `playlist()` caps RD ids at MIX_LIMIT = 100. Lesson: I first assumed
  the PC was still on 0.8.8 from the install log; Josh had installed 0.8.9 by hand. Ask
  which version is running instead of inferring it. Published **v0.8.10** (8 Nov).
- GitHub's australiaeast edge returned 504 for .../releases/download/*/manifest.json (all
  versions; APK, .sig and the API asset route were fine) on 8 Nov evening, so the phone's
  update check failed. The APK can be installed from the release page in the phone's
  browser meanwhile. Idea offered: fall back to the API asset route.
- Seen in Josh's real server.log since 7 Nov (not new, everything still works): "Can't
  read the YouTube sign-in of josh: DPAPI decrypt failed (Windows error 13)" from
  desktop_api, several times an hour. Not investigated yet.

**Phase 9 — in progress** (started 9 Nov 2026, branch `phase-8` for now; plan in docs/ROADMAP.md):
- **Published v0.9.1** (9 Nov; not yet confirmed by Josh): household foundations, no visible change, 146 tests:
  tables `people` (profile COLLATE NOCASE, role parent|child, store), `library_items` (per-person
  song list: added_at/by, play_count, last_played, starred_at, pinned) and `stars` (album/artist).
  tracks.profile = the store's owner (folder); old per-person columns on tracks/albums/artists
  are no longer read. Migration = PRAGMA user_version 1 (`_to_households`), copies the db to
  `dielify-before-0.9.1.db` first (VACUUM INTO). `library_for(profile)` gives a person's
  Library over their store; every caller uses it. remove_track only deletes the file when no
  other library has the song, never for a child. Queue: a song already in the store joins the
  library with no download; people take turns (`_next_job`, ROW_NUMBER per profile + `_served`).
  Trial on a copy of Josh's real db (build/migrate_trial.py, real db read-only): 2,494 songs,
  1,968 albums, 1,253 artists, plays all matched; move 0.04 s. Josh's real db has one profile,
  "Josh". Also fixed: artist page showed "null" after the thumbs (since 0.8.11). Phone app unchanged.

- 0.9.2 built (second person), 149 tests, phone builds, **not published**. Josh: his daughter
  uses her phone at home only (no PC person-switch, no Tailscale for her). PC Settings >
  People: "Add a kids account" (POST /api/desktop/people: role child, store = the PC's
  active profile's store, phone login of the same name; password screen now lists the home
  Wi-Fi and Tailscale addresses), New password, Remove (DELETE /api/desktop/people/{name}:
  logins + library/history/playlists via `library.forget_person`; files stay). Kids
  account: YouTube calls use the store owner's sign-in (`signin_of`, in _YouTube.call and
  the queue's adapter); /discover/home, /discover/charts, /yt/my-playlists return empty;
  playlist import/sync 403, create/delete never touch YouTube; PUT /settings 403.
  GET /api/me (role, household). Household: GET /api/library/household (store songs not in
  your library; stream + cover allowed for preview), POST /api/library/add. PC Library tab
  "Household" and phone Library tab "Household" appear when more than one person shares the
  store. tests/test_kids_accounts.py. Also fixed the test_lyrics race (lyrics saved just
  after "done"). Filters + Kids discovery are 0.9.3: don't hand the phone over before that.

- **Published v0.9.3** (9 Nov; includes 0.9.2; not yet confirmed by Josh). Kids controls + Kids discovery, 157 tests. Was
  published** (0.9.2 wasn't either: Josh chose to go straight on). `kids.py`: Controls
  (table kid_controls, JSON; defaults explicit block, clean versions, word check, auto
  downloads, 50/day, search on, discovery play on, quiet hours off, stats private, picks),
  KidFilter (blocked songs/artists, words in titles + stored lyrics, explicit via yt_flags;
  unmarked songs looked up with a YouTube song search, capped per request; never-checked =
  withheld), Checker thread (checks store songs with no mark while a child blocks explicit).
  YTItem.explicit from ytmusicapi isExplicit (search: songs + albums only; album/playlist
  tracks yes; watch-playlist radio no). `custom_api._items` filters for children (lookups
  per endpoint); /discover/home for a child = `kids_home.shelves` (Picked for you, Your
  favourites, Because you like X, On the PC); quiet hours 403 on library stream + yt
  stream, /api/me.notice. Queue: child requests filtered, daily limit, status "approval"
  (PC Downloads: Allow / No via /api/desktop/approvals), worker re-checks unmarked songs
  and, after downloading, the lyrics (bad words -> out of her library, job failed).
  PC: Settings > People > Controls page (saves on each change), her stats if allowed.
  Phone: approval section in Downloads, quiet-hours banner (Library + Discover), endless
  button hidden when discovery play is off. Not done: remote control parent<->kid,
  approvals on the parent's phone, quiet hours for Subsonic apps.

- **Published v0.9.4** (9 Nov; not yet confirmed by Josh; GitHub's direct download link for manifest.json gave 504 right after publishing, the API asset route gave 200 and the apps fall back to it). Josh: "do some coding" after listing issues; Discovery moved to 0.9.5. 160
  tests, phone builds, PC checked in the browser, **not published**. Fixes the six issues in
  docs/ISSUES-0.9.3.md (see there). Also: a download only starts if it's still queued
  (cancel race), `_YouTube.background` (waits for 3 s without people's calls) for the kids
  Checker; kids.check_soon queues songs a child met for checking first.

- After 0.9.4 (9 Nov, committed, not released): phone Settings scrolls (since 0.9.0 the Keep-on-phone
  playlist list pushed Update off-screen, so the phone can't self-update until this ships); YouTube
  empty answers (JSONDecodeError on the home feed, seen 17:43 in Josh's log) retried once, and
  Discover falls back to the last home feed that loaded. Josh: ship these with 0.9.5 Discovery
  (not a separate fix release). Meanwhile the phone installs 0.9.4 from the release page.
  Also for 0.9.5 (Josh: playlists don't belong in Settings): "Keep on this phone" is a switch on
  each playlist's page (replaces the one-off "Save on phone" there); Settings lists only the kept
  playlists, with switches to stop keeping them.

- **Published v0.9.5** Discovery (9 Nov; Josh: "let me know when 9.5 is live"; 167 tests, PC checked in the browser
  against a dev copy; not yet tried on Josh's devices; tag v0.9.5 on phase-8 code). Includes the three fixes above.
  - Leave out of my taste: `taste.py`, table `taste_out` (song key like ratings, or playlist id = all its
    songs). Applied in history.seeds / on_repeat / forgotten / top_artists, mixes (play count 0), nowmix,
    new releases. Stats still count them. GET/PUT /api/taste. PC: song queue menu + playlist page button +
    Settings panel; phone: song ⋮ menus, playlist menu, Settings.
  - Time-of-day mix: `nowmix.py` (plays ±2 h of now, 0.5^hours, weekday/weekend x1.5, 180 days, stable per
    part of day; >= 15 songs). In GET /api/discover/for-you as `now_mix`; top of Discover in both apps.
  - New releases: `releases.py` + `artists.py`. Watched = follows + top 20 played artists (history.top_artists).
    Channel by exact-name artist search (table yt_artists), page read at most once / 20 h by ReleaseWatcher
    (youtube.background, first run 5 min after start, then every 3 h). artist_releases.first_seen: first look
    = this year's releases count as new; later looks = new. New for you = last 60 days, minus albums already
    in your library. Auto-download (prefs new_releases_auto, off by default, never kids) queues only releases
    found after the first look. Kids: explicit-blocked children see only albums marked not explicit.
    GET /api/discover/new, PUT /api/discover/new/settings, POST /api/discover/new/refresh, GET/PUT /api/follows.
  - Artist About: YouTube description + MusicBrainz url-rels (Website, Wikipedia, socials...; https only),
    table artist_about (30 days). GET /api/artists/about?name=. Subsonic getArtistInfo/2 answer from the cache
    (biography, lastFmUrl, largeImageUrl) and look it up in the background otherwise. Shared MusicBrainz
    client (artists.musicbrainz(), now thread-safe).
  - Fixed: library.connect ran table setup + migrations in parallel threads ("duplicate column name" on a
    new database); now under a process lock.

- After 0.9.5 (9 Nov, committed + pushed, **not released**): the PC froze at 19:29 (health 20-34 s, phone
  "PC not reachable", PC player "play() interrupted"). Cause from the real log: Keep on this phone for
  Bicycle (165 songs) saved all songs at once and each SaveWorker asked for lyrics; every lyrics lookup
  waits for YouTube (one call at a time), so all 40 server threads were stuck. Fixed: lyrics lookups 2 at
  a time (others 503 + Retry-After), /api/health async, thread limit 100; phone saves 2 songs at a time
  and asks for one lyric at a time; PC player ignores AbortError. Also: PRAGMA journal_mode under the
  setup lock ("database is locked" with many threads on a new db). It recovered by itself ~19:34.
- Josh's bug report (9 Nov, also unreleased): New for you never shows singles (albums + EPs only; a single
  shows up as its album once that's out). "More like your top songs" = playlists: YouTube Music's mix of
  each of the top 10 songs (id RDAMVM<videoId>, "<Song> mix"; get_playlist can't open those, so
  yt_adapter.playlist loads them via song_mix = get_watch_playlist radio; checked live: 100 songs). Josh:
  **never shelves of single songs** in discovery. These fixes and the freeze fix ship WITH 0.9.6 Library
  power (feature release numbers are never used for fix-only releases).

- **Published v0.9.6** Library power (9 Nov; 174 tests, PC checked in the browser on a dev copy, phone
  compiles; not yet tried on Josh's devices). Includes every fix since 0.9.5 (above).
  - Smart playlists: `smart.py`, playlists.kind='smart' + playlists.rules (JSON; migration adds the column),
    read-only, songs worked out again when read and older than 5 min (playlists.all_playlists / get call
    smart.refresh_stale). Rules: artist/album/title/genre (text ops), plays/year/length_s (gt/lt/eq),
    last_played/added (within/not_within days), rating (up/down/none); match all/any; sort; limit <= 1000.
    Only songs with a video id. POST /api/playlists/smart, GET/PUT /api/playlists/{id}/rules. PC: rule builder
    (Library > Playlists > Smart playlist, Edit rules on its page); phone shows them (rules edited on the PC).
  - Search by lyrics: FTS5 table lyrics_fts (lyrics.store keeps it; older lyrics indexed on first search),
    GET /api/library/lyrics-search. lyrics.Backfill thread (youtube.background, wait_s 600, one song every
    5 s, first run 10 min after start) fetches lyrics for older songs. PC + phone library search show
    "In the lyrics" with the matching line.
  - Recaps: `recap.py`, GET /api/recap?period=2026|2026-11, GET /api/recap/periods (a year from 1 Dec or once
    over). Only your own. PC: Stats > Recaps; phone: Stats > Recaps chip.

- **Published v0.9.7** Sound + phone extras (9 Nov; 175 tests, phone release build 7 MB; not yet tried
  on Josh's devices). No crossfade (Josh).
  - Equaliser: PC = Web Audio (lowshelf 120 Hz + 5 peaking bands 60/230/910/3600/14000 + highshelf 8 kHz,
    pre-gain = -max boost), built only once it isn't Flat; localStorage "eq". Phone = SoundEq on
    android.media.audiofx.Equalizer for the ExoPlayer audio session, preset curve read off at the phone's
    bands, shifted down by the max boost; prefs "playback" eq_preset/eq_bass/eq_treble. Same 12 presets.
  - Cast: media3-cast 1.11.1 (play-services-cast-framework 22.3.1), DefaultCastOptionsProvider (Default
    Media Receiver) in the manifest, Cast.initialize() in DielifyApp. The session's player is a CastPlayer
    wrapping the ExoPlayer (Spotify-Connect swap still on top). CastLinks converter: dielify://server/<path>
    -> http://<PC home address>:4747/<path>?token=<cast key>; cast keys from POST /api/cast/token
    (auth.create_cast_token: table cast_tokens, hash only, 12 h, only media_session accepts them, die with
    the phone's device token). MIME: library songs audio/ogg, YouTube audio/webm (unverified on a speaker).
    MediaRouteButton in the top bars + Now playing (hidden without Google Play services).
  - Widget: PlayerWidget (RemoteViews, 4x1): cover, title, artist / "Playing on X" / "On a speaker",
    prev/play/next as broadcasts to the running PlaybackService (PlaybackService.current.shownPlayer());
    when the service isn't running every tap opens the app.

- **Published v0.9.8** Together (9 Nov; 179 tests, PC Jam/share checked in the browser on a dev copy;
  not yet tried on Josh's devices).
  - Shared playlists: playlists.shared (+ playlist_items.added_by); playlists._visible: your own + shared
    ones of your household (same store). Only Dielify-only user playlists can be shared; only the owner
    renames / shares / deletes; everyone adds / removes. Kids see only songs their controls allow.
    PUT /api/playlists/{id}/share. PlaylistSummary.shared/owner/mine, PlaylistEntry.added_by.
  - Blend: `blend.py`, prefs "blend" per person; kids need kid_controls.blend (parent, default off).
    Pair = both on: 50 songs (both-play first, then favourites interleaved; weekly seed), kids-filtered when a
    child is in it. Read-only playlists kind='blend', one copy per person (mix_key blend:a|b). Rebuilt weekly
    in MixMaker.run_once, on PUT /api/blend and when a parent changes controls. GET/PUT /api/blend.
  - Jam: `jam.py`, in memory, one per household, ends after 6 h idle or a server restart. /api/jam (GET
    null|jam, POST start, /join, /songs add, DELETE /songs/{id}, /playing host index, /leave, DELETE end).
    With a child in the Jam every add must pass her filter; upcoming songs that don't are taken out when she
    joins (left_out says why). kid_controls.jam (default on). Host app: PC (app.js pollJam/hostJamSync every
    5 s, player.jamHost, reports index in playAt) and phone (playback/JamHost in the service: polls, rebuilds
    the queue after the playing song, reports on transitions). Phone: Jam icon in top bars, JamScreen,
    "Add to Jam" in song menus. Phone Server.send no longer sends a body with GET.

- **Published v0.9.9** Beautification (10 Nov; 178 tests; installer 123 MB, APK 8 MB; not yet confirmed by Josh on
  devices; tag v0.9.9 on phase-8). Josh, 10 Nov: all 27 items; plan in docs/ROADMAP.md. Decisions: font **Inter**
  (Josh OK'd downloading the font files from Google Fonts), phone colours from the **song's cover**
  (not Material You), app icon: "get creative" (draw options for Josh to pick).
  - Stage 1 built (not released): `artwork.py`. Colours per album (table art_colors, key al:<album id>,
    a:<artist key> for photos; palette() = Pillow median-cut: bg dark main colour, accent liveliest,
    fg white; in-memory copy) on Track/Album/Artist (`colors`) and PlaylistSummary (`colors`, `cover_url`).
    Covers always exist: album/track cover endpoints draw one (designed(): gradient from a curated hue set +
    big Segoe UI Bold title) when there's no art. GET /api/playlists/{id}/cover = 2x2 of 4 different album
    covers (1 if fewer), designed for mix/blend/smart. Artist photos: GET /api/library/artists/{id}/image
    (photo file in <data>/artists/, else first album cover); artwork.Worker: colours first (local), then
    photos via artists.photo_url (one artist search each, youtube.background, retried monthly). Subsonic
    getCoverArt ar- uses the photo. Apps don't use the new fields yet (stages 2 and 3).

  - Stage 2 built (PC, not released): index.html + app.css rewritten (tokens, Inter in ui/fonts (OFL), side bar
    with nav icons + your playlists (paintSide), floating search, cover-tinted .hero headers via tintStyle(colors),
    Now playing overlay (openNowPlaying: song colours + embedded lyrics), player bar in 3 zones with a More menu
    (add to playlist / sleep / equaliser / Now playing), Discover banner (discoverHero), Settings sections,
    skeleton(), fade-in only on page change (show: shownKey, "still"), playing bars on the song row, moreButton()
    for rare page actions). Start-up link #t=..&go=<route>[&playing] opens any screen (openRoute). Screenshots:
    build/dev_design.py (test library on :4796) + build/shots.py <label> (headless Chrome; Edge doesn't work
    from Claude's shell) -> docs/design/<label>/, side by side in docs/design/compare/. Keep no other browser tab
    on the test copy while shooting (an old key locks 127.0.0.1 out). Josh: "Looks good, go".
  - Stage 3 built (phone, bb15347, not released): Theme.kt (same tokens as app.css, Inter TTFs in res/font),
    Design.kt (PageHeader on the cover's colours, BigPlay, PlayingBars, SettingsSection, ThinSeek = thin
    white seek bar instead of M3's chunky slider), Now playing + mini player tinted with the song's colours
    (MediaItem extras COLOR_BG/COLOR_ACCENT -> PlayerUi.colorBg/colorAccent; swipe the cover / mini player
    for next/previous), album/artist/playlist/YouTube collection headers, playlist covers + artist photos in
    lists, Discover banner (NowMixShelf), Settings in sections, AnimatedContent page transitions, widget
    restyled. Checked on the emulator (AVD Medium_Phone_API_37.0, headless, signed in to 10.0.2.2:4796);
    screenshots in docs/design/phone/. Josh: "Looks good, go".
  - Stage 4 built (not released): icon = **Wave D** (Josh picked it from 6 options in docs/design/brand/board.png,
    drawn by tools/brand_concepts.py): a D made of 8 sound bars, orange -> coral -> violet, on a dark tile.
    One source: `src/dielify/brand.py` (bars(), svg(), icon_image() via Pillow). tools/make_brand.py writes
    the phone's ic_launcher_{background,foreground,monochrome}.xml (vector + gradient), ui/logo.svg (side bar +
    favicon) and packaging/wizard-{large,small}-{100,200}.bmp (Inno WizardImageFile / WizardSmallImageFile);
    rerun it after changing brand.py. Tray + dielify.ico (build.py) use icon_image. Phone start-up screen:
    values-v31/themes.xml (icon on #0E0F12). Checked: emulator drawer + start-up screen, PC side bar.
  - Stage 5 words pass (not released): every string listed (build/words_extract.py), 37 rewrites applied
    (OK/Cancel dialogs spelt out, "YouTube id" -> "from YouTube Music", raw HTTP errors -> plain "Something went
    wrong on the PC (error N)", "letters and numbers", phone sign-in pointed at the right PC section "People &
    phones", "Download later"). Found + fixed: ui/fonts/inter.css pointed at fonts/fonts/*.woff2 (404), so the PC
    app never showed Inter (stage 2 screenshots were the fallback font).
  - Josh's real server.log (read-only, build/log_load.py + log_window.py via a terminal tab), 10 Nov: health
    instant (the 9 Nov freeze fix holds); Discover home/charts/endless take 15-60 s and some 502. Cause found in
    code: one YouTube call at a time per sign-in, and `_YouTube.background` counts "quiet" from the START of the
    last person's call, so background jobs (lyrics Backfill every 5 s through ~2,500 older songs, release watcher,
    later artwork photos) slip in between people's calls (Lock isn't fair). Josh's PC runs the dist\ installer
    (0.9.8 number, 0.9.9 UI, built 10 Nov 06:09).
  - Josh (10 Nov): **lyrics removed entirely** ("prioritise the music experience, not a side feature") and
    **Discover cached 10 min**. Built (not released): lyrics.py, /api/lyrics, /api/library/lyrics-search, the
    Backfill thread, lyrics at download time, yt_adapter.lyrics, PC lyrics page + mic button + "In the lyrics",
    phone LyricsStore/LyricsSheet/prefetch/search all gone; library._migrate drops tables lyrics + lyrics_fts; the
    phone deletes filesDir/lyrics on start. Kids "Check words" now checks titles only (field still lyrics_check).
    PC Now playing's right half shows Up next instead. custom_api._cached_feed: home + charts kept 10 min
    (FEED_FRESH_S), up to 1 h old shown at once while a fresh copy loads in the background, YouTube 502 -> last
    copy; offline mode bypasses it. _YouTube: background jobs wait while any person's call runs or waits, then
    QUIET_S (3 s) after it ends; person calls over 5 s are logged ("YouTube <fn> for <profile> took N s").

## Backlog (Josh, 8 Nov; after Phase 8 item 6)

- **Published v0.8.11 (9 Nov; not yet confirmed by Josh on device): ratings + ban.** `ratings.py` (table
  `ratings`: profile, kind song|artist, key = video id / tr-<id> / artist_key(name),
  value 1 up / -1 down / -2 ban). GET/PUT /api/ratings. Discovery (home, similar, For
  you) drops banned and moves thumbs-down to the back (`Ratings.arrange`); mixes leave
  banned out and weight picks by FACTOR (up x3, down x0.2). Both players skip banned songs
  in any list (PC playAt/nextPlayable; phone onMediaItemTransition). PC: player-bar
  thumbs (hold thumbs down 0.7 s -> "ban this song / the artist"), artist-page thumbs,
  Settings > Ratings with Unban. Phone: same on Now playing (long press), artist page,
  Settings. Key rule is shared by ratings.py / app.js / Ratings.kt (NFKC, lower, & -> and).
- **Published v0.8.12 (9 Nov; not yet confirmed by Josh): never-ending discovery play.** `explore.py` +
  POST /api/discover/endless {seeds, exclude, count}: new songs (not in the library, no
  ban / thumbs down) from YouTube radio of the songs heard (thumbs-up first; else top
  plays, else random library songs), queued for download (request_type "discovery"),
  remembered in table `explore_songs`. Josh (9 Nov): thumbs down = deleted, thumbs up and
  unrated stay (no expiry). PUT /api/ratings with down/ban on an explore song cancels its
  download / deletes the file (`Library.remove_track`, empty folders go) and returns
  `removed`. Built: only songs this mode brought in are deleted, never ones Josh already
  had (ask Josh if he wants thumbs down to delete any song). Apps top up when <= 3 songs
  are left (PC player.endless; phone EndlessPlay in the playback service); thumbs down
  there also skips. Discover button "Never-ending discovery" on both. Playing on another
  device: that device gets one batch, no top-up.
  Also in 0.8.12 (Josh, 9 Nov): "On repeat" removed from Discover in both apps (YouTube's
  home has its own); PC player bar: icons centred, plain prev/next like the thumbs, only
  Play is a filled circle. **Confirmed by Josh** ("thats all working", 9 Nov).
- **Published v0.8.13 (9 Nov; not yet confirmed by Josh): Up next** (Josh: "should have been a core feature long
  ago"). PC: player-bar queue button opens a panel (now playing + coming songs; click to
  jump, drag to move, Play next, remove, Clear); song rows / album / playlist pages get
  "Play next / Add to queue". Phone: Up next sheet from Now playing (tap to jump, Play
  next, remove, Clear), Play next / Add to queue in song ⋮ menus (YouTube rows and library
  TrackRow). Works on the active device too: new remote action "queue" {queue, index} =
  new list around the playing song (it plays on); phone reports its queue in play order
  (shuffle) and maps "jump" back; phone also handles "jump" now (it ignored it before).
  Phone shuffle: the first queue edit lays the list out in the shuffled order and turns
  shuffle off (otherwise Media3 inserts at random places). No drag-to-move on the phone yet.
- **Published v0.9.0 (9 Nov; not yet confirmed by Josh; Josh: "all of them for a .9 update", 9 Nov):**
  - Lyrics: `lyrics.py` (YouTube Music timed lyrics via get_watch_playlist "lyrics" id ->
    get_lyrics(timestamps=True); else LRCLIB lrclib.net/api/get, only artist/title/album/length
    sent), table `lyrics` (none remembered 14 days), kept at download time (TrackInfo.lyrics_id,
    downloads._fetch_lyrics), GET /api/lyrics. PC: mic button = full-page lyrics, current line
    centred, click a line to seek. Phone: LyricsSheet, LyricsStore (filesDir/lyrics, 3000 max),
    fetched for the current + next 2 songs and for saved songs.
  - Sleep timer: PC moon button (15/30/45/60 min, end of song, 15 s fade); phone SleepTimer in
    DielifyApp, run by PlaybackService (pauseAtEndOfMediaItems; remote device: pause when it
    moves on).
  - Gapless + levelling: PC has two <audio> elements (next song preloaded 25 s before the end,
    swapped on "ended"); phone already gapless (Media3). `leveller.py` measures EBU R128
    loudness with FFmpeg into tracks.loudness (background, below-normal priority; -99 = none);
    Track.gain_db = -14 - LUFS; players only turn loud songs down (volume can't go over 1).
    Setting "Even out volume" (PC localStorage, phone prefs). gain_db travels in remote songs.
  - Keep on phone: GET /api/keep?liked&top&playlists; phone KeepOnPhone/KeepWorker (12 h + on
    change; Wi-Fi only by default); removes only songs it added ("auto" set).
  - Phone Up next: drag handle to move (queueMove).
  - Update downloads fall back to GitHub's API asset link on 5xx / network errors (PC + phone).
  - DPAPI warning explained + fixed: the sign-in file is Josh.dpapi / profile "Josh", the
    music folder is "josh"; _profiles added "josh" and Windows' case-insensitive path opened
    Josh.dpapi with entropy "josh" -> error 13. Profiles now dedupe case-insensitively.
  - Installer drops ffprobe.exe (228 MB; yt-dlp works without it, tested) and deletes the old
    copy. A slimmer FFmpeg (essentials build) would cut more but needs Josh's OK to download.
  - PC player bar: sleep / lyrics / queue / devices grouped; volume hidden under 1050 px.

- **Icons (Josh, 8 Nov: "this looks shit"): built in 0.8.11.** PC song rows are one line
  (tap the title to play; icons for add to playlist / download / ✓ in library / remove),
  inline SVG icons (Material Symbols paths) for the player bar, downloads and big buttons;
  phone's last text-only buttons got icons. Also: /ui files are sent with
  Cache-Control: no-cache (a cached old index.html with a new app.js broke the page in
  testing; would do the same in the WebView after an update).

## Open questions for Josh

- Default audio quality/format (currently `auto`: best available, ~256k Opus with
  Premium)
- Auto-download while streaming, or on demand only
- Default cache size limit and eviction behaviour (setting exists, not enforced yet)
- Where the daughter uses Dielify (her phone / the family PC / her own computer), and
  the kids-controls defaults (docs/ROADMAP.md, 0.9.3)
- Wake-on-LAN wanted?

## Decisions log

- 2026-11-10 (Josh): **no lyrics in Dielify** (removed from server, PC and phone; don't bring them back
  without asking). Discover's YouTube parts are cached for 10 minutes.

- 2026-11-09 (Josh): **the code lives in github.com/dielman/dielify-releases** (remote `origin`,
  PUBLIC), the same repo the releases come from. First push 9 Nov: main (replaced the README-only
  main; release tags untouched) + phase-1-live..phase-8. Push branches there when Josh asks. Josh
  knows it's public (home/Tailscale addresses and household details in CLAUDE.md/README are visible;
  no secrets in the history, checked 9 Nov). Never commit anything private there.

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
- 2026-11-07: **Phase 4 closed by Josh without the formal clean-PC acceptance test**
  ("skip"). Evidence instead: Josh installed 0.4.3 on his own PC, signed in, all screens
  work, downloads run at Premium quality; in-app update 0.4.1 -> 0.4.2 worked. Not
  verified: first install on a clean PC (Windows Sandbox), offline playback in the
  installed app. Do that before giving Dielify to someone else (Phase 7).
- 2026-11-07: Open after Phase 4: playlists in Library / YouTube playlist sync (Josh
  asked); "playlist stops at 100" not reproduced (Bicycle loads 165); faster downloads
  (measure first; optional 2-at-a-time). Josh asked for TorBox downloads: declined
  (torrent/usenet sources = unlicensed copies). Hidden duplicate data under
  `...\Packages\Claude_*\LocalCache\Local\Dielify*` still to clean up with Josh's OK.
- 2026-11-07 (Phase 5): Tailscale: PC `gamerig` 100.73.103.100, phone `pixel-9-pro`
  100.93.251.98, both Private network category; Windows' own "dielify.exe" allow rule
  (Private, any port) covers it, so no extra firewall rule. Dielify re-checks addresses
  every 30 s (AddressWatcher) so a late Tailscale connection is picked up; keep_awake
  setting added. Symfonium's form has separate host/port/HTTP fields: host must be the
  bare IP. Josh's `josh` phone login file couldn't be read by the installed app (root
  cause unknown; DPAPI wrapper made sturdier in 0.5.1); a new `pixel` login works.
  0.5.0/0.5.1 installed from dist\ locally; not published to GitHub yet.
- 2026-11-07: Default `auto` keeps the Premium Opus stream (itag 774) over 256k AAC:
  same quality class, no re-encode. Josh can set `preferred_format m4a` for AAC.
- 2026-11-08 (Phase 7 scope, Josh): multi-user / second PC **not needed yet** (skip). Backups:
  daily copy of database + settings to a folder on E:. Phone app: signed release build with
  in-app updates from the same GitHub releases. Backlog in: download next (phone requests
  jump the queue), YouTube playlists in Library, music-video "Track not found" fix. Not in:
  cache size limit enforcement.
- 2026-11-08 (Phase 8 scope, Josh): order 1 -> 2 -> 4 -> 3 -> 5.
  1. Instant play: any YouTube song plays at once (streamed through the PC with the
     Premium sign-in) and the PC downloads it next in line ("auto-download while
     streaming" = yes, answering the old open question).
  2. Play history (every play: when, device, how much) + stats + recommendations.
  4. Playlist sync: **two-way** (Dielify edits change Josh's YouTube Music playlists).
  3. Dielify-made playlists by genre/vibe; tags from MusicBrainz (free, no account).
  5. Outside discovery: **ListenBrainz** and **radio charts** (e.g. triple j). Not Last.fm
     (Josh didn't pick it), not Spotify (recommendation API closed to new apps).
- 2026-11-08 (Phase 8, Josh): **item 6 added: remote control between devices**
  (Spotify-Connect style), last in the order unless Josh moves it. Every player (PC app,
  phones) keeps a live connection to the server and reports its state; a devices
  button lists the user's own online devices: control (play/pause/skip/seek/volume,
  now playing), "Play on <device>", move playback with queue + position. Step 2: phone
  lock screen/notification controls the PC. No Google push (Firebase): the PC is always
  reachable; the phone while playing, for a while after pausing, and optionally via a
  "Stay reachable" setting (notification + Unrestricted battery). Verify Android 17
  Doze behaviour on Josh's Pixel before promising times. Volume = Dielify's own.
- 2026-11-09 (Josh): **road to 1.0** = `docs/ROADMAP.md` (all 11 competitor features +
  Blend / Jam / shared playlists + multi-user). **Household model:** one shared music
  store (Josh's folder), separate per-person libraries (membership list), parent and child
  profiles. **Child accounts (under 16) are "Dielified":** they use the parent's YouTube
  sign-in behind the scenes but never see anything from his YouTube account (no YouTube
  home feed, charts or his playlists); they get Kids discovery built from Dielify's own
  data, and the parent sets kids controls (explicit / profanity, approvals, search,
  limits...). Child playlists never sync to YouTube. Files are deleted only when no
  library uses them, never by a child.
- 2026-11-09 (Josh): roadmap changed: **0.9.7 = Sound + phone extras** (equaliser, cast, widget; crossfade
  dropped entirely, PC and phone), **0.9.8 = Together** (shared playlists, Blend, Jam), **0.9.9 = Beautification** (making both
  apps pretty; scope drafted in docs/ROADMAP.md, to agree with Josh), 0.9.10 hardening as before.
- 2026-11-08: **Version numbers** (Josh): we're far from 1.0, so releases now count up the
  last number (0.8.1, 0.8.2, ...) instead of the middle one. 0.9.0 was built but never
  published; it went out as 0.8.1.
