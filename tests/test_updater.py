"""Signed updates: only an installer listed in a correctly signed manifest, with the
right size and SHA-256, is ever started."""

import base64
import hashlib
import json

import pytest
from Cryptodome.PublicKey import ECC
from Cryptodome.Signature import eddsa

from dielify import settings, update_config, updater as upd
from dielify.updater import UpdateError, Updater, verify_manifest, version_tuple

MANIFEST_URL = "https://example.test/releases/latest/download/manifest.json"
INSTALLER = b"MZ fake installer bytes" * 1000


def sign(key, data: bytes) -> str:
    return base64.b64encode(eddsa.new(key, "rfc8032").sign(data)).decode()


def manifest(version="9.9.9", payload=INSTALLER, **overrides) -> bytes:
    m = {"version": version, "url": "https://example.test/Dielify-setup.exe",
         "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload), "notes": "Faster."}
    m.update(overrides)
    return json.dumps(m).encode()


class FakeResponse:
    def __init__(self, body: bytes):
        self.content, self.text = body, body.decode("latin-1")

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class FakeHttp:
    def __init__(self, files: dict[str, bytes]):
        self.files, self.requests = files, []

    def get(self, url, **kw):
        self.requests.append(url)
        return FakeResponse(self.files[url])


@pytest.fixture
def key(monkeypatch):
    k = ECC.generate(curve="ed25519")
    monkeypatch.setattr(update_config, "MANIFEST_URL", MANIFEST_URL)
    monkeypatch.setattr(update_config, "PUBLIC_KEY_PEM", k.public_key().export_key(format="PEM"))
    return k


def make(key, man: bytes, sig: str | None = None, payload: bytes = INSTALLER):
    http = FakeHttp({MANIFEST_URL: man, MANIFEST_URL + ".sig": (sig or sign(key, man)).encode(),
                     "https://example.test/Dielify-setup.exe": payload})
    started = []
    u = Updater(http=http, run_installer=started.append)
    return u, http, started


def test_version_compare():
    assert version_tuple("0.10.0") > version_tuple("0.9.9") > version_tuple("v0.4")
    assert version_tuple("1.0.0-beta2") == (1, 0, 2)


def test_good_update_downloads_verifies_and_starts(key):
    u, http, started = make(key, manifest())
    quit_called = []
    u.on_installer_started = lambda: quit_called.append(True)
    st = u.check()
    assert st.available and st.latest == "9.9.9" and st.notes == "Faster." and st.error is None
    u.install()
    assert len(started) == 1 and started[0].read_bytes() == INSTALLER and quit_called


def test_wrong_signature_rejected(key):
    other = ECC.generate(curve="ed25519")
    man = manifest()
    u, http, started = make(key, man, sig=sign(other, man))
    st = u.check()
    assert not st.available and "signature" in st.error
    assert "https://example.test/Dielify-setup.exe" not in http.requests  # nothing downloaded
    with pytest.raises(UpdateError):
        u.install()
    assert not started


def test_manifest_changed_after_signing_rejected(key):
    signed = manifest()
    tampered = manifest(url="https://evil.test/x.exe")
    u, _, started = make(key, tampered, sig=sign(key, signed))
    assert "signature" in u.check().error and not started


def test_installer_not_matching_fingerprint_is_deleted(key, isolated_home):
    u, _, started = make(key, manifest(), payload=INSTALLER[:-1] + b"X")
    u.check()
    with pytest.raises(UpdateError, match="fingerprint"):
        u.install()
    assert not started and not list((isolated_home / "updates").glob("*"))
    assert u.status.installing is False


def test_http_url_refused(key):
    with pytest.raises(UpdateError, match="HTTPS"):
        man = manifest(url="http://example.test/x.exe")
        verify_manifest(man, sign(key, man), update_config.PUBLIC_KEY_PEM)


def test_older_or_same_version_not_offered(key):
    from dielify import __version__
    u, _, _ = make(key, manifest(version=__version__))
    assert u.check().available is False


def test_offline_mode_and_unconfigured_never_check(key, monkeypatch):
    settings.set_value("offline", "true")
    u, http, _ = make(key, manifest())
    assert "Offline" in u.check().error and http.requests == []
    settings.set_value("offline", "false")
    monkeypatch.setattr(update_config, "MANIFEST_URL", None)
    u2, http2, _ = make(key, manifest())
    assert "aren't set up" in u2.check().error and http2.requests == []


def test_development_copy_never_runs_an_installer(tmp_path):
    with pytest.raises(UpdateError, match="installed app"):
        upd._launch_installer(tmp_path / "x.exe")
