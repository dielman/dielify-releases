"""Per-profile YouTube credentials, encrypted at rest.

On Windows the data is encrypted with DPAPI (CryptProtectData), so only the same
Windows user on the same PC can decrypt it. There is no plain-text fallback on
Windows. On other systems saving is refused unless YMP_INSECURE_DEV_STORE=1 is set,
which exists only for development and tests.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

from .paths import app_data_dir, safe_name

_ENTROPY_PREFIX = b"ymp-credstore-v1:"


class CredentialError(Exception):
    pass


# --- DPAPI via ctypes (no pywin32 dependency) ------------------------------

def _dpapi(data: bytes, entropy: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def to_blob(b: bytes) -> BLOB:
        buf = ctypes.create_string_buffer(b, len(b))
        return BLOB(len(b), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    inp, ent, out = to_blob(data), to_blob(entropy), BLOB()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ok = fn(ctypes.byref(inp), None, ctypes.byref(ent), None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(out))
    if not ok:
        raise CredentialError(f"DPAPI {'encrypt' if protect else 'decrypt'} failed "
                              f"(Windows error {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def _is_windows() -> bool:
    return sys.platform == "win32"


def _dev_store_allowed() -> bool:
    return os.environ.get("YMP_INSECURE_DEV_STORE") == "1"


# --- Public API -------------------------------------------------------------

def _cred_dir() -> Path:
    d = app_data_dir() / "credentials"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cred_path(profile: str) -> Path:
    return _cred_dir() / f"{safe_name(profile)}.dpapi"


def save(profile: str, auth: dict) -> Path:
    payload = json.dumps(auth).encode("utf-8")
    entropy = _ENTROPY_PREFIX + profile.encode("utf-8")
    if _is_windows():
        blob = b"DPAPI1" + _dpapi(payload, entropy, protect=True)
    elif _dev_store_allowed():
        blob = b"INSECURE-DEV" + base64.b64encode(payload)
    else:
        raise CredentialError(
            "Refusing to store credentials unencrypted on this OS. ymp's credential "
            "store uses Windows DPAPI. For local development only, set "
            "YMP_INSECURE_DEV_STORE=1.")
    path = _cred_path(profile)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(blob)
    if not _is_windows():
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def load(profile: str) -> dict | None:
    path = _cred_path(profile)
    if not path.exists():
        return None
    blob = path.read_bytes()
    entropy = _ENTROPY_PREFIX + profile.encode("utf-8")
    if blob.startswith(b"DPAPI1"):
        if not _is_windows():
            raise CredentialError("These credentials were encrypted on Windows.")
        payload = _dpapi(blob[6:], entropy, protect=False)
    elif blob.startswith(b"INSECURE-DEV"):
        if not _dev_store_allowed():
            raise CredentialError("Found a development-only credential file; refusing to use it.")
        payload = base64.b64decode(blob[12:])
    else:
        raise CredentialError(f"Unrecognised credential file: {path}")
    return json.loads(payload)


def delete(profile: str) -> bool:
    path = _cred_path(profile)
    if path.exists():
        path.unlink()
        return True
    return False


def list_profiles() -> list[str]:
    return sorted(p.stem for p in _cred_dir().glob("*.dpapi"))
