"""Publish Dielify updates.  Run from the project folder with the project's Python:

    .venv\\Scripts\\python tools\\release.py keygen             once: create the signing key
    .venv\\Scripts\\python tools\\release.py export-key FILE    back the key up (asks for a password)
    .venv\\Scripts\\python tools\\release.py import-key FILE    restore it on a new PC
    .venv\\Scripts\\python tools\\release.py configure OWNER/REPO   where updates are published
    .venv\\Scripts\\python tools\\release.py publish --notes "What's new"

The private key never enters the repository: it lives in %LOCALAPPDATA%\\Dielify-release,
encrypted for this Windows user (DPAPI). The app only contains the public key.
`publish` needs the GitHub CLI (`gh`), signed in to the account that owns OWNER/REPO.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from Cryptodome.PublicKey import ECC  # noqa: E402
from Cryptodome.Signature import eddsa  # noqa: E402

from dielify import __version__  # noqa: E402
from dielify.credstore import _dpapi  # noqa: E402

KEY_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "Dielify-release"
KEY_FILE = KEY_DIR / "signing-key.dpapi"
ENTROPY = b"dielify-release-signing-key"
CONFIG = ROOT / "src" / "dielify" / "update_config.py"


def _set_config(name: str, value: str) -> None:
    t = CONFIG.read_text(encoding="utf-8")
    line = f"{name}: str | None = {value!r}"
    # a function, not a string, as the replacement: re would turn the "\n" in a
    # repr'd PEM key into real line breaks and break the file
    new, n = re.subn(rf"^{name}: str \| None = .*?(?=\n\n|\n#|\Z)", lambda m: line,
                     t, count=1, flags=re.M | re.S)
    if n != 1:
        sys.exit(f"Couldn't find {name} in {CONFIG}")
    CONFIG.write_text(new, encoding="utf-8")


def _save_key(key) -> None:
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    pem = key.export_key(format="PEM").encode()
    KEY_FILE.write_bytes(_dpapi(pem, ENTROPY, protect=True))
    _set_config("PUBLIC_KEY_PEM", key.public_key().export_key(format="PEM"))


def _load_key():
    if not KEY_FILE.exists():
        sys.exit(f"No signing key found at {KEY_FILE} (running as {getpass.getuser()}). "
                 "Run `release.py keygen` (or `import-key` from your backup).")
    return ECC.import_key(_dpapi(KEY_FILE.read_bytes(), ENTROPY, protect=False).decode())


def cmd_keygen(args) -> None:
    if KEY_FILE.exists() and not args.force:
        sys.exit("A signing key already exists. Replacing it means installed copies reject future "
                 "updates until reinstalled by hand. If you really mean it: keygen --force")
    _save_key(ECC.generate(curve="ed25519"))
    print(f"Signing key created and stored encrypted at {KEY_FILE}")
    print(f"Public key written to {CONFIG} (commit that file).")
    print("Now back it up: release.py export-key E:\\somewhere-safe\\dielify-signing-key.pem")


def _ask_password(confirm: bool) -> str:
    pw = getpass.getpass("Password for the backup (typing is hidden): ")
    if confirm and pw != getpass.getpass("Same password again: "):
        sys.exit("The passwords didn't match.")
    if confirm and len(pw) < 10:
        sys.exit("Use at least 10 characters.")
    return pw


def cmd_export_key(args) -> None:
    key = _load_key()
    pem = key.export_key(format="PEM", passphrase=_ask_password(True),
                         protection="PBKDF2WithHMAC-SHA512AndAES256-CBC")
    Path(args.file).write_text(pem, encoding="utf-8")
    print(f"Backup written to {args.file}. Keep it (and its password) somewhere safe, not in the project.")


def cmd_import_key(args) -> None:
    key = ECC.import_key(Path(args.file).read_text(encoding="utf-8"), passphrase=_ask_password(False))
    _save_key(key)
    print(f"Signing key restored to {KEY_FILE}")


def cmd_configure(args) -> None:
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", args.repo):
        sys.exit("Give it as OWNER/REPO, e.g. josh/dielify-releases")
    _set_config("MANIFEST_URL", f"https://github.com/{args.repo}/releases/latest/download/manifest.json")
    print(f"Updates will come from https://github.com/{args.repo}/releases (commit {CONFIG}).")


def _repo_from_config() -> str:
    from importlib import reload

    import dielify.update_config as uc
    reload(uc)
    if not (uc.MANIFEST_URL and uc.PUBLIC_KEY_PEM):
        sys.exit("Run `release.py keygen` and `release.py configure OWNER/REPO` first.")
    m = re.match(r"https://github.com/([^/]+/[^/]+)/", uc.MANIFEST_URL)
    return m.group(1)


def write_manifest(setup: Path, url: str, notes: str, key) -> tuple[Path, Path]:
    data = json.dumps({
        "version": __version__, "url": url, "sha256": hashlib.sha256(setup.read_bytes()).hexdigest(),
        "size": setup.stat().st_size, "notes": notes, "published": date.today().isoformat(),
    }, indent=2).encode()
    man, sig = setup.with_name("manifest.json"), setup.with_name("manifest.json.sig")
    man.write_bytes(data)
    sig.write_text(base64.b64encode(eddsa.new(key, "rfc8032").sign(data)).decode(), encoding="ascii")
    return man, sig


def cmd_publish(args) -> None:
    repo = _repo_from_config()
    key = _load_key()
    gh = shutil.which("gh")
    if not gh:
        sys.exit("The GitHub CLI isn't installed: winget install -e --id GitHub.cli")
    if subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        sys.exit("Commit your changes first, so the release matches the code in git.")
    if not args.skip_build:
        subprocess.run([sys.executable, str(ROOT / "packaging" / "build.py")], check=True)
    setup = ROOT / "dist" / f"Dielify-setup-{__version__}.exe"
    tag = f"v{__version__}"
    url = f"https://github.com/{repo}/releases/download/{tag}/{setup.name}"
    man, sig = write_manifest(setup, url, args.notes, key)
    print(f"Signed manifest for {__version__}: {man}")
    subprocess.run([gh, "release", "create", tag, str(setup), str(man), str(sig), "--repo", repo,
                    "--title", f"Dielify {__version__}", "--notes", args.notes or f"Dielify {__version__}"],
                   check=True)
    print(f"Published {tag}. Installed copies will offer it within a day (or via Check for updates).")


def main() -> None:
    p = argparse.ArgumentParser(prog="release.py", description="Publish Dielify updates")
    sub = p.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen")
    k.add_argument("--force", action="store_true")
    k.set_defaults(fn=cmd_keygen)
    e = sub.add_parser("export-key")
    e.add_argument("file")
    e.set_defaults(fn=cmd_export_key)
    i = sub.add_parser("import-key")
    i.add_argument("file")
    i.set_defaults(fn=cmd_import_key)
    c = sub.add_parser("configure")
    c.add_argument("repo", help="OWNER/REPO on GitHub, e.g. josh/dielify-releases")
    c.set_defaults(fn=cmd_configure)
    pub = sub.add_parser("publish")
    pub.add_argument("--notes", default="", help="what's new, shown in the app")
    pub.add_argument("--skip-build", action="store_true", help="use the installer already in dist\\")
    pub.set_defaults(fn=cmd_publish)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
