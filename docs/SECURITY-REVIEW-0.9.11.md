# Security review, 0.9.11 (10 Nov 2026)

Scope: everything that matters before 1.0. Sign-ins and keys, one person reaching another's data,
kids accounts and the parent's YouTube account, TV sign-in, the PC installing apps on TVs, and what
the PC exposes on the network. Code at phase-8 after 7643cfd.

## Fixed

1. **A kids account could read the parent's YouTube playlists.**
   - The problem: `GET /api/yt/playlist/LM` runs on the parent's sign-in and returned his Liked Music. The
     same worked for his other YouTube playlists if their ids were known.
   - The fix: for kids accounts, `_parents_own_playlist` now refuses Liked Music (LM), Episodes for later (SE),
     personal "My Mix" lists (RDTMAK…) and every playlist in the parent's YouTube library (cached 10 min).
     Public playlists still work.
   - Test: `test_a_kid_never_gets_her_parents_youtube_playlists`.
2. **The PC app's key worked from any address.**
   - It is random per start and kept in memory only, but a copy (from a screenshot of a URL, say) would have
     given PC-only powers from the network.
   - It now only works from 127.0.0.1 / ::1, the desktop window's own address. This applies in `session`,
     `/api/remote` and the error handler.
   - Test: `test_the_pc_apps_key_only_works_on_this_pc`.

## Checked, no problem found

- **Sign-in on every endpoint.**
  - 115 endpoints: 82 need a device key, 6 accept a key in the URL (audio and pictures; logs never record
    query strings), and 23 are PC-only.
  - Only four take no key: login, TV pairing start and poll (by design), and `/api/remote`, which checks
    the key itself.
- **Keys.**
  - Device keys are stored as SHA-256 hashes and can be revoked.
  - Cast keys only play music and last 12 h.
  - Wrong keys count toward the per-address lockout (10 tries in 15 min).
- **Other households.**
  - `tests/test_cross_people.py` has a second parent with their own music try 23 id-based endpoints on
    the first household's songs, albums, artists, playlists, downloads and devices. All were refused, and
    nothing leaked into their lists or searches.
  - The same holds for Subsonic apps: getSong, stream, getAlbum, getCoverArt, download and search3.
- **Kids.**
  - A kid can't delete or change the parent's songs, playlists or downloads, sign out the parent's
    devices, or see his YouTube playlists.
  - A kid can't see or control the parent's devices; a parent can only pause, skip or change the volume
    on a kid's (test_remote).
  - YouTube home, charts and "my playlists" are empty for kids. Their search, albums and radio are public
    catalogue, filtered by their controls.
- **TV sign-in.**
  - The TV's secret is 32 random bytes. Codes are 8 characters, last 10 minutes, at most 5 wait at once,
    and there are 10 starts per address per 10 minutes.
  - Only a parent or the PC app can approve, and only for someone in their household. The key is handed
    over once.
- **The PC installing on TVs (adb).**
  - It passes fixed arguments, never a shell. Addresses come only from TVs that connected and are home
    network IPv4.
  - The app file is served only when its size and SHA-256 match. Android still checks the signature.
- **Network.**
  - The PC never listens on 0.0.0.0 or public addresses (enforced). There is no CORS, so a web page can't
    use the API. mDNS announces the name, port and version on home-network addresses only (not Tailscale).
- **Logs.** No key, password or cookie is logged. The access log has paths only.
- **Updates.** PC updates are Ed25519-signed. Phone and TV updates are SHA-256-checked, then Android
  checks the signature.

## Accepted risks (Josh to know, not fixed)

- **Home Wi-Fi traffic is plain HTTP** (Josh, 10 Nov: leave it).
  - Someone already on the home network could read device keys and music as they pass. Tailscale traffic
    is encrypted.
  - Fixing it would mean HTTPS with a self-made certificate on the PC and pinning it in the apps. It's a
    bigger change; worth it only if the home network has untrusted devices.
- **The TV's USB debugging stays on** so the PC can install updates.
  - Any computer on the network can ask to connect, but the TV only allows ones accepted on its screen
    (this PC).
- **The phone's cover-art provider is open to other apps on the phone,** because Android Auto must read it.
  The most it gives away is album covers.
- **Subsonic passwords are stored so they can be recovered** (DPAPI, this Windows user only), because the
  Subsonic login protocol needs them.
