#!/usr/bin/env python3
"""Build the ra-patches index: which romhacks apply to which ROM, per console.

The app's romhack tool (and the club's Romhack of the Month) look up a base ROM's CRC and
offer the hacks made for it, from RetroAchievements' RAPatches repository. RAPatches stores
each hack as an archive under `System/Type/.../<gameid>-<name>.zip`, and the archive holds a
patch named after No-Intro: `Base Game - Hack Name (v2.0).bps`. So both facts we need are
here without the RetroAchievements API:

- the **base game**, from the RAPatches base-game folder (falling back to the patch filename
  for translations, which file by language), resolved to its CRC through the No-Intro dats, and
- the **format** (bps/ips/xdelta), from the patch's extension, which the app needs to parse it.

The patch filename lives in the archive's central directory at the very end of the file, so a
short range request reads it without pulling the whole (often tens of MB) archive. The result
is `ra-patches/<shortname>.json`: `{ base_crc: [ {name, type, path, format} ] }`, exactly what
`RaPatches.parse` reads. A hack whose base cannot be resolved is skipped, so a wrong guess is
never published. Run from the repo root:

    python tools/build-rapatches.py                 # every system
    python tools/build-rapatches.py --system GBA    # one, for a quick check
"""
import argparse
import json
import os
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import nointro

TREE = "https://api.github.com/repos/RetroAchievements/RAPatches/git/trees/main?recursive=1"
RAW = "https://github.com/RetroAchievements/RAPatches/raw/refs/heads/main/"
OUT_DIR = "ra-patches"
UA = {"User-Agent": "chameleon-data ra-patches builder"}

# RAPatches' top-level console folder -> the pack shortname the app matches on. Folders with
# no console pack (DLC, Removed, Standalone, Saves, Incompatible) are simply absent, so their
# files are skipped. Regional names follow the packs (MD -> genesis, PC Engine -> tg16).
SYSTEMS = {
    "3DO": "3do", "Amstrad CPC": "amstradcpc", "Apple II": "appleii",
    "Arcadia 2001": "arcadia2001", "Atari 2600": "atari2600", "Atari Jaguar": "atarijaguar",
    "Dreamcast": "dreamcast", "Famicom Disk System": "fds", "GBA": "gba", "GBC": "gbc",
    "Game Boy": "gb", "Game Gear": "gamegear", "GameCube": "gc", "MD": "genesis", "MSX": "msx",
    "Master System": "master", "N64": "n64", "NDS": "nds", "NES": "nes",
    "Neo Geo CD": "neogeocd", "Neo Geo Pocket": "ngp", "Nintendo 64DD": "n64",
    "PC Engine CD": "tg16", "PC Engine": "tg16", "PC-FX": "pcfx", "PS2": "ps2",
    "PlayStation Portable": "psp", "PlayStation": "psx", "Pokemon Mini": "pokemonmini",
    "SG-1000": "sg1000", "SNES": "snes", "Saturn": "saturn", "Sega 32X": "sega32x",
    "Sega CD": "segacd", "Wii": "wii",
}

PATCH_IN_NAME = re.compile(rb"([\x20-\x7e]+?\.(?:bps|ips|xdelta|xdelta3|ups))", re.I)


