# Dielify — self-hosted YouTube Music player

Sign in to YouTube Music, download tracks to your own folder with full tags and cover
art, play them offline, and (in later phases) stream your library to a custom Android
app over your home network or Tailscale.

> The full plan is in [`docs/HANDOFF.md`](docs/HANDOFF.md);
> decisions, architecture and progress are in [`CLAUDE.md`](CLAUDE.md).

## Status

| Phase | What | Status |
|---|---|---|
| 1 | Command line: sign in, search, download with tags + cover art | **Done** (7 Nov 2026) |
| 2 | Library database + Subsonic API (Symfonium/Ultrasonic) | **Done** (7 Nov 2026) |
| 3 | Discovery + download requests | **Done** (7 Nov 2026) |
| 4 | Desktop app, installer and automatic updates | **Done** (7 Nov 2026) |
| 5 | Secure remote access (Tailscale) | **Next** |
| 6 | Android app | |
| 7 | Installer, second user, backups | |

---

## Phase 1 on Windows 11 — step by step

All commands go in **Windows Terminal** (Start menu → "Terminal"). After installing
anything with `winget`, **close and reopen the terminal** so it picks up the new
program.

### 1. Install the tools (one time)

```powershell
winget install -e --id Python.Python.3.13
winget install -e --id Git.Git
winget install -e --id Gyan.FFmpeg
winget install -e --id DenoLand.Deno
```

- **Python** runs Dielify. **Git** keeps the project's history.
- **FFmpeg** repackages the audio into a normal file (it does not re-encode).
- **Deno** is required by yt-dlp to download from YouTube (since late 2025).

Check them (reopen the terminal first):

```powershell
py --version; git --version; ffmpeg -version | Select-Object -First 1; deno --version
```

### 2. Set up the project

Unzip the project to somewhere like `C:\Projects\dielify`, then:

