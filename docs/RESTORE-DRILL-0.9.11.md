# Restore drill, 0.9.11 (10 Nov 2026)

**Result: passed.** The newest real backup restored completely into a throwaway folder.
`build/restore_drill.py` runs it with Dielify's own `backup.restore`. It never touches the real data
folder, and it only reads the music folder.

## Found first

**Backups were switched off** on Josh's PC (no backup folder set), so no backup existed. Josh turned
them on (Settings > This PC > Backups, folder on E:) and made one with Back up now. Since then backups are
on by default: a new install backs up next to the music folder unless someone turns them off.

## What came back

- Database integrity check: ok.
- The household: 2 people, one parent and one kids account.
- The library:
  - 2,970 songs on the PC, 2,340 albums, 1,474 artists;
  - 2,969 songs in people's libraries;
  - 157 plays of history;
  - 16 playlists holding 1,850 songs.
- Settings and other data:
  - the kids controls;
  - 6 signed-in devices;
  - 785 downloads in the list;
  - settings (music folder, backup folder).
- Music files: all 2,970 songs found in the music folder.
- The YouTube sign-in and all 3 phone logins could be read after the restore.

Restoring took under a second.

## Worth knowing

- **Sign-ins need the same Windows user on the same PC.** They are encrypted with Windows DPAPI. On a new
  PC or a reinstalled Windows, everything else comes back, but YouTube needs signing in again and phones
  need new phone logins.
- **The backups sit on the same drive as the music (E:).** If that drive fails, both are gone. Copying the
  backup folder somewhere else now and then (another drive, a USB stick, cloud storage) covers that. The
  backups are small (about 2.6 MB each).
- **What a backup doesn't hold:**
  - the music itself, which carries its own tags and covers; a library scan rebuilds the index;
  - downloaded artist photos and cover colours, which are fetched and worked out again by themselves.

## How to restore for real

Close Dielify (tray icon > Quit Dielify), then run this in a normal terminal (no admin):

```
"%LOCALAPPDATA%\Programs\Dielify\dielify-cli.exe" backup restore "E:\Music\Dielify-backups\<the backup>.zip"
```

It first makes a safety copy of the current data next to the backup. Then open Dielify again.