def _get(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def tree():
    """Every patch archive in the repo, as (system, type, path)."""
    data = json.loads(_get(TREE))
    for node in data["tree"]:
        if node["type"] != "blob":
            continue
        path = node["path"]
        if not path.lower().endswith((".zip", ".7z")):
            continue
        parts = path.split("/")
        if len(parts) < 3:
            continue
        yield parts[0], parts[1], path


def inner_patch(path):
    """(patch filename, format) read from the archive's tail, or (None, None).

    The central directory sits at the end of a zip, so the last few KB name the files inside;
    a range request reads them without the whole archive. 7z is not laid out the same way, so
    those fall back to the archive's own extension and a bps assumption.
    """
    if path.lower().endswith(".7z"):
        return os.path.basename(path), "bps"
    try:
        tail = _get(RAW + urllib.parse.quote(path), {"Range": "bytes=-16384"})
    except Exception:
        return None, None
    best = None
    for m in PATCH_IN_NAME.finditer(tail):
        name = m.group(1).decode("latin-1")
        # The newest revision when several ship together, so the CRC the site knows wins.
        if best is None or name > best:
            best = name
    if not best:
        return None, None
    return best, best.rsplit(".", 1)[1].lower()


def base_title(parts, type_folder, patch_name):
    """The base game a patch is for.

    For a hack, subset or fix the base-game folder is the reliable source - it is the whole
    title, so a name that itself contains ' - ' (Fire Emblem - The Sacred Stones) survives.
    Translations file by language instead, and a few patches sit directly under the type with
    no folder, so those fall back to the patch filename's leading part.
    """
    if type_folder != "Translation" and len(parts) >= 4:
        return parts[-2]
    name = patch_name.rsplit(".", 1)[0]
    return name.split(" - ", 1)[0].strip()


def base_crcs(resolver, title):
    """The CRCs for a base title, tolerating the informal names patches use.

    Tries an exact fold first; failing that, treats the title as the start of a catalogue name,
    so "Pokemon Emerald" reaches "Pokemon Emerald Version". Being a shade over-inclusive is safe:
    a BPS patch carries its source checksum and the app refuses to apply it to the wrong ROM, so
    a hack listed under a near neighbour simply never takes there.
    """
    key = nointro.fold(title)
    if not key:
        return set()
    exact = resolver.by_title.get(key)
    if exact:
        return exact
    out = set()
    for name, crcs in resolver.by_title.items():
        if name.startswith(key + " "):
            out |= crcs
    return out


def build(only=None, workers=16):
    packs = _packs()
    resolvers = {}

    # The archives worth reading: those on a console we have a pack and a dat for.
    jobs = []
    for system, type_folder, path in tree():
        if only and system != only:
            continue
        short = SYSTEMS.get(system)
        if not short or short not in packs:
            continue
        if short not in resolvers:
            resolvers[short] = nointro.resolver(packs[short])
        if resolvers[short]:
            jobs.append((short, type_folder, path))

    # The format needs a peek inside each archive; those reads are all network, so run them
    # in parallel - a few thousand tiny range requests one at a time would take an age.
    print(f"reading {len(jobs)} archives...")
    formats = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for path, (patch_name, fmt) in zip(
            [j[2] for j in jobs], pool.map(lambda j: inner_patch(j[2]), jobs)
        ):
            formats[path] = (patch_name, fmt)

    index = {}  # shortname -> {crc -> [hack]}
    for short, type_folder, path in jobs:
        patch_name, fmt = formats.get(path, (None, None))
        if not patch_name:
            continue
        title = base_title(path.split("/"), type_folder, patch_name)
        crcs = base_crcs(resolvers[short], title)
        if not crcs:
            print(f"  unresolved base: {short} {title!r}  ({path})")
            continue
        hack = {
            "name": os.path.splitext(os.path.basename(path))[0],
            "type": type_folder,
            "path": path,
            "format": fmt,
        }
        table = index.setdefault(short, {})
        for crc in sorted(crcs):
            table.setdefault(crc, []).append(hack)

    os.makedirs(OUT_DIR, exist_ok=True)
    for short, table in index.items():
        with open(os.path.join(OUT_DIR, f"{short}.json"), "w", encoding="utf-8") as f:
            json.dump(table, f, indent=2)
            f.write("\n")
        hacks = sum(len(v) for v in table.values())
        print(f"wrote {OUT_DIR}/{short}.json: {len(table)} base ROMs, {hacks} hacks")


def _packs():
    index = json.load(open(os.path.join("platforms", "index.json"), encoding="utf-8"))
    packs = {}
    for entry in index["platformList"]:
        path = os.path.join("platforms", entry["filename"])
        if os.path.isfile(path):
            platform = json.load(open(path, encoding="utf-8"))["platform"]
            packs[platform["shortname"]] = platform
    return packs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", help="only this RAPatches system folder, e.g. GBA")
    args = ap.parse_args()
    build(args.system)


if __name__ == "__main__":
    main()
