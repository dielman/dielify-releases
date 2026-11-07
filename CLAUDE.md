# CLAUDE.md — working notes for Claude sessions

Read this first in every session. Keep it current: update **Current status** at the
end of each working session and record any new decision under **Decisions log**.

## What this project is

A self-hosted YouTube Music system for Josh's Windows 11 PC. It signs in to YouTube
Music (Premium), searches and discovers music, downloads audio to a configurable
local folder with full tags and cover art, plays it offline, and serves the library
over LAN and Tailscale to a custom native Android app. Multi-user: each person has
their own profile, library folder and YouTube login. Working name: **ymp** (Josh to
choose the final name).

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

## Architecture

```
Android app (Kotlin) --Tailscale / LAN--> Server (Python, FastAPI)       [Phase 2+]
Desktop GUI (web UI in native window) --> Server (same engine)           [Phase 4]

src/ymp/
  yt_adapter.py   ytmusicapi + yt-dlp behind ONE interface. The only module that
                  imports them. When YouTube breaks something, fix it here.
  downloader.py   fetch -> tag -> move into Artist/Album/Track. (Queue/retries: Ph.3)
  tagging.py      mutagen tags + embedded cover art for m4a / opus / mp3 / flac
  credstore.py    per-profile YouTube credentials, encrypted with Windows DPAPI
  settings.py     JSON settings: library root, quality, format, cache limit
  paths.py        app data dirs + Windows-safe filename handling
  cli.py          `ymp` command (Phase 1 user interface)
  # planned: library.py (SQLite), subsonic_api.py, custom_api.py, auth.py
```

### Key technical facts (verified 7 Nov 2026)

- **YouTube sign-in:** ytmusicapi *browser-header* auth (paste request headers from
  DevTools). Google removed ytmusicapi's shared OAuth client in Nov 2024; OAuth now
  needs a personal Google Cloud client and gives no cookies for stream access, so we
  do not use it. Browser cookies expire after some weeks — the app must detect a
  dead login and prompt to sign in again.
- **yt-dlp needs a JavaScript runtime for YouTube** (since 2025.11.12). Deno is the
  default and recommended: `winget install --id=DenoLand.Deno`. `ymp doctor` checks.
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
- **Custom tag `YMP_VIDEOID`** (m4a: `----:com.ymp:videoId`) in every file so the
  Phase 2 library index can map files back to YouTube.

### Data locations (Windows)

- Settings: `%LOCALAPPDATA%\ymp\settings.json`
- Credentials: `%LOCALAPPDATA%\ymp\credentials\<profile>.dpapi` (DPAPI, current
  Windows user only)
- Music: `<library_root>\<profile>\<Artist>\<Album>\<NN Title>.<ext>`
- Database (Phase 2): `%LOCALAPPDATA%\ymp\ymp.db`

## Phases

| # | Phase | Acceptance | Status |
|---|---|---|---|
| 1 | Server core (CLI) | CLI run produces a tagged audio file that plays in VLC with no internet | **Done** 2026-11-07 (Josh confirmed VLC offline playback) |
| 2 | Library + Subsonic API | Symfonium/Ultrasonic on the home network browses and plays | Next — waiting for Josh's go-ahead |
| 3 | Discovery + request endpoints | Test client discovers, requests, watches progress, plays | Not started |
| 4 | Desktop GUI + Windows integration | Non-technical user installs, signs in, plays offline, no terminal | Not started |
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
- Next: Phase 2 (SQLite library + Subsonic API). Do not start until Josh says go.

## Open questions for Josh

- Default audio quality/format (currently `auto`: best available, ~256k Opus with
  Premium)
- Auto-download while streaming, or on demand only
- Default cache size limit and eviction behaviour (setting exists, not enforced yet)
- Daughter's install: shared library or fully separate
- Wake-on-LAN wanted?
- Project name

## Decisions log

- 2026-11-07: Working name `ymp`. Browser-header auth chosen over OAuth (see above).
  Pillow added as a dependency to square-crop non-square video thumbnails for cover
  art. Credentials refuse to save unencrypted on non-Windows unless the explicit
  dev-only env var `YMP_INSECURE_DEV_STORE=1` is set (used by tests).
- 2026-11-07: Default `auto` keeps the Premium Opus stream (itag 774) over 256k AAC:
  same quality class, no re-encode. Josh can set `preferred_format m4a` for AAC.
