"""PC-only endpoints (/api/desktop/...) for the desktop app's settings screens.

Only the desktop window's own key works here (see auth.enable_desktop_token);
phones and other devices get 403.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from . import __version__, auth, credstore, winint
from . import settings as settings_mod
from .custom_api import Session, desktop_session, youtube
from . import library as library_mod
from .library import library_for
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


class PersonInfo(BaseModel):
    name: str
    role: Literal["parent", "child"]
    store: str = Field(description="Whose music folder (and YouTube sign-in) this person uses")
    tracks: int = Field(description="Songs in their library")
    logins: list[str] = Field(description="Their phone logins")
    waiting: int = Field(0, description="Download requests waiting for a parent's OK")


class NewPerson(BaseModel):
    name: str = Field(min_length=1, max_length=40)


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
    people: list[PersonInfo] = Field(default_factory=list, description="Everyone sharing this PC's music")
    backup_folder: str = Field("", description='"" = backups off')
    backup_suggested: str = Field("", description="A sensible folder to offer when backups are off")
    last_backup: str | None = None
    last_backup_at: float | None = None
    backup_error: str | None = None
    setup_needed: bool = Field(False, description="Show the first-start wizard")


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


def _waiting(profile: str) -> int:
    from .library import connect
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM downloads WHERE profile = ? AND status = 'approval'",
                            (profile,)).fetchone()[0]


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
        lib = library_for(name, s)
        profiles.append(ProfileInfo(name=name, youtube_signed_in=_signed_in(name),
                                    library_path=str(lib.root), tracks=lib.stats()["tracks"]))
    users = [PhoneUser(name=u.name, profile=u.profile,
                       devices=[PhoneDevice(**{k: d[k] for k in ("id", "device_name", "created_at", "last_used_at")})
                                for d in auth.list_tokens(u.name)])
             for u in auth.list_users()]
    store = library_mod.person(s.active_profile)["store"]
    people = [PersonInfo(name=p["profile"], role=p["role"], store=p["store"],
                         tracks=library_for(p["profile"], s).stats()["tracks"],
                         logins=[u.name for u in users if u.profile.casefold() == p["profile"].casefold()],
                         waiting=_waiting(p["profile"]) if p["role"] == "child" else 0)
              for p in library_mod.people() if p["store"].casefold() == store.casefold()]
    from . import backup
    folder = Path(s.backup_folder) if s.backup_folder else None
    last = backup.last_backup(folder) if folder else None
    suggested = str(backup.suggested_folder(s))
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
        phone_users=users, people=people, setup_needed=setup_needed(s))


# --- first start ---------------------------------------------------------------------------
def setup_needed(s: settings_mod.Settings | None = None) -> bool:
    """A new install: nobody has finished the wizard, there is no YouTube sign-in and no song.
    (Installs from before the wizard have a sign-in or songs, so they never see it.)"""
    s = s or settings_mod.load()
    if s.setup_done or credstore.list_profiles():
        return False
    with library_mod.connect() as conn:
        return conn.execute("SELECT 1 FROM tracks LIMIT 1").fetchone() is None


class SetupName(BaseModel):
    name: str = Field(min_length=1, max_length=40)


@router.post("/setup/name", response_model=DesktopStatus)
def setup_name(body: SetupName, s: Session = Depends(desktop_session)) -> DesktopStatus:
    """The wizard's "What's your name?": renames the empty first profile ("default")."""
    name = body.name.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use letters and numbers (and - or _), no spaces")
    if not setup_needed():
        raise HTTPException(status.HTTP_409_CONFLICT, "Dielify is already set up: add people in Settings > People & phones")
    cfg = settings_mod.load()
    old = cfg.active_profile
    if old.casefold() != name.casefold():
        with library_mod.connect() as conn:  # the old name was never used: nothing to carry over
            conn.execute("DELETE FROM people WHERE profile = ? COLLATE NOCASE", (old,))
        try:
            cfg.profile_library(old).rmdir()  # only if empty
        except OSError:
            pass
    cfg.profile_library(name).mkdir(parents=True, exist_ok=True)
    settings_mod.set_value("active_profile", name)
    return _status()


@router.post("/setup/done", response_model=DesktopStatus)
def setup_done(s: Session = Depends(desktop_session)) -> DesktopStatus:
    settings_mod.set_value("setup_done", "true")
    return _status()


class RestoredPerson(BaseModel):
    name: str
    role: str
    songs: int
    youtube: bool | None = Field(None, description="Their YouTube sign-in works on this PC (parents only)")


class Restored(BaseModel):
    people: list[RestoredPerson]
    songs: int
    files_found: int
    playlists: int
    plays: int
    library_root: str
    phone_logins: int
    phone_logins_readable: int = Field(description="How many still work here (DPAPI: same PC + Windows user)")


