# YouTube Music Local Player: Project Handoff

*Prepared for Josh, 7 November 2026. Purpose: give a fresh Claude session (ideally Claude Code on a paid plan) everything needed to start building without re-asking decisions already made.*

## 1. One-paragraph summary

A self-hosted music system that runs on Josh's Windows 11 PC. It signs in to YouTube Music (Premium account), lets the user search and discover music, downloads the audio to a configurable local folder with proper tags and cover art, and plays it back offline. The PC also hosts the library on the network (a Subsonic/OpenSubsonic-compatible API plus custom endpoints) for a custom native Android app that handles discovery, search, download requests, and playback, including securely while away from home. It must support multiple users, each with their own YouTube login, so it can be installed on another computer for another person (for example Josh's daughter).

## 2. Decisions already made (do not re-litigate)

- **Terms of service:** Josh has accepted the ToS considerations and will keep his YouTube subscription active. Do not add warnings or refuse on this basis; just build well.
- **Android app:** a **custom native app** (option B). One app for discovery, search, tap-to-download, a download queue, and playback. Not a PWA, not a web page beside a third-party player.
- **Server compatibility:** the server exposes the Subsonic/OpenSubsonic API so existing Android clients (Symfonium, Ultrasonic, DSub) work as a fallback and as a test harness.
- **Remote access:** private encrypted tunnel via **Tailscale**. The server is never exposed directly to the public internet.
- **Platform:** Windows 11 for the PC. Android for the phone.
- **Extensibility:** the design must make later features easy to add (see section 10).
- **Discovery:** Josh recently used an app called Eclipse and liked its discovery. The goal is YouTube Music's own discovery (home feed, mixes, similar tracks, charts) surfaced in our app.

## 3. Functional requirements

1. **Login, per user.** Sign in to YouTube Music with a Premium account. Credentials are stored per user profile so the same software can be installed on another PC for another person.
2. **Stream and cache.** Play from YouTube Music; the audio is downloaded and stored locally.
3. **Configurable storage.** The storage folder is set inside the desktop GUI (folder picker), plus audio quality and a cache size limit.
4. **Offline playback.** Previously downloaded music plays with no internet and without any check-in to YouTube. Offline mode never calls out.
5. **Network hosting.** The library is served on the LAN and over the Tailscale tunnel to the Android app.
6. **Download requests from the phone.** The app can search YouTube Music, request a download, and the PC fetches it and then streams it to the phone.
7. **Phone-side offline saving.** The app can save tracks to the phone for use with no connection to the PC.
8. **Discovery.** Home feed, mixes, similar tracks, and charts, sourced from YouTube Music.
9. **Multi-user.** Separate accounts, libraries, and YouTube logins per user.

## 4. Non-functional requirements

- **Security first for remote use** (section 7).
- **Resilient files.** Every downloaded track has embedded tags and cover art so it works in any player even if this software disappears.
- **Runs unattended.** The server runs as a background service or tray app on Windows and starts with the PC.
- **Fails gracefully.** YouTube-facing libraries break periodically; isolate them behind an adapter so a fix touches one module.
- **Testable.** Each phase has acceptance criteria and can be checked from the command line or an existing Subsonic app before the next phase starts.

## 5. Architecture

```
Android app (Kotlin) --Tailscale / LAN--> Server (Python, FastAPI)
Desktop GUI (web UI in native window) ------> Server (same engine)

Server modules:
  yt_adapter     ytmusicapi + yt-dlp wrapped behind one interface
  downloader     queue, progress, retries, tagging, cover art
  library        SQLite index of tracks, albums, artists, playlists
  subsonic_api   Subsonic/OpenSubsonic compatible endpoints
  custom_api     discovery, YouTube search, download requests, progress
  auth           users, password hashing, per-device tokens
  settings       storage path, quality, cache limit, per-user config
```

### Suggested technology

| Area | Choice |
| --- | --- |
| Server language | Python 3.12 or newer |
| Web framework | FastAPI with Uvicorn |
| YouTube Music data | `ytmusicapi` (search, library, home feed, mixes) |
| Audio fetching | `yt-dlp` with FFmpeg |
| Tagging | `mutagen` (embedded tags and cover art) |
| Database | SQLite |
| Desktop GUI | Web UI served by the engine, shown in a native window (for example `pywebview`) with a tray icon (for example `pystray`) |
| Android app | Kotlin, Jetpack Compose, Media3 (ExoPlayer, MediaSession) |
| Remote access | Tailscale |
| Packaging | PyInstaller or similar for a Windows installer later |

These are recommendations. A fresh session may propose substitutions if it has a good reason, but should explain them first.

### Audio format

Prefer Opus or AAC (m4a) as served by YouTube Music, to avoid re-encoding. Premium offers higher bitrates than free, so quality should be a setting. Keep the original format where possible and only transcode if a client needs it.

## 6. Data and storage

- **Library folder:** user-configurable, one subfolder per user profile, organised as Artist / Album / Track.
- **Database:** SQLite file in an application data folder (not in the music folder), holding track metadata, YouTube video IDs, file paths, play counts, download state, and users.
- **Credentials:** YouTube auth stored per user, encrypted with Windows credential protection (DPAPI) rather than plain text files.
- **Config:** a settings file or table for storage path, quality, cache limit, and server bind address.
- **Cache policy:** configurable size cap with least-recently-played eviction, with a way to pin tracks so they are never evicted.

## 7. Security design

