# Dielify: road to 1.0

Agreed with Josh, 9 Nov 2026. One release at a time. Each release is confirmed by Josh
on his devices before the next one starts (CLAUDE.md working agreements). Version numbers
count up the last digit: 0.9.1, 0.9.2 ... then 1.0.0.

## The shape of it

| Release | Theme | Main contents |
|---|---|---|
| 0.9.1 | Household foundations | shared music store, per-person libraries, parent/child roles (no visible change) |
| 0.9.2 | Second person | create a profile, her own phone login, her own library, borrow from the household |
| 0.9.3 | Kids accounts | Kids discovery, parent controls (explicit, approvals, search, limits) |
| 0.9.4 | Fixes from Josh's testing | docs/ISSUES-0.9.3.md: kids Discover speed, remove from library, green bar, open on Discover, Back keeps the search, song + artist radio |
| 0.9.5 | Discovery | new releases from your artists, artist About pages, time-of-day mix, leave out of my taste |
| 0.9.6 | Library power | smart playlists, search by lyrics (removed in 0.9.9), year in review |
| 0.9.7 | Sound + phone extras | equaliser, cast to speakers, home-screen widget (no crossfade: Josh, 9 Nov) |
| 0.9.8 | Together | shared household playlists, Blend, Jam |
| 0.9.9 | Beautification | one design, real artwork, new icon; lyrics removed, Discover cached (published 10 Nov) |
| 0.9.10 | TV | Dielify on the Google TV in the shed: TV screens, QR sign-in approved from a phone, phone as remote, Jam host (published 10 Nov) |
| 0.9.11 | 1.0 hardening | clean-PC install, car test, security review (incl. TV pairing), restore drill, help pages |
| 1.0.0 | Release | the last 0.9 build, renamed, once Josh is happy |

Multi-user goes first because every later feature has to know whose library, whose taste
and what a kid may see. Building those features once, with that already in place, is
cheaper than building them for one person and fixing them later.

## Accounts: the rules

