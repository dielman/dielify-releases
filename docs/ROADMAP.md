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
| 0.9.6 | Library power | smart playlists, search by lyrics, year in review |
| 0.9.7 | Sound + phone extras | crossfade, equaliser, cast to speakers, home-screen widget |
| 0.9.8 | Together | shared household playlists, Blend, Jam |
| 0.9.9 | Beautification | make both apps look good: one design, real artwork everywhere, a proper Now playing |
| 0.9.10 | 1.0 hardening | clean-PC install, car test, security review, restore drill, help pages |
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

## 0.9.7: Sound + phone extras (0.9.7 and 0.9.8 combined, Josh 9 Nov)

- **Crossfade**: 0–12 s on the PC (two-player setup already exists) and the phone. Never
  between songs of the same album played in order. Uses the loudness data to blend evenly.
- **Equaliser**: presets plus bass and treble on the phone (Android's equaliser on
  Media3's audio session) and the PC (Web Audio filters). Set per device.

- **Cast to speakers**: Google Cast from the phone to Nest speakers and Chromecasts
  (Media3 Cast). Streams from the PC over the home network. Checked on Josh's speakers.
- **Home-screen widget**: cover, title, play/pause/next; shows the active device too.

## 0.9.8: Together

- **Shared household playlists**: lists more than one person can edit. A child sees only
  the songs her filter allows.
- **Blend**: a weekly mix from two people's tastes. Each person opts in; a child needs the
  parent's OK and the result is filtered.
- **Jam**: one shared queue, e.g. in the car. The host plays; others add songs from their
  phones. If a child is in the Jam, every song is filtered for her.

## 0.9.9: Beautification (Josh, 9 Nov: "we need to work on making the app pretty")

Draft, to agree with Josh before it starts (he points at what bothers him most):
- **One look for both apps**: a small design system (colours, type sizes, spacing, corner
  radii, icon set) used by the PC app and the phone, so they look like the same product.
- **Real artwork everywhere**: no music-note placeholders. Artist pictures from YouTube
  Music (already fetched for About), playlist covers made from their songs' album covers
  (2x2), smart playlists and mixes with generated covers.
- **Now playing**: full-screen on the PC, big cover with the background tinted from the
  cover's colours, on the phone too.
- **Pages with headers**: album, artist and playlist pages with a large header image and
  the cover colour behind it.
- **Motion**: smooth screen changes, cover transitions between the player bar and Now
  playing, button feedback.
- **Lists and cards**: consistent card sizes, tidy song rows, better empty and loading
  states (skeletons, not "Loading…").
- **App icon and installer look** refreshed.
- Before/after screenshots of every screen for Josh to approve.

## 0.9.10: 1.0 hardening

- **Clean-PC install test** (Windows Sandbox): install, sign in, play offline, no
  terminal. Owed since Phase 4.
- **Android Auto test** in the car (Josh).
- **Security review** of the multi-user and kids code (`/security-review` plus the
  cross-profile tests), and a check that the parent's YouTube login can't leak to a child
  device.
- **Restore drill**: restore last night's backup onto a test copy.
- **Help pages** in the app for a non-technical person: first setup, adding a person, kids
  controls.
- **Slimmer FFmpeg** (only with Josh's OK to download it; saves about 70 MB per update).

## Not on the road to 1.0

Hi-res audio (YouTube's limit is ~256k), an AI DJ voice, karaoke voice removal, podcasts,
audiobooks, a second PC / second household.

## Still to decide

- ~~Where the child uses Dielify~~: her phone, at home (Josh, 9 Nov).
- The defaults in the parent controls table above (Josh to confirm or change).