@router.get("/setup/restored", response_model=Restored)
def restored(s: Session = Depends(desktop_session)) -> Restored:
    """What came back from a backup (the wizard's last page after a restore)."""
    cfg = settings_mod.load()
    people, found, total = [], 0, 0
    for p in library_mod.people():
        lib = library_for(p["profile"], cfg)
        youtube_ok = None
        if p["role"] == "parent":
            try:
                youtube_ok = bool(credstore.load(p["profile"]))
            except Exception:  # noqa: BLE001 - another PC / Windows user: DPAPI can't read it
                youtube_ok = False
        people.append(RestoredPerson(name=p["profile"], role=p["role"], songs=lib.stats()["tracks"], youtube=youtube_ok))
    with library_mod.connect() as conn:
        stores = {p["store"] for p in library_mod.people()} or {cfg.active_profile}
        for store in stores:
            lib = library_for(store, cfg)
            for t in conn.execute("SELECT * FROM tracks WHERE profile = ? COLLATE NOCASE", (store,)):
                total += 1
                found += lib.path_of(t).exists()
        playlists = conn.execute("SELECT COUNT(*) FROM playlists").fetchone()[0]
        plays = conn.execute("SELECT COUNT(*) FROM plays").fetchone()[0]
    logins, readable = len(credstore.list_profiles(auth.STORE)), len(auth.list_users())
    return Restored(people=people, songs=total, files_found=found, playlists=playlists, plays=plays,
                    library_root=cfg.library_root, phone_logins=logins, phone_logins_readable=readable)


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
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Names can use letters, numbers, - and _ only")
    for key, value in changes.items():
        settings_mod.set_value(key, str(value))
    if "backup_folder" in changes:  # a choice, incl. "off": never turned on by default again
        settings_mod.set_value("backup_chosen", "true")
    if changes.get("backup_folder"):
        from . import backup
        backup.scheduler.run_once()  # first backup straight away
    if "library_root" in changes or "active_profile" in changes:
        cfg = settings_mod.load()
        library_for(cfg.active_profile, cfg).scan()
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
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Names can use letters, numbers, - and _ only")
    cfg = settings_mod.load()
    cfg.profile_library(body.name).mkdir(parents=True, exist_ok=True)
    settings_mod.set_value("active_profile", body.name)
    return _status()


@router.post("/people", response_model=PhoneLogin)
def add_child(body: NewPerson, s: Session = Depends(desktop_session)) -> PhoneLogin:
    """A kids account: shares this PC's music folder and YouTube sign-in (behind the
    scenes), has its own library, and a phone login of the same name."""
    name = body.name.strip()
    if safe_name(name) != name or not name.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Names can use letters, numbers, - and _ only")
    cfg = settings_mod.load()
    taken = {n.casefold() for n in _profiles(cfg)} | {p["profile"].casefold() for p in library_mod.people()}
    taken |= {u.name.casefold() for u in auth.list_users()}
    if name.casefold() in taken:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{name} is already used on this PC; choose another name")
    store = library_mod.person(cfg.active_profile)["store"]
    library_mod.set_person(name, "child", store=store)
    try:
        u = auth.add_user(name, name)
    except ValueError as e:
        library_mod.forget_person(name)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return PhoneLogin(name=u.name, profile=u.profile, password=u.password)


@router.delete("/people/{name}", status_code=204)
def remove_child(name: str, s: Session = Depends(desktop_session)) -> Response:
    """Remove a kids account: its phone logins, library, history and playlists. Music
    files stay (songs only they had show under Household)."""
    p = next((p for p in library_mod.people() if p["profile"].casefold() == name.casefold()), None)
    if p is None or p["role"] != "child":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such kids account")
    for u in auth.list_users():
        if u.profile.casefold() == p["profile"].casefold():
            auth.remove_user(u.name)
    library_mod.forget_person(p["profile"])
    return Response(status_code=204)


# --- kids accounts: the parent's controls, approvals, stats -------------------------------

