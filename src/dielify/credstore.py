"""Per-profile YouTube credentials, encrypted at rest.

On Windows the data is encrypted with DPAPI (CryptProtectData), so only the same
Windows user on the same PC can decrypt it. There is no plain-text fallback on
Windows. On other systems saving is refused unless DIELIFY_INSECURE_DEV_STORE=1 is set,
which exists only for development and tests.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
from pathlib import Path

from .paths import app_data_dir, safe_name

_ENTROPY_PREFIX = b"dielify-credstore-v1:"
_LEGACY_ENTROPY_PREFIX = b"ymp-credstore-v1:"  # before the rename to Dielify


class CredentialError(Exception):
    pass


# --- DPAPI via ctypes (no pywin32 dependency) ------------------------------
# Calls are made one at a time (a lock), with argument types declared, and a failed
# decrypt is retried once: in the installed app a read of a valid file was seen to
# fail once and succeed a moment later.

_dpapi_lock = threading.Lock()
_api = None


def _crypt_api():
    global _api
    if _api is None:
        import ctypes
        from ctypes import wintypes

        class BLOB(ctypes.Structure):
            _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

        crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        sig = [ctypes.POINTER(BLOB), wintypes.LPCWSTR, ctypes.POINTER(BLOB), ctypes.c_void_p,
               ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(BLOB)]
        protect = crypt32.CryptProtectData
        protect.argtypes, protect.restype = sig, wintypes.BOOL
        unprotect = crypt32.CryptUnprotectData
        unprotect.argtypes = [ctypes.POINTER(BLOB), ctypes.c_void_p, *sig[2:]]
        unprotect.restype = wintypes.BOOL
        kernel32.LocalFree.argtypes, kernel32.LocalFree.restype = [ctypes.c_void_p], ctypes.c_void_p
        _api = (ctypes, BLOB, protect, unprotect, kernel32.LocalFree)
    return _api


def _dpapi_once(data: bytes, entropy: bytes, protect: bool) -> bytes:
    ctypes, BLOB, protect_fn, unprotect_fn, local_free = _crypt_api()
    # Keep the buffers referenced until the call returns.
    data_buf = ctypes.create_string_buffer(data, len(data))
    ent_buf = ctypes.create_string_buffer(entropy, len(entropy))
    inp = BLOB(len(data), ctypes.cast(data_buf, ctypes.POINTER(ctypes.c_char)))
    ent = BLOB(len(entropy), ctypes.cast(ent_buf, ctypes.POINTER(ctypes.c_char)))
    out = BLOB()
    fn = protect_fn if protect else unprotect_fn
    ok = fn(ctypes.byref(inp), None, ctypes.byref(ent), None, None, 0x1, ctypes.byref(out))
    if not ok:
        raise CredentialError(f"DPAPI {'encrypt' if protect else 'decrypt'} failed "
                              f"(Windows error {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        local_free(ctypes.cast(out.pbData, ctypes.c_void_p))


def _dpapi(data: bytes, entropy: bytes, protect: bool) -> bytes:
    with _dpapi_lock:
        try:
            return _dpapi_once(data, entropy, protect)
        except CredentialError:
            if protect:
                raise
            return _dpapi_once(data, entropy, protect)  # one retry before giving up


def _is_windows() -> bool:
    return sys.platform == "win32"


def _dev_store_allowed() -> bool:
    return os.environ.get("DIELIFY_INSECURE_DEV_STORE") == "1"


# --- Public API -------------------------------------------------------------

# Stores: "credentials" = YouTube sign-ins per profile; "server_users" = logins
# that phone apps use for the Subsonic API.
def _cred_dir(store: str = "credentials") -> Path:
    d = app_data_dir() / store
    d.mkdir(parents=True, exist_ok=True)
    return d


def _entropy(profile: str, store: str, prefix: bytes = _ENTROPY_PREFIX) -> bytes:
    # Binds each file to its name and store, so files can't be swapped between them.
    suffix = b"" if store == "credentials" else b":" + store.encode("utf-8")
    return prefix + profile.encode("utf-8") + suffix


def _cred_path(profile: str, store: str = "credentials") -> Path:
    return _cred_dir(store) / f"{safe_name(profile)}.dpapi"


def save(profile: str, auth: dict, store: str = "credentials") -> Path:
    payload = json.dumps(auth).encode("utf-8")
    entropy = _entropy(profile, store)
    if _is_windows():
        blob = b"DPAPI1" + _dpapi(payload, entropy, protect=True)
    elif _dev_store_allowed():
        blob = b"INSECURE-DEV" + base64.b64encode(payload)
    else:
        raise CredentialError(
            "Refusing to store credentials unencrypted on this OS. Dielify's credential "
            "store uses Windows DPAPI. For local development only, set "
            "DIELIFY_INSECURE_DEV_STORE=1.")
    path = _cred_path(profile, store)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(blob)
    if not _is_windows():
        os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def load(profile: str, store: str = "credentials") -> dict | None:
    path = _cred_path(profile, store)
    if not path.exists():
        return None
    blob = path.read_bytes()
    entropy = _entropy(profile, store)
    if blob.startswith(b"DPAPI1"):
        if not _is_windows():
            raise CredentialError("These credentials were encrypted on Windows.")
        try:
            payload = _dpapi(blob[6:], entropy, protect=False)
        except CredentialError:
            # Saved before the rename to Dielify: open it the old way, re-save the new way.
            legacy = _entropy(profile, store, _LEGACY_ENTROPY_PREFIX)
            payload = _dpapi(blob[6:], legacy, protect=False)
            save(profile, json.loads(payload), store)
    elif blob.startswith(b"INSECURE-DEV"):
        if not _dev_store_allowed():
            raise CredentialError("Found a development-only credential file; refusing to use it.")
        payload = base64.b64decode(blob[12:])
    else:
        raise CredentialError(f"Unrecognised credential file: {path}")
    return json.loads(payload)


def delete(profile: str, store: str = "credentials") -> bool:
    path = _cred_path(profile, store)
    if path.exists():
        path.unlink()
        return True
    return False


def list_profiles(store: str = "credentials") -> list[str]:
    return sorted(p.stem for p in _cred_dir(store).glob("*.dpapi"))
