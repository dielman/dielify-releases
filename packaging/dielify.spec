# PyInstaller build: one folder with Dielify.exe (desktop app) and dielify-cli.exe
# (command line) sharing the same Python and libraries. Build with:  python packaging\build.py
# (Not "dielify.exe": Windows file names ignore case, so it would overwrite Dielify.exe.)
# FFmpeg and Deno are not bundled here: the installer puts them in {app}\bin.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = SPECPATH + "\\.."
hidden = (collect_submodules("uvicorn") + collect_submodules("websockets") + collect_submodules("dielify")
          + ["pystray._win32", "webview.platforms.winforms", "webview.platforms.edgechromium"])
datas = [(ROOT + "\\src\\dielify\\ui", "dielify\\ui")] + collect_data_files("ytmusicapi")

common = dict(pathex=[ROOT + "\\src"], hiddenimports=hidden, datas=datas,
              excludes=["pytest", "PyInstaller"])  # keep tkinter: `auth login --clipboard`
app = Analysis([SPECPATH + "\\entry_desktop.py"], **common)
cli = Analysis([SPECPATH + "\\entry_cli.py"], **common)

app_exe = EXE(PYZ(app.pure), app.scripts, [], exclude_binaries=True, name="Dielify",
              icon=SPECPATH + "\\dielify.ico", console=False, version=SPECPATH + "\\version_info.txt")
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name="dielify-cli",
              icon=SPECPATH + "\\dielify.ico", console=True, version=SPECPATH + "\\version_info.txt")

COLLECT(app_exe, app.binaries, app.datas, cli_exe, cli.binaries, cli.datas,
        name="Dielify", strip=False, upx=False)