```powershell
cd C:\Projects\dielify
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

If `Activate.ps1` is blocked with a "running scripts is disabled" error, run this
once and try again:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

You'll know the environment is active when the prompt starts with `(.venv)`. Do the
`Activate.ps1` line each time you open a new terminal for this project.

### 3. Check everything

```powershell
dielify doctor
pytest
```

`dielify doctor` should end with **All good.** and `pytest` should show all tests passed.

### 4. Choose where music is saved

```powershell
dielify config set library_root "D:\Music\Dielify"
dielify config show
```

Use any folder you like. Each user profile gets its own subfolder inside it, laid out
as `Artist\Album\NN Title.opus` (or `.m4a`). Other settings:

| Setting | Values | Meaning |
|---|---|---|
| `quality` | `auto` (default), `high`, `standard` | `auto`/`high` = best available (with Premium: ~256 kbps Opus, or 256 kbps AAC if you prefer `m4a`); `standard` caps at ~160 kbps |
| `preferred_format` | `auto` (default), `m4a`, `opus` | Prefer a format when both exist. Audio is never re-encoded. |
| `active_profile` | any name, e.g. `josh` | Whose login and library folder to use |
| `request_delay_s` | seconds, default `1.5` | Pause between YouTube requests, to keep traffic human-paced |

```powershell
dielify config set active_profile josh
```

### 5. Sign in to YouTube Music

Dielify signs in with your browser session (this is currently the reliable method; the
alternative OAuth route now needs your own Google Cloud project).

**Use an Incognito window, and close it afterwards.** Your normal browser keeps
replacing its sign-in cookies with fresh ones as you browse, and Google then
rejects older copies, so headers copied from a normal window stop working within
hours. Cookies from an Incognito window you close straight away are never
replaced, so Dielify's copy keeps working (typically for weeks).

1. In **Chrome**, press **Ctrl+Shift+N** for a new Incognito window. (Edge:
   **Ctrl+Shift+N** opens an InPrivate window.) Go to <https://music.youtube.com>
   and **sign in** with your Premium account. If you use a brand account or more
   than one channel, switch to the one you listen on.
2. Press **F12** to open Developer Tools, then click the **Network** tab.
3. In the filter box type `browse`, then click around YouTube Music (e.g. open
   **Library**) until a request named `browse?...` appears.
   **It must be music.youtube.com, not www.youtube.com.** Headers copied from
   ordinary YouTube don't work, and Dielify will tell you if that's what you copied.
4. Click that request. On the right, stay on the **Headers** tab and scroll down to
   the **Request Headers** heading. Click and drag to select every line under it,
   from `accept:` down to the last line (usually `x-youtube-client-version`), and copy
   with **Ctrl+C**. Leave the "Raw" switch as it is: either view works.
   (Firefox: right-click the request → **Copy Value** → **Copy Request Headers**.)
5. Back in the terminal:

```powershell
dielify auth login --clipboard
```

6. When it says **Signed in as &lt;your name&gt;**, **close the Incognito window**
   (just close it; don't click "Sign out", which would end Dielify's session too).

The login is encrypted with Windows
DPAPI, so only your Windows account on this PC can read it. Nothing is stored in
plain text and nothing goes into the project folder.

> These headers are your login. Don't paste them anywhere else. If you saved them to a
> file, use `dielify auth login --file headers.txt` and then delete the file.
> YouTube sign-ins do expire eventually. `dielify auth status` checks it any time.
> While the PC isn't signed in, download requests wait in the queue with the message
> "Waiting for YouTube sign-in on the PC" rather than quietly downloading at lower
> quality. Repeat this step and they carry on by themselves.

### 6. Search and download

```powershell
dielify search under pressure queen
dielify get under pressure queen          # shows results, you pick one, it downloads
dielify download VIDEO_ID                 # or by the id shown in search results
dielify inspect "E:\Music\ymp\josh\Queen\Hot Space\11 Under Pressure (feat. David Bowie).opus"
```

A real download on Josh's PC (7 Nov 2026):

```
→ VIDEO_ID
  downloading… 100%
  downloaded, tagging…
  Queen — Under Pressure (feat. David Bowie)
  OggOpus, 251 kbps, 4:08, cover 104 KB
  E:\Music\ymp\josh\Queen\Hot Space\11 Under Pressure (feat. David Bowie).opus
```

Downloading the same track again is skipped (add `--overwrite` to replace it). Add
`-v` to any command for detailed output when something goes wrong.

### 7. Phase 1 acceptance test

1. Turn off Wi-Fi / unplug the network cable.
2. Open the downloaded file in **VLC**. It should play.
3. In VLC, **Tools → Media Information** should show title, artist, album, year,
   track number and the cover art.

When that works, Phase 1 is done.

## Phase 2 — play your library from a phone app (home network)

Dielify now keeps an index of your music and speaks the **Subsonic** protocol, so phone
apps like **Symfonium** or **Ultrasonic** can browse and play it. For now that
works over your home network only. Away-from-home access (Tailscale) is Phase 5.

### 1. Fix the firewall (one time, needs admin)

Your PC's network connection must be marked **Private** (a trusted home network).
The firewall rule below only opens Dielify's port on Private networks, and only for
Python.

Open **Terminal as administrator** (right-click Start → **Terminal (Admin)**) and
run these three commands one at a time:

```powershell
Set-NetConnectionProfile -InterfaceAlias Ethernet -NetworkCategory Private
```
Marks your home Ethernet connection as Private. (Same as Settings → Network &
internet → Ethernet → Network profile type → **Private**.)

```powershell
Remove-NetFirewallRule -DisplayName "python.exe"
```
Removes the broad "allow Python on **public** networks, every port" rules that
Windows created when the server first started. Dielify doesn't need them.

```powershell
New-NetFirewallRule -DisplayName "dielify server (private networks)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 4747 -Profile Private -Program "$env:LOCALAPPDATA\Python\pythoncore-3.15-64\python.exe"
```
Lets phones on your home network reach Dielify on port 4747, and nothing else.

If Windows still shows an "allow access?" pop-up when you start the server, tick
**only Private networks** and click **Allow**.

### 2. Make a login for the phone app

In your normal (non-admin) terminal, with `.venv` active:

```powershell
dielify server user add josh
```

This prints a random password **once**. Keep the terminal open until you've typed
it into the phone app. It's a separate password just for the app, not your
YouTube or Google password. Forgot it? `dielify server user password josh` makes a
new one.

### 3. Start the server

```powershell
dielify serve
```

It scans your music folder, then prints the address to use, for example
`http://192.168.1.249:4747`. Leave this window open while you listen; **Ctrl+C**
stops it. (Phase 4 turns this into a background service with a tray icon.)