- The server binds only to the Tailscale interface and the local network, never to all interfaces.
- Nothing is exposed to the public internet. No router port forwarding.
- Per-user accounts with strong password hashing (for example Argon2 or bcrypt).
- Per-device tokens for each phone, individually revocable.
- Rate limiting and lockout on failed logins.
- The Subsonic API's standard login scheme is weak by modern standards, so it must only be reachable inside the encrypted tunnel or local network.
- Optional HTTPS inside the tunnel for defence in depth.
- A Windows Firewall rule limited to private networks.
- No secrets in logs. No credentials in the repository.
- The PC must be awake to serve while Josh is away, so sleep and hibernate behaviour should be configurable, with Wake-on-LAN through the tunnel as an optional extra.

## 8. API surface

**Subsonic/OpenSubsonic (for compatibility):** ping, getArtists, getArtist, getAlbum, getAlbumList2, search3, stream, getCoverArt, getPlaylists, getPlaylist, star, unstar, scrobble, and related calls needed by Symfonium, Ultrasonic, and DSub.

**Custom endpoints (our own, authenticated):**

- `GET /api/discover/home`: personalised home feed and mixes
- `GET /api/discover/similar/{track}`: similar tracks
- `GET /api/discover/charts`: charts
- `GET /api/yt/search?q=`: search YouTube Music
- `POST /api/downloads`: request a download (track, album, or playlist)
- `GET /api/downloads`: queue and progress
- `DELETE /api/downloads/{id}`: cancel
- `GET /api/settings` and `PUT /api/settings`: storage path, quality, cache limit
- `POST /api/auth/login`, `POST /api/auth/device-token`, `DELETE /api/auth/device-token/{id}`
- `GET /api/health`: status for the apps and the tray icon

The exact shapes should be defined in an OpenAPI spec generated by FastAPI and kept as the contract for the Android app.

## 9. Build phases and acceptance criteria

### Phase 1: Server core (command line)

Sign in with Josh's account, search for a track, download it to a configurable folder with correct tags and cover art. **Done when:** a command-line run produces a tagged audio file that plays in VLC with no internet.

### Phase 2: Library and Subsonic API

Index downloads in SQLite and serve them over the Subsonic API. **Done when:** Symfonium or Ultrasonic on the phone connects over the home network, browses, and plays downloaded tracks.

### Phase 3: Discovery and request endpoints

Home feed, similar tracks, charts, search, and download requests with progress. **Done when:** a test client can discover a track, request it, watch progress, and then play it from the library.

### Phase 4: Desktop GUI and Windows integration

Settings (folder picker, quality, cache limit), sign-in and user profiles, download queue, offline switch, tray icon, start with Windows. **Done when:** a non-technical user can install, sign in, and play offline without opening a terminal.

### Phase 5: Secure remote access

Tailscale setup, bind rules, firewall rule, device tokens, rate limiting. **Done when:** the phone plays from the PC over mobile data with no router ports open.

### Phase 6: Android app

In order: connect and play; discovery and search; download requests and queue; phone-side offline saving; lock-screen and Android Auto controls. **Done when:** Josh can find a new track in the app, request it, and listen to it on the road.

### Phase 7: Polish and multi-user install

Installer for a second PC, second user profile, and backups of the database and settings.

## 10. Extension ideas (design so these are easy later)

- Auto-download liked songs and chosen playlists
- Playlist sync between the app and YouTube Music
- Lyrics (for example from LRCLIB)
- Scrobbling (ListenBrainz or Last.fm)
- Per-user recommendations and listening stats
- Scheduled discovery downloads (a weekly mix pulled automatically)
- Chromecast, Android Auto, and car mode refinements
- Auto-update checks for `yt-dlp` and `ytmusicapi`, since YouTube changes often

## 11. Known risks

- **Unofficial libraries break.** `ytmusicapi` and `yt-dlp` follow YouTube's changes and occasionally fail until updated. Keep them behind `yt_adapter`, pin versions, and make updating easy.
- **Authentication method.** `ytmusicapi` has supported browser-cookie header authentication; OAuth support has been unreliable. Verify the current recommended method before building the login flow.
- **CGNAT.** Many ISPs block inbound connections, which is a reason to use Tailscale rather than port forwarding.
- **PC availability.** If the PC sleeps or is off, remote access fails. Phone-side offline saving is the safety net.
- **Account safety.** Josh has accepted the ToS risk; keep request rates modest and human-like to avoid unnecessary account attention.

## 12. Setup checklist (Windows 11)

1. Python 3.12 or newer
2. Git
3. FFmpeg on PATH
4. Tailscale on the PC and the phone
5. Android Studio (needed from Phase 6)
6. A phone with developer mode enabled, or an emulator
7. A project folder under version control, with a `.gitignore` that excludes credentials, the database, and the music folder

## 13. Working agreements for the Claude session

- Work phase by phase. Do not start the next phase until the current phase's acceptance criteria are met and Josh confirms.
- Prefer small, runnable steps. After each change, run it and show the result.
- Explain Windows setup steps plainly; Josh is building this project and may not know every tool.
- Keep a `README.md` and a `CLAUDE.md` in the repository recording the decisions in section 2, the architecture, and current phase status, and update them as the project evolves.
- Ask before changing any decision in section 2.
- Flag security concerns directly rather than quietly working around them.

## 14. Open questions for Josh

- Preferred audio quality and format as the default
- Whether downloads should happen automatically while streaming, or only on demand
- Default cache size limit and eviction behaviour
- Whether the daughter's install should share a library with Josh's or stay fully separate
- Whether Wake-on-LAN is wanted for remote use
- Name for the project

## 15. Starter prompt to paste into the new session

> I'm Josh. Attached is the handoff document for a self-hosted YouTube Music player I want to build on my Windows 11 PC, with a custom Android app. Please read it fully, then create the project repository structure, a README.md, and a CLAUDE.md that records the decisions and phases. Then start Phase 1: sign in with my YouTube Music account, search for a track, and download it to a configurable folder with correct tags and cover art. Work in small, runnable steps and show me results as you go. Ask me before changing any decision in section 2.