- **Household** = one PC, one music store, one YouTube Premium sign-in (the parent's).
- **Parent profile** (Josh): everything Dielify does today, plus the Kids controls.
- **Child profile** (under 16): a Dielify-only experience.
  - She never sees YouTube's own home feed, "Listen again", "Mixed for you", YouTube
    charts or Josh's YouTube playlists. Nothing that comes from Josh's YouTube account
    reaches her.
  - The parent's sign-in is still used behind the scenes to find and download songs. She
    never sees it and can't change it.
  - Her playlists stay in Dielify; they are never synced to YouTube (they'd land in Josh's
    account).
- **Libraries are separate.** Each library is a list of songs pointing at files in the
  shared store. A song both people have is stored once. Removing a song takes it out of
  that person's library only. The file is deleted only when no library uses it any more,
  and never because of a child's action.
- **Separate per person:** plays, stats, thumbs and bans, mixes, For you, discovery play,
  Up next, devices / remote control, phone logins, Subsonic login.

## 0.9.1: Household foundations

No visible change. Josh's library must look and behave exactly as before.

- Database:
  - `library_items (profile, track_id, added_at, added_by)`;
  - profiles get `role` (parent / child) and `household`.
  - Every existing track is added to Josh's library. A backup is taken first, automatically.
- `tracks.profile` becomes the store owner (Josh's folder stays where it is:
  `E:\Music\ymp\josh`). Library queries go through `library_items`.
- Every API and Subsonic call is checked for "is this song in *your* library", not
  "is it on the PC". There are tests for one profile trying to reach another's data.
- Deleting a file needs "no library uses it". Thumbs down in discovery play takes the
  song out of your library and deletes the file only if no one else has it.
- Downloads record who asked. The queue takes turns between people, so one person's
  200-song playlist can't block the other's songs.

## 0.9.2: Second person

- PC Settings > People: add a person (name, parent or child), make her phone login.
- The phone app logs in as her and shows her library: empty at first.
- **Household** shelf: browse songs already on the PC and add them to her library (no
  download). For a child this is filtered by her controls (0.9.3).
- New songs she asks for download into the shared store and join her library only.
- Her stats, mixes, For you and discovery play come from her own plays only.
- ~~PC app: switch person with a PIN~~ dropped (Josh, 9 Nov: his daughter uses her phone
  at home only). Her phone uses the home Wi-Fi address; no Tailscale on her phone.
- Built in 0.9.2 as well: a kids account already gets nothing from the parent's YouTube
  account (home feed, charts, YouTube playlists are empty; her playlists never sync) and
  can't change settings. Kids discovery and the filters come in 0.9.3, so **don't hand the
  phone over until 0.9.3**.

## 0.9.3: Kids accounts

### Kids discovery (instead of YouTube's home feed)

Built only from Dielify's own data, filtered by the parent's controls:

- **Your favourites / on repeat**: from her own plays.
- **Because you like X**: radio from her top songs and artists. The results are filtered.
- **Her mixes**: genre, decade and vibe mixes from her own library (same engine as now).
- **Picked by your parent**: artists and playlists Josh chooses, shown as a shelf.
- **New from your artists**: arrives with 0.9.4, filtered.
- **Discovery play**: on or off per the controls; results filtered.

### Parent controls (PC Settings > People > her name; parent profile only)

| Control | Options | Default |
|---|---|---|
| Explicit songs | block / allow | block |
| Clean versions | when blocked, look for the clean version of a song instead | on |
| Lyrics check | also block songs whose stored lyrics contain words on the list (catches songs YouTube doesn't mark) | on |
| New downloads | download straight away / wait for parent's OK | straight away |
| Download limit | songs per day | 50 |
| YouTube search | on / off (off = she can only use the household's songs) | on |
| Discovery play | on / off | on |
| Blocked artists and songs | parent's own list; she never sees them | empty |
| Listening hours | e.g. no music after 21:00 on school nights | off |
| Parent can see her stats | on / off | off |
| Remote control | parent's devices can control hers | off |

- The **filter** runs everywhere a child gets a song:
  - search;
  - radio;
  - discovery play;
  - the Household shelf;
  - shared playlists;
  - Jam;
  - Subsonic apps.
- **Approvals**: the parent gets a list (PC Downloads + a phone notification) and taps
  Allow or Deny.
- **Explicit data**: YouTube marks explicit songs in most search and album results. To
  check while building: which YouTube calls carry the mark (radio results may not). Where
  it's missing, Dielify looks the song up again before letting it through.

### Built in 0.9.3 (9 Nov), and what changed from the plan

- All controls above except "Remote control" (parent's devices controlling hers): moved to
  after 1.0 (the device hub is per person; joining two people's devices is its own job).
- Approvals are on the PC's Downloads page only (no phone notification yet).
- Quiet hours stop streaming from the PC (Dielify app, instant play); songs saved on her
  phone still play, and Symfonium / Subsonic apps aren't covered.
- Explicit marks: search, album and playlist results carry YouTube's mark; radio results
  don't, so those songs get one YouTube search each (remembered in yt_flags). The songs
  already on the PC are checked in the background (about 1,500 an hour) while a kids
  account blocks explicit songs; until a song is checked, a child doesn't get it.

## 0.9.5: Discovery (published 9 Nov)

- **New releases from your artists**: follow artists (or use your top 20 played). A daily
  check of their YouTube artist pages builds "New for you". Optional: download new
  albums automatically. Kids get this filtered.
- **Artist About pages**: bio and links (YouTube description, MusicBrainz). Also answers
  Symfonium's getArtistInfo2.
- **Time-of-day mix**: changes through the day, from what you play at each hour.
- **Leave out of my taste**: mark a playlist or song so it doesn't shape your recommendations.

## 0.9.6: Library power (published 9 Nov)

- **Smart playlists**: rule-based lists that keep themselves up to date. Rules can use
  genre, artist, decade, play count, last played, rating, added date and length. The PC
  has a rule builder; the phone shows the lists.
- **Search by lyrics**: a full-text index of stored lyrics; search "lyrics: ..." or a
  Lyrics tab.
- **Year in review**: a recap page per person (top songs, artists, genres, minutes,
  firsts). Any month, plus a December edition. A child's recap is hers only.

## 0.9.7: Sound + phone extras (0.9.7 and 0.9.8 combined, Josh 9 Nov; published 9 Nov)

No crossfade (Josh, 9 Nov: dropped, PC and phone).
- **Equaliser**: presets plus bass and treble on the phone (Android's equaliser on
  Media3's audio session) and the PC (Web Audio filters). Set per device.

- **Cast to speakers**: Google Cast from the phone to Nest speakers and Chromecasts
  (Media3 Cast). Streams from the PC over the home network. Checked on Josh's speakers.
- **Home-screen widget**: cover, title, play/pause/next; shows the active device too.

## 0.9.8: Together (published 9 Nov)

- **Shared household playlists**: lists more than one person can edit. A child sees only
  the songs her filter allows.
- **Blend**: a weekly mix from two people's tastes. Each person opts in; a child needs the
  parent's OK and the result is filtered.
- **Jam**: one shared queue, e.g. in the car. The host plays; others add songs from their
  phones. If a child is in the Jam, every song is filtered for her.

## 0.9.9: Beautification (Josh, 10 Nov: all 27 items) - published 10 Nov

Josh picked everything on the list (artwork, colour, PC, phone, motion, brand, words). Built in
stages; Josh sees PC screenshots after stage 2 before the phone work starts.

1. **Artwork and colour, on the PC server** (both apps use it):
   - every cover's main colours worked out once (Pillow) and sent with songs, albums, playlists;
   - playlist covers = 2x2 grid of their album covers; mixes, Blends, smart playlists get
     designed covers (colour block + big title); songs/albums without art get a generated one;
   - artist photos from YouTube Music (fetched once, kept on the PC).
2. **PC app**: design tokens (one accent, type scale, spacing, radii), the chosen font,
   side navigation with your playlists, big page headers with the cover's colour behind them,
   a full-window Now playing (cover-tinted, Up next beside it since lyrics went), a calmer player bar (rare
   buttons in one menu), Discover hero, Settings in sections, loading skeletons, page
   transitions, an animated "playing" marker in lists, shorter words.
   -> screenshots of every PC screen, before/after, for Josh.
3. **Phone app**: same tokens and font, Now playing redesign (cover colour, swipe for
   next/previous, swipe down to close), mini player with progress and swipe, Settings in
   sections, tighter top bars, cover-to-player animation, playing marker, the widget restyled,
   Material You or cover colours (Josh's choice).
4. **Brand**: new app icon and splash screen (Josh picks from options), installer and update
   screens to match.
5. **Words pass** on every screen, then publish.

Status (10 Nov): stages 1-5 built and pushed (phase-8), Josh approved the PC look, the phone look
and picked the **Wave D** icon. Josh's PC runs a dist\ build with it. Not done from the list: the
phone's cover-to-player animation (pages slide instead). Also in 0.9.9 (Josh, 10 Nov):
- **Lyrics removed entirely** (server, PC, phone; stored lyrics deleted). Kids "Check words" now
  checks titles only.
- **Discover cached**: YouTube's home feed and charts kept 10 minutes, refreshed in the background
  when older, last copy shown when YouTube fails.
- **People before background jobs**: background YouTube lookups wait until nobody's call is
  running or waiting; slow YouTube calls are logged.
- Inter font fix on the PC (it never loaded before).

Published 10 Nov (v0.9.9).

## 0.9.10: TV (Josh, 10 Nov)

A Google TV in the shed, on the same network as the PC. Decisions (Josh, 10 Nov): TV goes in before
1.0 (hardening moves to 0.9.11 so its checks cover the TV); signing in = a QR code on the TV that a
phone approves, and a **parent picks which person** the TV signs in as; the Android TV emulator
image was OK'd (Google TV, Android 16, x86_64; installed on E:).

- **One app for phone and TV**: the same APK opens TV screens on a TV (Compose for TV, D-pad focus,
  10-foot text, overscan margins, launcher banner) and shares everything underneath (server client,
  Media3 playback, song cache, remote control, updater, signing key).
- **Finding the PC**: the PC announces itself on the home network (mDNS / DNS-SD, `_dielify._tcp`);
  typing the address is the fallback.
- **QR sign-in** (the TV/YouTube "device code" pattern):
  1. TV -> PC `POST /api/pair/start {device_name}` (no sign-in): a long secret only the TV keeps +
     a short code (e.g. `KDW-7RT`), 10 minutes. Few pending at once, rate-limited.
  2. The TV shows a QR code holding only the short code (and the code in text).
  3. A signed-in phone scans it (Google's code scanner, no camera permission), sees "Sign in
     <TV name> (<address>)", a parent picks the person, Allow -> `POST /api/pair/approve`.
     The PC app can approve a typed code too (Settings > People & phones > Add a TV).
  4. The TV polls with its secret and collects its device token once. The TV is then listed with
     the phones and can be signed out there. The QR alone grants nothing.
- **TV screens**: Home (mixes, new releases, recently played), Library (cover grids), Search,
  Settings; full-screen Now playing in the cover's colours with Up next; slow-moving cover display
  when idle. No "keep on this phone".
- **Together**: the TV in every "Play on" list (phone as the remote), the TV as Jam host.
- **Install**: Developer options + Wireless debugging on the TV, then installed from the PC over
  Wi-Fi (adb). Updates: the same in-app updater as the phone.

Status (10 Nov): steps 1-4 done, running on Josh's TCL Google TV. **Published 10 Nov (v0.9.10).** Also fixed: phone Jam
songs were refused by the PC since 0.9.8 (missing "type").
Also (Josh, 10 Nov): phones and TVs get app updates from the PC first (the installer carries the
phone/TV app), GitHub only as the fallback: Josh's TV can't reach GitHub.
After 0.9.10 (Josh): the PC installs app updates on TVs over the network (adb), because a kids profile on
Josh's TV blocks it installing apps. Ships with the next release.

Steps: 1 pairing + announcing + PC code entry + phone scanner -> 2 TV app (find PC, sign in, Home /
Library / Search, playback, Now playing) -> 3 Play on / Jam / idle display -> 4 install on the TV,
Josh tests in the shed.

## 0.9.11: 1.0 hardening

**Kids controls, decided by Josh (10 Nov)**, to build in 0.9.11:
- **Each child gets their own tab in PC Settings** (next to Playback, People & phones...) holding all of their
  controls, instead of the Controls page reached from People & phones.
- Explicit songs: an allow / don't-allow **toggle** (default: don't allow). Clean versions: on.
- Check words (titles): **off by default** (was on).
- New downloads: straight away. Download limit: a number Josh sets per child (default 50). YouTube search: all of
  YouTube Music. Never-ending discovery: on. Jams: on.
- Quiet hours: set per child in their tab (default off). Blend: per child in their tab ("some kids are old
  enough, some aren't"; default off).
- Parent can see the child's stats: **on by default** (was off).
- Before 1.0: **control her devices** (a parent's phone / PC sees and controls what plays on a child's devices)
  and **quiet hours everywhere** (also in Subsonic apps like Symfonium). Not before 1.0: approvals on the
  parent's phone.
Status (10 Nov): all of the above built (not released).

Also owed from earlier releases: Josh hasn't yet confirmed on his devices most of 0.9.1-0.9.8
(kids account on his daughter's phone, Jam, Blend, cast, widget, equaliser, new releases).

- **Clean-PC install test** (Windows Sandbox): install, sign in, play offline, no
  terminal. Owed since Phase 4.
- **Android Auto test** in the car (Josh).
- **Security review** (done 10 Nov: docs/SECURITY-REVIEW-0.9.11.md, 2 fixes) of the multi-user and kids code (`/security-review` plus the
  cross-profile tests), and a check that the parent's YouTube login can't leak to a child
  device.
- **Restore drill** (done 10 Nov, passed: docs/RESTORE-DRILL-0.9.11.md; backups had been off): restore last night's backup onto a test copy.
  Follow-up (Josh, 10 Nov): **backups on by default** (built): the first start picks <music folder's parent>\Dielify-backups;
  picking a folder or Turn off is remembered (settings.backup_chosen), so off stays off.
- **Help pages** in the app for a non-technical person: first setup, adding a person, kids
  controls. Built 10 Nov (not released): Help in the PC side bar (ui/help.js: first setup, phone, away from home,
  add a person, kids controls, add a TV, play on another device, backups, troubleshooting).
- **First-start wizard** (Josh, 10 Nov, built, not released): a new install opens on it (no sign-in, no songs, not
  finished before): welcome -> your name (renames the empty "default" profile) -> YouTube sign-in -> music folder ->
  backups -> start with Windows / keep awake -> add a phone (password + install steps) or TV help -> done. Or
  **Restore from a backup**: pick the zip, Dielify restarts itself with --restore (restores before the server opens the
  database), then shows what came back (people, songs, files found, which sign-ins need redoing, music folder picker).
  Help > Run the setup again. Josh tried the dist\ installer build (10 Nov): "everything looks good".
- **Phones learn the PC's addresses** (built 10 Nov, not released): /api/me gives every address the PC listens on
  (server.LISTENING, home network first); the phone keeps any it doesn't know (Server.learnAddresses, after sign-in
  and whenever it finds the PC), so a phone signed in at home gets the Tailscale address without signing in again.
  Checked on the emulator. Works once both the PC and the phone run this version.
- **Log check** (10 Nov, Josh's real server.log, read-only; built, not released):
  - YouTube's empty answers (JSONDecodeError) are now asked again for song, video, album lookups and search, not
    only the home feed. Before, a song looked up during one became a plain video: "Singles", no album, track number
    or year (33 songs on 9 Nov, ~22 still like that). `details.py` repairs those: each "Singles" song with no year
    and no track number is looked up once more at quiet moments (10 min after start, then every 6 h until done);
    with an album now, tags + cover are rewritten and the file moves to its album folder, same track id (plays,
    playlists, ratings kept). Real music videos stay; each song checked once (table details_checked).
  - Instant play asks yt-dlp again when "Requested format is not available" (a 403 inside yt-dlp; downloads already
    recovered on their retry, instant play gave a 502 after 35 s).
  - Windows' "connection forcibly closed" asyncio errors (63, harmless: phones dropping connections) are left out
    of the log. The yt-dlp "Unable to download API page: 403" warnings are harmless (downloads finished).
- **Slimmer FFmpeg** (only with Josh's OK to download it; saves about 70 MB per update).

## Not on the road to 1.0

Lyrics (removed in 0.9.9, Josh). Hi-res audio (YouTube's limit is ~256k), an AI DJ voice, karaoke voice removal, podcasts,
audiobooks, a second PC / second household.

## Still to decide

- ~~Where the child uses Dielify~~: her phone, at home (Josh, 9 Nov).
- ~~The defaults in the parent controls table above~~: decided 10 Nov, see 0.9.11.