### 4. Connect the phone

Your phone must be on the **same home network** as the PC (Wi-Fi, not mobile data).

- **Symfonium:** Add media provider → **Subsonic** → server address
  `http://192.168.1.249:4747`, user `josh`, the password from step 2. Leave other
  options at their defaults.
- **Ultrasonic:** Settings → Server → **+** → same address, user and password.

### 5. Phase 2 acceptance test

In the app, browse to **Queen → Hot Space → Under Pressure** and play it. Phase 2
is done when that works.

> The PC's address (`192.168.1.249`) is handed out by your router and can change
> after a restart. If the app stops connecting, check the address `dielify serve`
> prints. A router "DHCP reservation" keeps it fixed; Tailscale (Phase 5) makes
> this a non-issue.

## Phase 3 — discovery and download requests

The server now has its own API under `/api/` (the one the Android app will use in
Phase 6):

- **Discover:** your YouTube Music home feed and mixes, songs similar to a song, charts.
- **Browse YouTube:** search songs, videos, albums, playlists and artists, and open
  any album or playlist.
- **Request downloads:** a song, a whole album or a playlist. The PC works through
  the queue one track at a time, retries failures, and can cancel. Songs you
  already have aren't downloaded again.
- **Play:** finished downloads appear in the library straight away, for this API
  and for Symfonium alike.

Clients sign in once with the same user and password as Symfonium and get a
**device token**; each device can be signed out separately. The full API
description is at `http://<PC address>:4747/api/docs` while `dielify serve` runs,
and in [`docs/openapi.json`](docs/openapi.json).

### Phase 3 acceptance test

1. Make sure the PC's YouTube sign-in works: `dielify auth status`. If it says
   signed out, repeat Phase 1 step 5 (with the Incognito window).
2. Restart the server so it runs the new code: **Ctrl+C** in the `dielify serve`
   window, then `dielify serve` again.
3. **Have your server password ready.** This is the password for the `josh` server
   user that `dielify server user add josh` showed once in Phase 2, the one you typed
   into Symfonium. It isn't your YouTube or Google password. If you no longer have
   it, make a new one with `dielify server user password josh`. That replaces the old
   one, so also update it in Symfonium (edit the media provider → password).
4. In a second terminal, run the test client. It asks for that password; nothing
   appears while you type it, which is normal:

```powershell
.venv\Scripts\python tools\acceptance_phase3.py http://127.0.0.1:4747 josh
```

It signs in, reads your home feed, finds a song similar to "Under Pressure" that
you don't have yet, requests it, shows the download progress, and then plays it
from the library. It ends with **PASS** when everything worked. The new song
also shows up in Symfonium after a sync.

---

## Phase 5 — play from your PC anywhere (Tailscale)

Tailscale makes a private, encrypted network between your own devices. Your phone
reaches the PC from anywhere, with **no router changes and nothing open to the
internet**: Dielify only ever listens on your home network and on Tailscale.

**You need:** a Google, Microsoft or GitHub login (Tailscale is free for personal use;
use the same login everywhere), and to click **Yes** when Windows asks during the install.

