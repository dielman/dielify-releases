"""PC-only endpoints (/api/desktop/...) for the desktop app's settings screens.

Only the desktop window's own key works here (see auth.enable_desktop_token);
phones and other devices get 403.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from . import __version__, auth, credstore, winint
from . import settings as settings_mod
from .custom_api import Session, desktop_session, youtube
from .library import Library
from .paths import app_data_dir, safe_name

router = APIRouter(prefix="/api/desktop", tags=["desktop"])


class ProfileInfo(BaseModel):
    name: str
    youtube_signed_in: bool
    library_path: str
    tracks: int


class PhoneDevice(BaseModel):
    id: int
    device_name: str
    created_at: float
    last_used_at: float | None


class PhoneUser(BaseModel):
    name: str
    profile: str
    devices: list[PhoneDevice]


class DesktopStatus(BaseModel):
    version: str
    data_folder: str
    log_file: str
    active_profile: str
    profiles: list[ProfileInfo]
    library_root: str
    quality: str
    preferred_format: str
    cache_limit_gb: float
    offline: bool
    keep_awake: bool
    start_with_windows: bool
    server_port: int
    addresses: list[str] = Field(description="Addresses phones can use")
    phone_users: list[PhoneUser]
    backup_folder: str = Field("", description='"" = backups off')
    backup_suggested: str = Field("", description="A sensible folder to offer when backups are off")
    last_backup: str | None = None
    last_backup_at: float | None = None
    backup_error: str | None = None


class DesktopChange(BaseModel):
    library_root: str | None = None
    active_profile: str | None = None
    quality: Literal["auto", "high", "standard"] | None = None
    preferred_format: Literal["auto", "m4a", "opus"] | None = None
    cache_limit_gb: float | None = Field(None, ge=0)
    offline: bool | None = None
    keep_awake: bool | None = None
    start_with_windows: bool | None = None
    backup_folder: str | None = Field(None, description='"" turns backups off')


class NewProfile(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class NewPhoneUser(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    profile: str | None = None


class PhoneLogin(BaseModel):
    name: str
    profile: str
    password: str = Field(description="Shown once; type it into the phone app")


class ScanResult(BaseModel):
    added: int
    updated: int
    removed: int
    unchanged: int
    errors: list[str]


def _profiles(s: settings_mod.Settings) -> list[str]:
    """Profiles: sign-in files, the active one, and folders in the music folder. Windows
    names ignore case, so "josh" (a folder) and "Josh" (the sign-in) are one profile, named
    as the sign-in / settings have it (checking "josh" against Josh.dpapi failed: the file
    is locked to its exact name)."""
    names: dict[str, str] = {}
    for n in [*credstore.list_profiles(), s.active_profile]:
        names.setdefault(n.casefold(), n)
    root = Path(s.library_root)
    if root.exists():
        for p in root.iterdir():
            if p.is_dir() and not p.name.startswith("."):
                names.setdefault(p.name.casefold(), p.name)
    return sorted(names.values(), key=str.casefold)


def _signed_in(profile: str) -> bool:
    """A login file that can't be read counts as signed out (and is logged), so one bad
    file can't break every screen."""
    try:
        return credstore.load(profile) is not None
    except credstore.CredentialError as e:
        import logging
        logging.getLogger(__name__).warning("Can't read the YouTube sign-in of %s: %s", profile, e)
        return False


def _status() -> DesktopStatus:
    from .server import bind_addresses
    s = settings_mod.load()
    profiles = []
    for name in _profiles(s):
        lib = Library(name, s.profile_library(name))
        profiles.append(ProfileInfo(name=name, youtube_signed_in=_signed_in(name),
                                    library_path=str(lib.root), tracks=lib.stats()["tracks"]))
    users = [PhoneUser(name=u.name, profile=u.profile,
                       devices=[PhoneDevice(**{k: d[k] for k in ("id", "device_name", "created_at", "last_used_at")})
                                for d in auth.list_tokens(u.name)])
             for u in auth.list_users()]
    from . import backup
    folder = Path(s.backup_folder) if s.backup_folder else None
    last = backup.last_backup(folder) if folder else None
    root = Path(s.library_root) if s.library_root else None
    suggested = str((root.parent if root and root.parent != root else Path.home()) / "Dielify-backups")
    return DesktopStatus(
        backup_folder=s.backup_folder, backup_suggested=suggested,
        last_backup=str(last) if last else None, last_backup_at=last.stat().st_mtime if last else None,
        backup_error=backup.scheduler.last_error,
        version=__version__, data_folder=str(app_data_dir()),
        log_file=str(app_data_dir() / "logs" / "server.log"),
        active_profile=s.active_profile, profiles=profiles,
        library_root=s.library_root, quality=s.quality, preferred_format=s.preferred_format,
        cache_limit_gb=s.cache_limit_gb, offline=s.offline, keep_awake=s.keep_awake, start_with_windows=winint.start_with_windows(),
        server_port=s.server_port,
        addresses=[f"http://{a}:{s.server_port}" for a in bind_addresses(s) if not a.startswith("127.")],
        phone_users=users)


