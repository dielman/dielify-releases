# ymp — self-hosted YouTube Music player

Sign in to YouTube Music, download tracks to your own folder with full tags and cover
art, play them offline, and (in later phases) stream your library to a custom Android
app over your home network or Tailscale.

> Working name **ymp**. The full plan is in [`docs/HANDOFF.md`](docs/HANDOFF.md);
> decisions, architecture and progress are in [`CLAUDE.md`](CLAUDE.md).

## Status

| Phase | What | Status |
|---|---|---|
| 1 | Command line: sign in, search, download with tags + cover art | **Done** (7 Nov 2026) |
| 2 | Library database + Subsonic API (Symfonium/Ultrasonic) | **Done** (7 Nov 2026) |
| 3 | Discovery + download requests | **Next** |
| 4 | Desktop app (settings, folder picker, tray icon) | |
| 5 | Secure remote access (Tailscale) | |
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

- **Python** runs ymp. **Git** keeps the project's history.
- **FFmpeg** repackages the audio into a normal file (it does not re-encode).
- **Deno** is required by yt-dlp to download from YouTube (since late 2025).

Check them (reopen the terminal first):

```powershell
py --version; git --version; ffmpeg -version | Select-Object -First 1; deno --version
```

### 2. Set up the project

Unzip the project to somewhere like `C:\Projects\ymp`, then:

```powershell
cd C:\Projects\ymp
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
ymp doctor
pytest
```

`ymp doctor` should end with **All good.** and `pytest` should show all tests passed.

### 4. Choose where music is saved

```powershell
ymp config set library_root "D:\Music\ymp"
ymp config show
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
ymp config set active_profile josh
```

### 5. Sign in to YouTube Music

ymp signs in with your browser session (this is currently the reliable method; the
alternative OAuth route now needs your own Google Cloud project).

1. In **Chrome or Edge**, go to <https://music.youtube.com> and make sure you're signed
   in with your Premium account.
2. Press **F12** to open Developer Tools, then click the **Network** tab.
3. In the filter box type `browse`, then click around YouTube Music (e.g. open
   **Library**) until a request named `browse?...` appears.
   **It must be music.youtube.com, not www.youtube.com.** Headers copied from
   ordinary YouTube don't work, and ymp will tell you if that's what you copied.
4. Click that request. On the right, stay on the **Headers** tab and scroll down to
   the **Request Headers** heading. Click and drag to select every line under it,
   from `accept:` down to the last line (usually `x-youtube-client-version`), and copy
   with **Ctrl+C**. Leave the "Raw" switch as it is: either view works.
   (Firefox: right-click the request → **Copy Value** → **Copy Request Headers**.)
5. Back in the terminal:

```powershell
ymp auth login --clipboard
```

You should see **Signed in as &lt;your name&gt;**. The login is encrypted with Windows
DPAPI, so only your Windows account on this PC can read it. Nothing is stored in
plain text and nothing goes into the project folder.

> These headers are your login. Don't paste them anywhere else. If you saved them to a
> file, use `ymp auth login --file headers.txt` and then delete the file.
> YouTube sign-ins expire after some weeks; when ymp says the login was rejected,
> repeat this step. `ymp auth status` checks it any time.

### 6. Search and download

```powershell
ymp search under pressure queen
ymp get under pressure queen          # shows results, you pick one, it downloads
ymp download VIDEO_ID                 # or by the id shown in search results
ymp inspect "E:\Music\ymp\josh\Queen\Hot Space\11 Under Pressure (feat. David Bowie).opus"
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

ymp now keeps an index of your music and speaks the **Subsonic** protocol, so phone
apps like **Symfonium** or **Ultrasonic** can browse and play it. For now that
works over your home network only. Away-from-home access (Tailscale) is Phase 5.

### 1. Fix the firewall (one time, needs admin)

Your PC's network connection must be marked **Private** (a trusted home network).
The firewall rule below only opens ymp's port on Private networks, and only for
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
Windows created when the server first started. ymp doesn't need them.

```powershell
New-NetFirewallRule -DisplayName "ymp server (private networks)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 4747 -Profile Private -Program "$env:LOCALAPPDATA\Python\pythoncore-3.15-64\python.exe"
```
Lets phones on your home network reach ymp on port 4747, and nothing else.

If Windows still shows an "allow access?" pop-up when you start the server, tick
**only Private networks** and click **Allow**.

### 2. Make a login for the phone app

In your normal (non-admin) terminal, with `.venv` active:

```powershell
ymp server user add josh
```

This prints a random password **once**. Keep the terminal open until you've typed
it into the phone app. It's a separate password just for the app, not your
YouTube or Google password. Forgot it? `ymp server user password josh` makes a
new one.

### 3. Start the server

```powershell
ymp serve
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
> after a restart. If the app stops connecting, check the address `ymp serve`
> prints. A router "DHCP reservation" keeps it fixed; Tailscale (Phase 5) makes
> this a non-issue.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ymp` is not recognised | Activate the environment: `.venv\Scripts\Activate.ps1` |
| `deno NOT FOUND` | `winget install -e --id DenoLand.Deno`, then reopen the terminal |
| `ffmpeg NOT FOUND` | `winget install -e --id Gyan.FFmpeg`, then reopen the terminal |
| "YouTube rejected the saved sign-in" | Cookies expired: repeat step 5 |
| Downloads fail after previously working | YouTube changed something. Update: `pip install -U yt-dlp ytmusicapi`, re-run `ymp doctor` and `pytest`, then pin the new versions in `pyproject.toml` |
| Phone app can't connect | Is `ymp serve` running? Same Wi-Fi as the PC? Address matches what `ymp serve` printed? Firewall step done (Phase 2 step 1)? |
| "Too many failed logins" | Wait 15 minutes, then check the password (or reset it: `ymp server user password josh`) |
| Only ~130–160 kbps instead of ~256 | Check `ymp auth status`; Premium quality needs a working sign-in |

## Project layout

```
src/ymp/
  yt_adapter.py   all YouTube access (ytmusicapi + yt-dlp) — fixes go here
  downloader.py   fetch → tag → file into Artist/Album/Track
  tagging.py      tags + cover art (m4a, opus, mp3, flac)
  credstore.py    encrypted per-profile sign-in (Windows DPAPI)
  settings.py     settings.json in %LOCALAPPDATA%\ymp
  paths.py        app folders, Windows-safe file names
  cli.py          the `ymp` command
  library.py      SQLite index of each profile's music (rebuildable by a scan)
  subsonic_api.py Subsonic/OpenSubsonic API for phone apps
  auth.py         phone-app logins, lockout after failed logins
  server.py       web server; listens on home network/Tailscale only
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
  localhost), never on all interfaces and never on a public address; ymp refuses
  a `server_bind` setting that would.
- Phone-app passwords are random and only for ymp. The Subsonic protocol means the
  server must be able to read them back, so they're encrypted with DPAPI rather
  than hashed. Ten wrong passwords from one device lock it out for 15 minutes.
- The server log records which page was requested, never the login details.
