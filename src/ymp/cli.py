"""`ymp` command line — the Phase 1 interface.

    ymp doctor                     check FFmpeg, Deno, library versions
    ymp config show | set K V      settings (library folder, quality, ...)
    ymp auth login|status|logout   YouTube Music sign-in for a profile
    ymp search "query"             search songs
    ymp download VIDEO_ID ...      download by video id
    ymp get "query"                search, pick a result, download it
    ymp inspect FILE               show a file's tags
    ymp library scan | stats       index the music folder (Phase 2)
    ymp server user add|list|...   logins for phone apps (Subsonic)
    ymp serve                      serve the library on the home network
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__, credstore
from . import settings as settings_mod
from .yt_adapter import NotSignedIn, TrackInfo, YouTubeError


def _out(msg: str = "") -> None:
    print(msg, flush=True)


def _fmt_dur(s: int | None) -> str:
    return f"{s // 60}:{s % 60:02d}" if s else "--:--"


def _profile(args) -> str:
    return args.profile or settings_mod.load().active_profile


def _adapter(args, require_login: bool = True):
    from .yt_adapter import YTMusicAdapter
    s = settings_mod.load()
    auth = credstore.load(_profile(args))
    if auth is None and require_login:
        raise NotSignedIn(f"Profile '{_profile(args)}' is not signed in. Run: ymp auth login")
    return YTMusicAdapter(auth=auth, request_delay_s=s.request_delay_s)


# --- commands ---------------------------------------------------------------

def cmd_doctor(args) -> int:
    from .yt_adapter import check_runtime
    rt = check_runtime()
    s = settings_mod.load()
    ok = True
    _out(f"ymp {__version__}   Python {sys.version.split()[0]}")
    for name in ("yt-dlp", "ytmusicapi", "mutagen"):
        _out(f"  [ok]  {name:<11} {rt[name]}")
    for name, why in (("ffmpeg", "needed to remux audio"), ("ffprobe", "ships with FFmpeg")):
        if rt[name]:
            _out(f"  [ok]  {name:<11} {rt[name]}")
        else:
            ok = False
            _out(f"  [!!]  {name:<11} NOT FOUND — {why}. See README step 3.")
    if rt["deno"]:
        _out(f"  [ok]  {'deno':<11} {rt['deno']}")
    else:
        ok = False
        _out("  [!!]  deno        NOT FOUND — yt-dlp needs it for YouTube. "
             "Install: winget install --id=DenoLand.Deno")
    lib = Path(s.library_root)
    _out(f"  [..]  library     {lib}  ({'exists' if lib.exists() else 'will be created'})")
    profiles = credstore.list_profiles()
    _out(f"  [..]  profiles    {', '.join(profiles) or '(none signed in)'}"
         f"   active: {s.active_profile}")
    _out("\nAll good." if ok else "\nFix the [!!] items above, then run ymp doctor again.")
    return 0 if ok else 1


def cmd_config_show(args) -> int:
    s = settings_mod.load()
    _out(f"Settings file: {settings_mod.settings_path()}")
    for k, v in asdict(s).items():
        _out(f"  {k:<17} {v}")
    _out(f"  {'(this profile)':<17} {s.profile_library(_profile(args))}")
    return 0


def cmd_config_set(args) -> int:
    s = settings_mod.set_value(args.key, args.value)
    _out(f"{args.key} = {getattr(s, args.key)}")
    return 0


def _read_headers(args) -> str:
    if args.file:
        return Path(args.file).read_text(encoding="utf-8")
    if args.clipboard:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        try:
            return root.clipboard_get()
        finally:
            root.destroy()
    _out("Paste the request headers copied from your browser, then press Enter on an")
    _out("empty line (see README 'Sign in' for where to copy them from):\n")
    lines = []
    for line in sys.stdin:
        if not line.strip() and lines:
            break
        lines.append(line.rstrip("\r\n"))
    return "\n".join(lines)


def cmd_auth_login(args) -> int:
    from .yt_adapter import YTMusicAdapter, parse_browser_headers
    profile = _profile(args)
    auth = parse_browser_headers(_read_headers(args))
    s = settings_mod.load()
    name = YTMusicAdapter(auth=auth, request_delay_s=s.request_delay_s).account_name()
    path = credstore.save(profile, auth)
    _out(f"Signed in as {name} (profile '{profile}'). Credentials encrypted at {path}")
    if args.file:
        _out(f"Your headers file still contains your sign-in cookies. Delete it now:\n"
             f"  del \"{Path(args.file).resolve()}\"")
    return 0


def cmd_auth_status(args) -> int:
    profile = _profile(args)
    if credstore.load(profile) is None:
        _out(f"Profile '{profile}': not signed in.")
        return 1
    _out(f"Profile '{profile}': signed in as {_adapter(args).account_name()}")
    return 0


def cmd_auth_logout(args) -> int:
    profile = _profile(args)
    _out(f"Removed sign-in for '{profile}'." if credstore.delete(profile)
         else f"Profile '{profile}' was not signed in.")
    return 0


def _print_results(results: list[TrackInfo]) -> None:
    for i, r in enumerate(results, 1):
        album = f" — {r.album}" if r.album else ""
        _out(f"{i:>3}. {r.title} · {r.artist}{album}  [{_fmt_dur(r.duration_s)}]  id={r.video_id}")


def cmd_search(args) -> int:
    results = _adapter(args, require_login=False).search(" ".join(args.query),
                                                          args.limit, args.videos)
    if not results:
        _out("No results.")
        return 1
    _print_results(results)
    return 0


def _progress_printer():
    last = {"pct": -10}

    def hook(d: dict) -> None:
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                pct = int(d.get("downloaded_bytes", 0) * 100 / total)
                if pct >= last["pct"] + 10:
                    last["pct"] = pct
                    print(f"\r  downloading… {pct:3d}%", end="", flush=True)
        elif d.get("status") == "finished":
            print("\r  downloaded, tagging…      ", flush=True)
    return hook


def _download_ids(args, ids: list[str]) -> int:
    from .downloader import download_track
    from .tagging import read_tags
    adapter = _adapter(args)
    s = settings_mod.load()
    failures = 0
    for vid in ids:
        _out(f"→ {vid}")
        try:
            res = download_track(adapter, vid, s, _profile(args), _progress_printer(),
                                 overwrite=args.overwrite)
        except YouTubeError as e:
            failures += 1
            _out(f"  FAILED: {e}")
            continue
        tags = read_tags(res.path)
        note = " (already in library — skipped)" if res.already_existed else ""
        _out(f"  {res.info.artist} — {res.info.title}{note}")
        _out(f"  {tags['format']}, {tags['bitrate_kbps']} kbps, {_fmt_dur(int(tags['length_s']))},"
             f" cover {tags['cover_bytes'] // 1024} KB")
        _out(f"  {res.path}")
    return 1 if failures else 0


def cmd_download(args) -> int:
    return _download_ids(args, args.video_ids)


def cmd_get(args) -> int:
    results = _adapter(args).search(" ".join(args.query), args.limit)
    if not results:
        _out("No results.")
        return 1
    if args.first:
        choice = results[0]
    else:
        _print_results(results)
        raw = input(f"\nWhich one? [1-{len(results)}, Enter = 1, q = quit] ").strip()
        if raw.lower() == "q":
            return 0
        try:
            choice = results[int(raw or "1") - 1]
        except (ValueError, IndexError):
            _out("Not a valid choice.")
            return 1
    return _download_ids(args, [choice.video_id])


def cmd_inspect(args) -> int:
    from .tagging import read_tags
    for k, v in read_tags(Path(args.file)).items():
        _out(f"  {k:<13} {v}")
    return 0


def _library(args):
    from .library import Library
    s = settings_mod.load()
    return Library(_profile(args), s.profile_library(_profile(args)))


def cmd_library_scan(args) -> int:
    lib = _library(args)
    _out(f"Scanning {lib.root} …")
    res = lib.scan()
    _out(f"  added {res.added}, updated {res.updated}, removed {res.removed}, "
         f"unchanged {res.unchanged}")
    for err in res.errors:
        _out(f"  could not read: {err}")
    return cmd_library_stats(args)


def cmd_library_stats(args) -> int:
    st = _library(args).stats()
    _out(f"Profile '{_profile(args)}': {st['tracks']} tracks, {st['albums']} albums, "
         f"{st['artists']} artists, {st['bytes'] / 1e9:.2f} GB")
    return 0


def _show_new_password(user) -> None:
    _out(f"  user:     {user.name}   (plays profile '{user.profile}')")
    _out(f"  password: {user.password}")
    _out("Type this password into the phone app now; ymp won't show it again.")
    _out("(It's stored encrypted on this PC. Reset it any time with: "
         f"ymp server user password {user.name})")


def cmd_user_add(args) -> int:
    from . import auth
    _show_new_password(auth.add_user(args.name, args.profile or args.name))
    return 0


def cmd_user_password(args) -> int:
    from . import auth
    if auth.get_user(args.name) is None:
        raise ValueError(f"No server user '{args.name}'")
    _show_new_password(auth.set_password(args.name))
    return 0


def cmd_user_list(args) -> int:
    from . import auth
    users = auth.list_users()
    for u in users:
        _out(f"  {u.name:<16} profile '{u.profile}'")
    if not users:
        _out("No server users yet. Add one: ymp server user add josh")
    return 0


def cmd_user_remove(args) -> int:
    from . import auth
    _out(f"Removed '{args.name}'." if auth.remove_user(args.name) else f"No server user '{args.name}'.")
    return 0


def cmd_serve(args) -> int:
    from . import auth, server
    s = settings_mod.load()
    if args.port:
        s.server_port = args.port
    if args.bind:
        s.server_bind = args.bind
    s.validate()  # refuses 0.0.0.0 and public addresses
    users = auth.list_users()
    if not users:
        _out("No server users yet, so no phone app could sign in. First run:")
        _out("  ymp server user add josh")
        return 1
    for u in users:
        res = _library_for(u.profile).scan()
        _out(f"Library '{u.profile}': +{res.added} ~{res.updated} -{res.removed} "
             f"(={res.unchanged}) — {_library_for(u.profile).stats()['tracks']} tracks")
    addrs = server.bind_addresses(s)
    _out()
    _out(f"ymp {__version__} serving on port {s.server_port}. In the phone app, use:")
    for a in addrs:
        where = "this PC only" if a.startswith("127.") else (
            "Tailscale" if a.startswith("100.") else "home network")
        _out(f"  http://{a}:{s.server_port}    ({where})")
    _out(f"Users: {', '.join(u.name for u in users)}.  Stop with Ctrl+C.")
    _out()
    _log_to_file()
    server.run(s, addrs)
    return 0


def cmd_openapi(args) -> int:
    import json

    from .server import create_app
    spec = json.dumps(create_app().openapi(), indent=2, ensure_ascii=False) + "\n"
    if args.out:
        Path(args.out).write_text(spec, encoding="utf-8")
        _out(f"Wrote {args.out}")
    else:
        sys.stdout.write(spec)
    return 0


def _log_to_file() -> None:
    """Server requests -> console and %LOCALAPPDATA%\\ymp\\logs\\server.log (no secrets)."""
    from logging.handlers import RotatingFileHandler

    from .paths import app_data_dir
    logs = app_data_dir() / "logs"
    logs.mkdir(exist_ok=True)
    fh = RotatingFileHandler(logs / "server.log", maxBytes=2_000_000, backupCount=3,
                             encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(fh)
    for name in ("ymp.server", "ymp.subsonic_api"):
        logging.getLogger(name).setLevel(logging.INFO)
    _out(f"Log: {logs / 'server.log'}")


def _library_for(profile: str):
    from .library import Library
    return Library(profile, settings_mod.load().profile_library(profile))


# --- parser -----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ymp", description="Self-hosted YouTube Music player")
    p.add_argument("--version", action="version", version=f"ymp {__version__}")
    p.add_argument("-p", "--profile", help="user profile (default: active_profile setting)")
    p.add_argument("-v", "--verbose", action="store_true", help="show debug output")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="check setup").set_defaults(fn=cmd_doctor)

    c = sub.add_parser("config", help="view or change settings").add_subparsers(dest="sub", required=True)
    c.add_parser("show").set_defaults(fn=cmd_config_show)
    cs = c.add_parser("set", help="e.g. ymp config set library_root D:\\Music")
    cs.add_argument("key")
    cs.add_argument("value")
    cs.set_defaults(fn=cmd_config_set)

    a = sub.add_parser("auth", help="YouTube Music sign-in").add_subparsers(dest="sub", required=True)
    al = a.add_parser("login", help="sign in by pasting browser request headers")
    src = al.add_mutually_exclusive_group()
    src.add_argument("--clipboard", action="store_true", help="read headers from the clipboard")
    src.add_argument("--file", help="read headers from a text file")
    al.set_defaults(fn=cmd_auth_login)
    a.add_parser("status").set_defaults(fn=cmd_auth_status)
    a.add_parser("logout").set_defaults(fn=cmd_auth_logout)

    s = sub.add_parser("search", help="search YouTube Music")
    s.add_argument("query", nargs="+")
    s.add_argument("-n", "--limit", type=int, default=10)
    s.add_argument("--videos", action="store_true", help="search videos instead of songs")
    s.set_defaults(fn=cmd_search)

    d = sub.add_parser("download", help="download tracks by video id")
    d.add_argument("video_ids", nargs="+")
    d.add_argument("--overwrite", action="store_true")
    d.set_defaults(fn=cmd_download)

    g = sub.add_parser("get", help="search, choose, download")
    g.add_argument("query", nargs="+")
    g.add_argument("-n", "--limit", type=int, default=8)
    g.add_argument("--first", action="store_true", help="take the top result without asking")
    g.add_argument("--overwrite", action="store_true")
    g.set_defaults(fn=cmd_get)

    i = sub.add_parser("inspect", help="show an audio file's tags")
    i.add_argument("file")
    i.set_defaults(fn=cmd_inspect)

    lb = sub.add_parser("library", help="music library index").add_subparsers(dest="sub", required=True)
    lb.add_parser("scan", help="index new, changed and removed files").set_defaults(fn=cmd_library_scan)
    lb.add_parser("stats", help="track/album/artist counts").set_defaults(fn=cmd_library_stats)

    sv = sub.add_parser("server", help="server settings").add_subparsers(dest="sub", required=True)
    su = sv.add_parser("user", help="logins for phone apps").add_subparsers(dest="action", required=True)
    ua = su.add_parser("add", help="create a login (prints its password once)")
    ua.add_argument("name")
    ua.add_argument("--profile", help="whose library it plays (default: same as name)")
    ua.set_defaults(fn=cmd_user_add)
    su.add_parser("list").set_defaults(fn=cmd_user_list)
    up = su.add_parser("password", help="make a new password")
    up.add_argument("name")
    up.set_defaults(fn=cmd_user_password)
    ur = su.add_parser("remove")
    ur.add_argument("name")
    ur.set_defaults(fn=cmd_user_remove)
    so = sv.add_parser("openapi", help="print or save the /api contract (OpenAPI JSON)")
    so.add_argument("--out", help="file to write, e.g. docs/openapi.json")
    so.set_defaults(fn=cmd_openapi)

    sr = sub.add_parser("serve", help="serve the library to phone apps (home network/Tailscale)")
    sr.add_argument("--port", type=int, help="override server_port for this run")
    sr.add_argument("--bind", help="override server_bind for this run, e.g. 127.0.0.1")
    sr.set_defaults(fn=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to a legacy code page; song titles need UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    try:
        return args.fn(args)
    except (YouTubeError, credstore.CredentialError, KeyError, ValueError, OSError) as e:
        _out(f"Error: {e}")
        return 2
    except KeyboardInterrupt:
        _out("\nCancelled.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