@router.get("/status", response_model=DesktopStatus)
def status_(s: Session = Depends(desktop_session)) -> DesktopStatus:
    return _status()


@router.put("/settings", response_model=DesktopStatus)
def change(body: DesktopChange, s: Session = Depends(desktop_session)) -> DesktopStatus:
    changes = body.model_dump(exclude_none=True)
    if "start_with_windows" in changes:
        winint.set_start_with_windows(changes.pop("start_with_windows"))
    if "library_root" in changes:
        root = Path(changes["library_root"]).expanduser()
        if not root.is_absolute():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a full folder path, e.g. D:\\Music")
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Can't use that folder: {e}") from e
    if changes.get("backup_folder"):
        folder = Path(changes["backup_folder"]).expanduser()
        if not folder.is_absolute():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a full folder path, e.g. E:\\Dielify-backups")
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Can't use that folder: {e}") from e
        changes["backup_folder"] = str(folder)
    if "active_profile" in changes and safe_name(changes["active_profile"]) != changes["active_profile"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Profile names: letters, digits, - and _ only")
    for key, value in changes.items():
        settings_mod.set_value(key, str(value))
    if changes.get("backup_folder"):
        from . import backup
        backup.scheduler.run_once()  # first backup straight away
    if "library_root" in changes or "active_profile" in changes:
        cfg = settings_mod.load()
        Library(cfg.active_profile, cfg.profile_library()).scan()
    return _status()


@router.post("/backup", response_model=DesktopStatus)
def backup_now(s: Session = Depends(desktop_session)) -> DesktopStatus:
    from . import backup
    cfg = settings_mod.load()
    if not cfg.backup_folder:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a backup folder first")
    try:
        backup.make_backup(Path(cfg.backup_folder))
        backup.scheduler.last_error = None
    except Exception as e:
        backup.scheduler.last_error = f"{type(e).__name__}: {e}"
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Backup failed: {e}") from e
    return _status()


@router.post("/profiles", response_model=DesktopStatus)
def add_profile(body: NewProfile, s: Session = Depends(desktop_session)) -> DesktopStatus:
    if safe_name(body.name) != body.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Profile names: letters, digits, - and _ only")
    cfg = settings_mod.load()
    cfg.profile_library(body.name).mkdir(parents=True, exist_ok=True)
    settings_mod.set_value("active_profile", body.name)
    return _status()


@router.delete("/youtube/{profile}", response_model=DesktopStatus)
def youtube_sign_out(profile: str, s: Session = Depends(desktop_session)) -> DesktopStatus:
    credstore.delete(profile)
    youtube.reset()
    return _status()


@router.post("/scan", response_model=ScanResult)
def scan(s: Session = Depends(desktop_session)) -> ScanResult:
    res = s.lib.scan()
    return ScanResult(added=res.added, updated=res.updated, removed=res.removed,
                      unchanged=res.unchanged, errors=res.errors)


@router.post("/phone-users", response_model=PhoneLogin)
def add_phone_user(body: NewPhoneUser, s: Session = Depends(desktop_session)) -> PhoneLogin:
    try:
        u = auth.add_user(body.name, body.profile or s.user.profile)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return PhoneLogin(name=u.name, profile=u.profile, password=u.password)


@router.post("/phone-users/{name}/password", response_model=PhoneLogin)
def new_phone_password(name: str, s: Session = Depends(desktop_session)) -> PhoneLogin:
    if auth.get_user(name) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such phone login")
    u = auth.set_password(name)
    return PhoneLogin(name=u.name, profile=u.profile, password=u.password)


@router.delete("/phone-users/{name}", status_code=204)
def remove_phone_user(name: str, s: Session = Depends(desktop_session)) -> Response:
    if not auth.remove_user(name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such phone login")
    return Response(status_code=204)


@router.delete("/devices/{device_id}", status_code=204)
def remove_device(device_id: int, s: Session = Depends(desktop_session)) -> Response:
    if not auth.revoke_token(device_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such device")
    return Response(status_code=204)


# --- updates (installed app only; see updater.py) --------------------------------------

class UpdateInfo(BaseModel):
    current: str
    latest: str | None
    available: bool
    notes: str | None
    size: int | None
    configured: bool
    checked_at: float | None
    error: str | None
    installing: bool


@router.get("/update", response_model=UpdateInfo)
def update_status(s: Session = Depends(desktop_session)) -> UpdateInfo:
    from .updater import updater
    return UpdateInfo(**updater.as_dict())


@router.post("/update/check", response_model=UpdateInfo)
def update_check(s: Session = Depends(desktop_session)) -> UpdateInfo:
    from .updater import updater
    updater.check()
    return UpdateInfo(**updater.as_dict())


@router.post("/update/install", response_model=UpdateInfo)
def update_install(s: Session = Depends(desktop_session)) -> UpdateInfo:
    """Download + verify, start the installer; Dielify then closes and restarts updated."""
    from .updater import UpdateError, updater
    try:
        updater.install()
    except (UpdateError, OSError) as e:  # OSError includes download/network errors
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return UpdateInfo(**updater.as_dict())
