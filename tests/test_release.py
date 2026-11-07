"""tools/release.py: what `publish` signs is exactly what the app's updater accepts."""

import importlib.util
import shutil
from pathlib import Path

import pytest
from Cryptodome.PublicKey import ECC

from dielify.updater import verify_manifest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def release(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("release", ROOT / "tools" / "release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = tmp_path / "update_config.py"
    shutil.copy(ROOT / "src" / "dielify" / "update_config.py", cfg)
    monkeypatch.setattr(mod, "CONFIG", cfg)  # never touch the real file
    return mod


def test_publish_manifest_verifies_in_app(release, tmp_path):
    key = ECC.generate(curve="ed25519")
    setup = tmp_path / "Dielify-setup-1.2.3.exe"
    setup.write_bytes(b"installer" * 100)
    man, sig = release.write_manifest(setup, "https://github.com/o/r/releases/download/v1/x.exe", "notes", key)
    data = verify_manifest(man.read_bytes(), sig.read_text(), key.public_key().export_key(format="PEM"))
    assert data["size"] == 900 and data["url"].startswith("https://github.com/")


def test_configure_and_public_key_written(release):
    class A:
        repo = "josh/dielify-releases"
    release.cmd_configure(A)
    release._set_config("PUBLIC_KEY_PEM", "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----")
    ns = {}
    exec(release.CONFIG.read_text(encoding="utf-8"), ns)
    assert ns["MANIFEST_URL"] == "https://github.com/josh/dielify-releases/releases/latest/download/manifest.json"
    assert ns["PUBLIC_KEY_PEM"].startswith("-----BEGIN PUBLIC KEY-----")
    release._set_config("MANIFEST_URL", "https://github.com/a/b/releases/latest/download/manifest.json")
    exec(release.CONFIG.read_text(encoding="utf-8"), ns)
    assert ns["MANIFEST_URL"].startswith("https://github.com/a/b/") and ns["PUBLIC_KEY_PEM"]


def test_manifest_includes_phone_app(release, tmp_path):
    import hashlib
    key = ECC.generate(curve="ed25519")
    setup = tmp_path / "Dielify-setup-0.6.0.exe"
    setup.write_bytes(b"installer")
    apk = tmp_path / "Dielify-0.6.0.apk"
    apk.write_bytes(b"phone app" * 10)
    man, sig = release.write_manifest(setup, "https://x/setup.exe", "notes", key, apk, "https://x/app.apk")
    data = verify_manifest(man.read_bytes(), sig.read_text(), key.public_key().export_key(format="PEM"))
    a = data["android"]
    assert a["url"] == "https://x/app.apk" and a["size"] == 90
    assert a["sha256"] == hashlib.sha256(apk.read_bytes()).hexdigest()
    assert a["version_code"] == release.version_code(a["version"])
    assert release.version_code("0.6.0") == 600 and release.version_code("1.2.3") == 10203
