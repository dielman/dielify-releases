# Issues found in 0.9.3: all six fixed in 0.9.4 (9 Nov; not yet tried on Josh's devices)

1. Kids Discover: requests never wait on explicit checks (unchecked songs are left out and
   checked first by the background check, which now waits for a quiet moment: people's
   YouTube requests always go first). 2. Remove from my library: PC song rows + album page,
   phone song ⋮ menu + album page (confirm first). 3. Green bar in the top bar on every phone
   screen; Now playing has no mini player and its cover shrinks to fit. 4. Both apps open on
   Discover (PC offline mode / phone without the PC: Library). 5. Back keeps the search:
   phone keeps every screen's state (and each tab's), results cached; PC has a real back
   history (Back button + mouse Back), search results kept 10 min. 6. Start radio on songs
   (PC song menus, phone ⋮ menus + Now playing) and artist radio (artist pages, YouTube
   artists); POST /api/radio, tops up like discovery play, nothing downloaded unless played.

# Issues found in 0.9.3 (collecting; fix all together)

Josh, 9 Nov: "lets keep finding things before we make changes".

## 1. Discover doesn't load in the kids account (diagnosed)

Seen in the real server.log (read-only), her phone 192.168.1.43:
`/api/discover/home` 33 s and 58 s, `/api/discover/similar` 88 s and 64 s. The phone gives up
after 30 s (OkHttp readTimeout), so Discover shows nothing. Search works (fast: songs in
search results carry YouTube's explicit mark, so no extra lookups).

Causes:
- Every song without an explicit mark (song radio, "Because you like", On the PC) is checked
  with its own YouTube search, one at a time at the 1.5 s pace: up to 15 per Discover load.
- The background check of the music on the PC (`kids.Checker`) uses the same YouTube
  connection as everyone's requests (one call at a time per sign-in), and runs nonstop for
  about 2 hours after the update. So her requests, and Josh's, wait in line behind it.
  Josh's Discover is affected too while it runs (his home took 3.5 s at 15:54).

Fix ideas: Discover never waits on lookups (show what's already checked, check the rest
in the background and fill in next time); the background check yields to people (its own
lower-priority turn, or pauses while someone is using the app); phone timeout handling.

## 2. No way to remove a song from your library (both accounts)

Neither the PC app nor the phone has "Remove from my library" (only thumbs down in
discovery play removes a song). The server already has the safe rule (Library.remove_track:
the file is deleted only if nobody else has it, never by a child), but no endpoint or button.

## 3. Phone: the green "Playing on <PC>" bar covers the controls (PC playing, phone controlling)

Likely cause (not confirmed on the device): the phone's bottom bar always holds the mini
player, and above it the green strip (`PlayingOnStrip` in `MiniPlayer`), even on the Now
playing screen, which already shows "Playing on ..." at the top. With both, the bottom bar
gets taller and Now playing's controls (seek bar, play/next) end up under it or below the
fold. Fix ideas: no mini player (or strip) on Now playing; check the strip doesn't overlap on
other screens. Ask Josh for a screenshot if the fix isn't obvious.

**Josh's fix (9 Nov):** keep the green bar, move it to the top, just under the header bar
(on every screen), and lay everything else out below it, not under it. Everything must size
itself so the play controls never disappear under the footer (mini player + tabs), whatever
the screen height: e.g. Now playing scales its cover down / scrolls rather than pushing the
controls off-screen; the green bar in the top bar slot (Scaffold topBar Column), so content
padding accounts for it.

## 4. Open on Discover, not Library (Josh, 9 Nov)

Both apps start on Library. Phone: `AppViewModel._stack` starts (and resets, lines ~84, 181,
464) with `Screen.Library`. PC: `app.js` `let view = "library"`. Change both to Discover.
Keep the fallback: when the PC can't be reached, the phone should still land somewhere
useful (Library > On phone), since Discover needs the PC.

## 5. Going back loses the search (Josh, 9 Nov: "huge QOL fail")

Search, open a result (e.g. a playlist), go back: the search is gone. Both apps:
- Phone: `MainActivity` shows only `stack.last()`, so the screen underneath is thrown
  away, along with its `rememberSaveable` state (query, results, tab, scroll position). Fix:
  `rememberSaveableStateHolder()` + `SaveableStateProvider(key per stack entry)`, so every
  screen in the back stack keeps its state (search text, type tab, results, scroll); and
  keep loaded results (don't re-search on return).
- PC: the album/playlist page's back button goes to "Discover" (`viewCollection`: back =
  `go("discover")`), not to the search it came from. Fix: a real back history (the view
  that opened it, with its query, tab and scroll position), and the browser/mouse Back
  button doing the same.
Check every list → detail → back path in both apps for the same problem (library search,
artist → album, playlists, stats → artist).

## 6. Song radio and artist radio (Josh, 9 Nov: "other apps have this")

Every song (song menus everywhere, Now playing, library rows, search results) and every
artist (artist pages, YouTube and library) gets **Start radio**: playback starts at once with
that song (or the artist), followed by similar songs, and keeps topping up like
never-ending discovery. Today the phone only has "Similar songs", a list you have to open
and tap; the PC has nothing.
- Song radio: YouTube's song radio (`similar`, watch playlist), the song itself first.
- Artist radio: ytmusicapi `get_artist` gives `radioId` (RDEM...) for the artist's radio
  playlist; library artists without a YouTube channel id: radio from their top songs.
- Plays straight away (instant play), no downloads unless played (same rule as instant
  play: a song that's played gets downloaded); thumbs down skips and steers it.
- Kids accounts: radio results go through her filter, without making playback wait on
  explicit checks (see #1).
- Works on the active device (Spotify Connect style), like Up next.

## More (add as found)
