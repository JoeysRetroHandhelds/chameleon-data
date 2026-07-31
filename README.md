# chameleon-data

The data [Chameleon](https://github.com/JoeysRetroHandhelds) reads at runtime: which
emulators exist, how to launch them, what folders a library uses, and what each console
is called by the services we talk to.

It is separate from the app, and public, for one reason: **when an emulator changes its
package or its activity name, the fix is one line, and the person who hit the problem is
usually the person best placed to send it.** A pull request here reaches every user
without waiting for an app release.

## What is here

| File | What it is |
| --- | --- |
| `platforms/index.json` | The list of platforms and the current revision of each |
| `platforms/*.json` | One pack per platform: emulators, launch arguments, file extensions |
| `systems-esde.txt` | Every system ES-DE defines, used to create a folder tree |
| `retroachievements-consoles.json` | Console ids, so RetroAchievements can be asked about a game |
| `hash-schemes.json` | Which hashing rule each console uses |
| `upstream.json` | Where each piece came from, and what it looked like when we took it |

## What is *not* here

The hashing rules themselves, the parsers, and everything else that is code. The split is
deliberate: tables change often and belong where anyone can fix them; algorithms change
rarely and a wrong one fails silently, which is not a thing to accept a drive-by change
on.

## Fixing an emulator

Launch arguments live in the platform's pack, in `playerList`. Each entry has
`amStartArguments`, which is an `am start`-shaped string:

```
-n com.retroarch/.browser.retroactivity.RetroActivityFuture
-e ROM {file.path}
```

If an emulator stopped launching, its activity name has usually changed. Edit the pack,
bump `revisionNumber` in both the pack and `index.json`, and open a pull request. Please
say which emulator version you tested against.

## Where this came from

The platform packs began as a copy of
[Daijishō's](https://github.com/TapiocaFox/Daijishou), which are MIT licensed. That
licence and its copyright notice are kept in `LICENSE-daijisho`, and they cover the
packs regardless of how far they diverge from here.

Upstream is watched rather than followed: a weekly job compares their revision numbers
against the ones recorded in `upstream.json` and opens an issue listing what they
changed. Nothing here is overwritten. When a fix is worth copying, copy it and update
that platform revision in `upstream.json` so it stops being reported.

They are no longer synced from upstream. Chameleon adds fields Daijishō has no place for,
and a mirror would overwrite them on every run. Their work on emulator arguments is still
worth watching, and cherry-picking a fix from them is welcome.

`systems-esde.txt` comes from [ES-DE's](https://gitlab.com/es-de/emulationstation-de)
`es_systems.xml` and is refreshed automatically.

## Licence

Platform packs: MIT, see `LICENSE-daijisho`.

Everything else in this repository is dedicated to the public domain under
[CC0](https://creativecommons.org/publicdomain/zero/1.0/). It is a list of numbers and
names; nobody should have to ask before using it.
