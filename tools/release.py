"""Publish Dielify updates.  Run from the project folder with the project's Python:

    .venv\\Scripts\\python tools\\release.py keygen             once: create the signing key
    .venv\\Scripts\\python tools\\release.py export-key FILE    back the key up (asks for a password)
    .venv\\Scripts\\python tools\\release.py import-key FILE    restore it on a new PC
    .venv\\Scripts\\python tools\\release.py configure OWNER/REPO   where updates are published
    .venv\\Scripts\\python tools\\release.py publish --notes "What's new"

Phone app (signed with its own Android key, also kept in %LOCALAPPDATA%\\Dielify-release):
    .venv\\Scripts\\python tools\\release.py android-keygen           once
    .venv\\Scripts\\python tools\\release.py android-export-key FILE  back it up (asks for a password)
    .venv\\Scripts\\python tools\\release.py android-import-key FILE  restore it on a new PC
    .venv\\Scripts\\python tools\\release.py android-build            dist\\Dielify-<version>.apk
`publish` also builds and uploads the phone app once android-keygen has been run.

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
ANDROID_KEYSTORE = KEY_DIR / "android-release.jks"
ANDROID_PASSWORD = KEY_DIR / "android-keystore-password.dpapi"
ANDROID_ENTROPY = b"dielify-android-keystore"
ANDROID_DIR = ROOT / "android"
STUDIO_JBR = Path(r"C:\Program Files\Android\Android Studio\jbr")


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


def version_code(version: str = __version__) -> int:
    """Same rule as android/app/build.gradle.kts: 0.6.0 -> 600."""
    code = 0
    for part in version.split("."):
        code = code * 100 + int(part)
    return code


def write_manifest(setup: Path, url: str, notes: str, key,
                   apk: Path | None = None, apk_url: str | None = None) -> tuple[Path, Path]:
    manifest = {
        "version": __version__, "url": url, "sha256": hashlib.sha256(setup.read_bytes()).hexdigest(),
        "size": setup.stat().st_size, "notes": notes, "published": date.today().isoformat(),
    }
    if apk is not None:
        manifest["android"] = {
            "version": __version__, "version_code": version_code(), "url": apk_url,
            "sha256": hashlib.sha256(apk.read_bytes()).hexdigest(), "size": apk.stat().st_size,
        }
    data = json.dumps(manifest, indent=2).encode()
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
    apk = None
    if ANDROID_KEYSTORE.exists():
        apk = ROOT / "dist" / f"Dielify-{__version__}.apk"
        if not args.skip_build or not apk.exists():
            apk = build_android()
    apk_url = f"https://github.com/{repo}/releases/download/{tag}/{apk.name}" if apk else None
    man, sig = write_manifest(setup, url, args.notes, key, apk, apk_url)
    print(f"Signed manifest for {__version__}: {man}")
    files = [str(setup), str(man), str(sig)] + ([str(apk)] if apk else [])
    subprocess.run([gh, "release", "create", tag, *files, "--repo", repo,
                    "--title", f"Dielify {__version__}", "--notes", args.notes or f"Dielify {__version__}"],
                   check=True)
    print(f"Published {tag}. Installed copies will offer it within a day (or via Check for updates).")


# --- the phone app -------------------------------------------------------------------

def _android_password() -> str:
    if not (ANDROID_KEYSTORE.exists() and ANDROID_PASSWORD.exists()):
        sys.exit(f"No Android signing key at {ANDROID_KEYSTORE}. Run `release.py android-keygen` "
                 "(or `android-import-key` from your backup).")
    return _dpapi(ANDROID_PASSWORD.read_bytes(), ANDROID_ENTROPY, protect=False).decode()


def _keytool() -> str:
    exe = STUDIO_JBR / "bin" / "keytool.exe"
    return str(exe) if exe.exists() else (shutil.which("keytool") or sys.exit("keytool not found (install Android Studio)"))


def cmd_android_keygen(args) -> None:
    if ANDROID_KEYSTORE.exists() and not args.force:
        sys.exit("An Android signing key already exists. A new one means phones can't update "
                 "(they must uninstall and reinstall). If you really mean it: android-keygen --force")
    import secrets
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    ANDROID_KEYSTORE.unlink(missing_ok=True)
    password = secrets.token_urlsafe(24)
    env = {**os.environ, "DIELIFY_KS_PW": password}
    subprocess.run([_keytool(), "-genkeypair", "-keystore", str(ANDROID_KEYSTORE), "-storetype", "PKCS12",
                    "-alias", "dielify", "-keyalg", "RSA", "-keysize", "4096", "-validity", "36500",
                    "-dname", "CN=Dielify", "-storepass:env", "DIELIFY_KS_PW", "-keypass:env", "DIELIFY_KS_PW"],
                   check=True, env=env, capture_output=True)
    ANDROID_PASSWORD.write_bytes(_dpapi(password.encode(), ANDROID_ENTROPY, protect=True))
    print(f"Android signing key created: {ANDROID_KEYSTORE} (its password is stored encrypted next to it).")
    print("Now back it up: release.py android-export-key E:\\somewhere-safe\\dielify-android-key.backup")


def _backup_cipher(password: str, salt: bytes):
    from Cryptodome.Cipher import AES
    from Cryptodome.Protocol.KDF import scrypt
    return AES, scrypt(password.encode(), salt, 32, N=2 ** 17, r=8, p=1)


def cmd_android_export_key(args) -> None:
    pw = _android_password()
    blob = json.dumps({"keystore": base64.b64encode(ANDROID_KEYSTORE.read_bytes()).decode(),
                       "password": pw}).encode()
    salt = os.urandom(16)
    AES, key = _backup_cipher(_ask_password(True), salt)
    c = AES.new(key, AES.MODE_GCM)
    data, tag = c.encrypt_and_digest(blob)
    Path(args.file).write_text(json.dumps({
        "dielify-android-key": 1, "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(c.nonce).decode(), "tag": base64.b64encode(tag).decode(),
        "data": base64.b64encode(data).decode()}), encoding="utf-8")
    print(f"Backup written to {args.file}. Keep it (and its password) somewhere safe, not in the project.")


def cmd_android_import_key(args) -> None:
    f = json.loads(Path(args.file).read_text(encoding="utf-8"))
    AES, key = _backup_cipher(_ask_password(False), base64.b64decode(f["salt"]))
    c = AES.new(key, AES.MODE_GCM, nonce=base64.b64decode(f["nonce"]))
    try:
        blob = json.loads(c.decrypt_and_verify(base64.b64decode(f["data"]), base64.b64decode(f["tag"])))
    except ValueError:
        sys.exit("Wrong password (or the backup file is damaged).")
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    ANDROID_KEYSTORE.write_bytes(base64.b64decode(blob["keystore"]))
    ANDROID_PASSWORD.write_bytes(_dpapi(blob["password"].encode(), ANDROID_ENTROPY, protect=True))
    print(f"Android signing key restored to {ANDROID_KEYSTORE}")


def build_android() -> Path:
    """Build the signed release app into dist\\Dielify-<version>.apk."""
    pw = _android_password()
    env = {**os.environ, "DIELIFY_KEYSTORE": str(ANDROID_KEYSTORE), "DIELIFY_KEYSTORE_PASSWORD": pw}
    if STUDIO_JBR.exists():
        env["JAVA_HOME"] = str(STUDIO_JBR)
    subprocess.run([str(ANDROID_DIR / "gradlew.bat"), "assembleRelease", "--console=plain", "-q"],
                   cwd=ANDROID_DIR, env=env, check=True)
    built = ANDROID_DIR / "app" / "build" / "outputs" / "apk" / "release" / "app-release.apk"
    out = ROOT / "dist" / f"Dielify-{__version__}.apk"
    out.parent.mkdir(exist_ok=True)
    shutil.copyfile(built, out)
    print(f"Phone app built: {out} ({out.stat().st_size // 1_000_000} MB)")
    return out


def cmd_android_build(args) -> None:
    build_android()


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
    ak = sub.add_parser("android-keygen")
    ak.add_argument("--force", action="store_true")
    ak.set_defaults(fn=cmd_android_keygen)
    ae = sub.add_parser("android-export-key")
    ae.add_argument("file")
    ae.set_defaults(fn=cmd_android_export_key)
    ai = sub.add_parser("android-import-key")
    ai.add_argument("file")
    ai.set_defaults(fn=cmd_android_import_key)
    sub.add_parser("android-build").set_defaults(fn=cmd_android_build)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