1. **PC:** download from <https://tailscale.com/download/windows>, install, then click
   the Tailscale tray icon → **Log in** and sign in. The icon should say **Connected**.
2. **Phone:** install **Tailscale** from the Play Store, log in with the same account,
   allow the VPN, and make sure the switch is **on**.
3. **Dielify:** Settings → *Phone apps* shows two addresses: *On home Wi-Fi* and
   *Away from home (Tailscale)* (starts with `http://100.`). Dielify notices Tailscale
   by itself within 30 seconds, even if it connected after Dielify started.
4. **Symfonium:** add the Tailscale address as a second server (same user and
   password), or edit the existing one to use it: it works at home too.
5. Optional: Settings → *Keep this PC awake*, so it doesn't sleep while you're out.

**Phase 5 test:** turn off Wi-Fi on the phone (mobile data only, Tailscale on) and play
a song in Symfonium.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `dielify` is not recognised | Activate the environment: `.venv\Scripts\Activate.ps1` |
| `deno NOT FOUND` | `winget install -e --id DenoLand.Deno`, then reopen the terminal |
| `ffmpeg NOT FOUND` | `winget install -e --id Gyan.FFmpeg`, then reopen the terminal |
| "YouTube rejected the saved sign-in" | Cookies expired: repeat step 5 |
| Downloads fail after previously working | YouTube changed something. Update: `pip install -U yt-dlp ytmusicapi`, re-run `dielify doctor` and `pytest`, then pin the new versions in `pyproject.toml` |
| Phone app can't connect | Is `dielify serve` running? Same Wi-Fi as the PC? Address matches what `dielify serve` printed? Firewall step done (Phase 2 step 1)? |
| Downloads say "Waiting for YouTube sign-in on the PC" | The PC's YouTube sign-in has expired: repeat Phase 1 step 5 (Incognito). The queue carries on by itself |
| "Too many failed logins" | Wait 15 minutes, then check the password (or reset it: `dielify server user password josh`) |
| Only ~130–160 kbps instead of ~256 | Check `dielify auth status`; Premium quality needs a working sign-in |

## Project layout

```
src/dielify/
  yt_adapter.py   all YouTube access (ytmusicapi + yt-dlp) — fixes go here
  downloader.py   fetch → tag → file into Artist/Album/Track
  tagging.py      tags + cover art (m4a, opus, mp3, flac)
  credstore.py    encrypted per-profile sign-in (Windows DPAPI)
  settings.py     settings.json in %LOCALAPPDATA%\Dielify
  paths.py        app folders, Windows-safe file names
  cli.py          the `dielify` command
  library.py      SQLite index of each profile's music (rebuildable by a scan)
  subsonic_api.py Subsonic/OpenSubsonic API for phone apps
  auth.py         phone-app logins, lockout after failed logins
  server.py       web server; listens on home network/Tailscale only
  custom_api.py   our /api: discovery, YouTube browsing, downloads, settings
  downloads.py    download queue (saved in the database, retries, cancel)
tools/           acceptance test clients
tests/            pytest suite (uses FFmpeg-generated audio; no internet needed)
android/          Android app (Phase 6)
docs/HANDOFF.md   original project brief
```

## Security notes

- Your YouTube login is encrypted with Windows DPAPI and never written to the project
  folder, logs or console. `.gitignore` also blocks cookie/header files and the
  music folder.
- During a download the cookies are written to a temporary file for yt-dlp and
  deleted immediately afterwards.
- The server listens only on this PC's home-network and Tailscale addresses (plus
  localhost), never on all interfaces and never on a public address; Dielify refuses
  a `server_bind` setting that would.
- Phone-app passwords are random and only for Dielify. The Subsonic protocol means the
  server must be able to read them back, so they're encrypted with DPAPI rather
  than hashed. Ten wrong passwords from one device lock it out for 15 minutes.
- The server log records which page was requested, never the login details.
