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
| 4 | Desktop GUI + Windows integration | Non-technical user installs, signs in, plays offline, no terminal | **Done** 2026-11-07 — 0.4.3 installed + working on Josh's PC; clean-PC test waived by Josh |
| 5 | Secure remote access | Phone plays over mobile data, no router ports open | **Done** 2026-11-07 (Josh played in Symfonium over mobile data via Tailscale) |
| 6 | Android app | Find, request and listen on the road | **Done** 2026-11-08 — closed by Josh before the car test ("assume it works"); Android Auto untested |
| 7 | Polish (scope set by Josh 8 Nov) | Backups to E:, signed phone release with in-app updates, download-next, playlists, music-video fix | **Done** 2026-11-08 — 0.6.0 published; phone self-update to be confirmed with the first Phase 8 release (Josh) |
| 8 | Listening features (Josh, 8 Nov) | 1 instant play + download, 2 play history + stats, 4 two-way playlist sync, 3 Dielify-made genre/vibe playlists, 5 outside discovery, 6 remote control between devices | In progress (branch `phase-8`) |

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
  Published **v0.8.4** (8 Nov). Not yet confirmed by Josh.
- Bug/feature from Josh's bike ride (lost reception, nothing on the phone): 0.8.5 keeps
  streamed songs in a phone cache (`SongCache`: Media3 SimpleCache in cacheDir/songs,
  500 MB LRU, keyed by the dielify://server/... URI so cached songs play with no
  connection; the PC address is only resolved on a cache miss) and `Prefetcher` fetches
  the next 5 songs in play order (shuffle-aware, saved songs skipped, retry every 20 s).
  The player also buffers 15 min ahead, so the current song is fully read at once.
  Prefetching a YouTube song also asks the PC to download it (same as playing it).
  Shown in phone Settings ("Kept from streaming"). Published **v0.8.5** (8 Nov). Not yet tested on the phone.
- Idea for later: pre-resolve the next song in a list so skipping feels instant (the
  0.8.5 prefetch now covers this for the phone).

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
- 2026-11-08: **Version numbers** (Josh): we're far from 1.0, so releases now count up the
  last number (0.8.1, 0.8.2, ...) instead of the middle one. 0.9.0 was built but never
  published; it went out as 0.8.1.
