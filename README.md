# ymp — self-hosted YouTube Music player

Sign in to YouTube Music, download tracks to your own folder with full tags and cover
art, play them offline, and (in later phases) stream your library to a custom Android
app over your home network or Tailscale.

> Working name **ymp**. The full plan is in [`docs/HANDOFF.md`](docs/HANDOFF.md);
> decisions, architecture and progress are in [`CLAUDE.md`](CLAUDE.md).

## Status

| Phase | What | Status |
|---|---|---|
| 1 | Command line: sign in, search, download with tags + cover art | **Ready to test on Windows** |
| 2 | Library database + Subsonic API (Symfonium/Ultrasonic) | Next |
| 3 | Discovery + download requests | |
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
as `Artist\Album\NN Title.m4a`. Other settings:

| Setting | Values | Meaning |
|---|---|---|
| `quality` | `auto` (default), `high`, `standard` | `auto`/`high` = best available (256 kbps AAC with Premium); `standard` caps at ~160 kbps |
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
4. Click that request. In **Headers**, scroll to **Request Headers**, tick **Raw**,
   and select and copy **everything** in that section.
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
ymp inspect "D:\Music\ymp\josh\Queen\Hot Space\11 Under Pressure.m4a"
```

Example of a successful download:

```
→ VIDEO_ID
  downloading… 100%
  downloaded, tagging…
  Queen, David Bowie — Under Pressure
  MP4, 256 kbps, 4:08, cover 180 KB
  D:\Music\ymp\josh\Queen\Hot Space\11 Under Pressure.m4a
```

Downloading the same track again is skipped (add `--overwrite` to replace it). Add
`-v` to any command for detailed output when something goes wrong.

### 7. Phase 1 acceptance test

1. Turn off Wi-Fi / unplug the network cable.
2. Open the downloaded file in **VLC**. It should play.
3. In VLC, **Tools → Media Information** should show title, artist, album, year,
   track number and the cover art.

When that works, Phase 1 is done.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ymp` is not recognised | Activate the environment: `.venv\Scripts\Activate.ps1` |
| `deno NOT FOUND` | `winget install -e --id DenoLand.Deno`, then reopen the terminal |
| `ffmpeg NOT FOUND` | `winget install -e --id Gyan.FFmpeg`, then reopen the terminal |
| "YouTube rejected the saved sign-in" | Cookies expired: repeat step 5 |
| Downloads fail after previously working | YouTube changed something. Update: `pip install -U yt-dlp ytmusicapi`, re-run `ymp doctor` and `pytest`, then pin the new versions in `pyproject.toml` |
| Only ~128 kbps instead of 256 | Check `ymp auth status`; Premium quality needs a working sign-in |

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
- The network server (Phase 2+) will bind only to your local network and Tailscale,
  never to the public internet.
