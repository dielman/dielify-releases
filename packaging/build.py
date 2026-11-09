"""Build the Dielify installer:  .venv\\Scripts\\python packaging\\build.py

1. icon + Windows version info from dielify.__version__
2. PyInstaller -> dist\\Dielify\\ (Dielify.exe, dielify-cli.exe, _internal\\)
3. Inno Setup -> dist\\Dielify-setup-<version>.exe, with FFmpeg and Deno in {app}\\bin

Needs: the dev install (pip install -e ".[dev,build]"), Inno Setup 6, and FFmpeg +
Deno on PATH (they're copied from there into the installer).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging"
sys.path.insert(0, str(ROOT / "src"))

from dielify import __version__  # noqa: E402
from dielify.brand import icon_image  # noqa: E402


def iscc() -> Path:
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES")):
        p = Path(base or "") / ("Programs/Inno Setup 6" if base == os.environ.get("LOCALAPPDATA") else "Inno Setup 6") / "ISCC.exe"
        if p.exists():
            return p
    sys.exit("Inno Setup 6 not found: winget install -e --id JRSoftware.InnoSetup")


def tool_dir(name: str) -> Path:
    exe = shutil.which(name)
    if not exe:
        sys.exit(f"{name} not found on PATH (it's bundled into the installer from there)")
    return Path(exe).parent


def make_icon() -> None:
    img = icon_image(256)  # Pillow scales it down for the smaller sizes
    img.save(PKG / "dielify.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def make_version_info() -> None:
    nums = (__version__.split(".") + ["0", "0", "0"])[:4]
    tup = ", ".join(str(int(n)) for n in nums)
    (PKG / "version_info.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({tup}), prodvers=({tup})),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Josh'),
    StringStruct('FileDescription', 'Dielify'),
    StringStruct('FileVersion', '{__version__}'),
    StringStruct('ProductName', 'Dielify'),
    StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""", encoding="utf-8")


def run(cmd: list) -> None:
    print(">", " ".join(map(str, cmd)), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    print(f"Building Dielify {__version__}")
    make_icon()
    make_version_info()
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
         "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build"), str(PKG / "dielify.spec")])
    ffmpeg, deno = tool_dir("ffmpeg"), tool_dir("deno")
    run([iscc(), "/Q", f"/DAppVersion={__version__}", f"/DFFmpegDir={ffmpeg}", f"/DDenoDir={deno}",
         str(PKG / "dielify.iss")])
    setup = ROOT / "dist" / f"Dielify-setup-{__version__}.exe"
    digest = hashlib.sha256(setup.read_bytes()).hexdigest()
    print(f"\nBuilt {setup}\n  {setup.stat().st_size / 1e6:.0f} MB, sha256 {digest}")


if __name__ == "__main__":
    main()