class KidControls(BaseModel):
    explicit: Literal["block", "allow"] = "block"
    clean_versions: bool = True
    lyrics_check: bool = True
    extra_words: list[str] = []
    downloads: Literal["auto", "approve"] = "auto"
    daily_limit: int = Field(50, ge=0, le=1000)
    youtube_search: bool = True
    discovery_play: bool = True
    blocked_artists: list[str] = []
    blocked_songs: list[dict] = []
    quiet_hours: bool = False
    quiet_from: str = Field("21:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    quiet_to: str = Field("07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    parent_sees_stats: bool = False
    blend: bool = Field(False, description="May make a Blend with someone in the household")
    jam: bool = Field(True, description="May join a Jam (every song in it is filtered for her)")
    picks: list[dict] = Field([], description="The parent's picks: YouTube items (album, artist, playlist, song)")


def _child(name: str) -> dict:
    p = next((p for p in library_mod.people() if p["profile"].casefold() == name.casefold()), None)
    if p is None or p["role"] != "child":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such kids account")
    return p


@router.get("/people/{name}/controls", response_model=KidControls)
def get_controls(name: str, s: Session = Depends(desktop_session)) -> KidControls:
    from . import kids
    from dataclasses import asdict
    return KidControls(**asdict(kids.load(_child(name)["profile"])))


@router.put("/people/{name}/controls", response_model=KidControls)
def put_controls(name: str, body: KidControls, s: Session = Depends(desktop_session)) -> KidControls:
    from . import kids, kids_home
    from dataclasses import asdict
    profile = _child(name)["profile"]
    try:
        c = kids.save(profile, kids.Controls.from_dict(body.model_dump()))
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    kids_home.forget(profile)
    import threading
    from . import blend
    threading.Thread(target=blend.rebuild_all, daemon=True, name="dielify-blend").start()  # Blend allowed / not
    return KidControls(**asdict(c))


class Approval(BaseModel):
    id: int
    person: str
    title: str
    artist: str | None
    video_id: str
    requested_at: float


class ApprovalList(BaseModel):
    approvals: list[Approval]


class Decision(BaseModel):
    ids: list[int] = Field(min_length=1)
    allow: bool


@router.get("/approvals", response_model=ApprovalList)
def approvals(request: Request, s: Session = Depends(desktop_session)) -> ApprovalList:
    kids_ = [p["profile"] for p in library_mod.people() if p["role"] == "child" and p["store"] == s.lib.store]
    return ApprovalList(approvals=[Approval(id=j["id"], person=j["profile"], title=j["title"], artist=j["artist"],
                                            video_id=j["video_id"], requested_at=j["created_at"])
                                   for j in request.app.state.queue.approvals(kids_)])


@router.post("/approvals", response_model=ApprovalList)
def decide(body: Decision, request: Request, s: Session = Depends(desktop_session)) -> ApprovalList:
    request.app.state.queue.decide(body.ids, body.allow)
    return approvals(request, s)


@router.get("/people/{name}/stats")
def kid_stats(name: str, period: Literal["week", "month", "year", "all"] = "month",
              limit: int = Query(10, ge=1, le=50), s: Session = Depends(desktop_session)):
    """A kids account's stats, if its controls let the parent see them."""
    from . import kids
    from .custom_api import get_stats
    p = _child(name)
    if not kids.load(p["profile"]).parent_sees_stats:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"{p['profile']}'s stats are private (Controls)")
    return get_stats(period, limit, Session(auth.ServerUser(p["profile"], p["profile"], ""), 0))


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


# --- 0.9.10: the PC installs app updates on the TVs (tvupdate.py) ------------------------------

class Tv(BaseModel):
    address: str
    name: str
    last_seen: float | None = None
    version_code: int | None = Field(None, description="Dielify's version on the TV when last checked")
    result: str | None = Field(None, description="What happened last time the PC checked it")
    checked: float | None = None


class Tvs(BaseModel):
    tvs: list[Tv]
    app_version: str | None = Field(None, description="The TV app this PC carries")
    adb: bool = Field(description="False: the Android tools (adb) aren't on this PC, so it can't update TVs")


def _tvs() -> Tvs:
    from . import appshare, tvupdate
    app = appshare.available()
    return Tvs(tvs=[Tv(address=ip, **{k: v.get(k) for k in ("name", "last_seen", "version_code", "result", "checked")})
                    for ip, v in sorted(tvupdate.known().items())],
               app_version=app["version"] if app else None, adb=tvupdate.find_adb() is not None)


@router.get("/tvs", response_model=Tvs)
def tvs(s: Session = Depends(desktop_session)) -> Tvs:
    """The TVs this PC knows (every TV that connected), for Settings > People & phones."""
    return _tvs()


@router.post("/tvs/update", response_model=Tvs)
def tvs_update(s: Session = Depends(desktop_session)) -> Tvs:
    """Install the TV app this PC carries on every TV that's older (not ones playing music)."""
    from . import tvupdate
    from .remote import tv_playing
    tvupdate.update_all(tv_playing)
    return _tvs()


@router.delete("/tvs/{address}", status_code=204)
def tvs_forget(address: str, s: Session = Depends(desktop_session)) -> Response:
    from . import tvupdate
    if not tvupdate.forget(address):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such TV")
    return Response(status_code=204)
