#!/usr/bin/env python3
"""Build shortcode-to-title mappings for arcade platforms.

Arcade ROMs are named by set code -- 1943mii.zip, sf2ce.zip -- while every artwork
source names its pictures after the game: "1943 Kai: Midway Kaisen (Japan).png". No
amount of fuzzy matching bridges that, so 652 of FinalBurn Neo's 721 games found
nothing at all on a test device.

libretro's own database carries the mapping, in the same ClrMamePro dats its thumbnail
sets are built from, so a code resolves to the exact string the artwork is filed under.

Usage: python tools/arcade-names.py
"""
import json
import re
import urllib.request
from pathlib import Path

SOURCES = {
    # system id -> dat inside libretro-database
    "fbneo": "metadat/fbneo-split/FBNeo - Arcade Games.dat",
    # 2010 rather than 2003: it is the largest split dat libretro publishes, and the
    # thumbnail set it feeds is the one named plain "MAME".
    "mame": "metadat/mame-split/MAME 2010.dat",
}
BASE = "https://raw.githubusercontent.com/libretro/libretro-database/master/"
GAME = re.compile(r'game \(\s*\n\s*name "([^"]+)"(.*?)\n\)', re.S)
ROM = re.compile(r'rom \(\s*name ([^\s]+\.zip)')


def fetch(path):
    url = BASE + urllib.parse.quote(path)
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read().decode("utf-8", "replace")


def mapping(text):
    names = {}
    for title, body in GAME.findall(text):
        rom = ROM.search(body)
        if not rom:
            continue
        code = rom.group(1)[: -len(".zip")]
        # First wins: the dats list clones after their parent, and a clone's artwork
        # is filed under its own name anyway.
        names.setdefault(code, title)
    return names


def main():
    out = {"formatVersion": 1, "systems": {}}
    for system, path in SOURCES.items():
        try:
            names = mapping(fetch(path))
        except Exception as error:  # a dat that moved is not a reason to lose the rest
            print(f"  {system}: skipped, {error}")
            continue
        out["systems"][system] = dict(sorted(names.items()))
        print(f"  {system}: {len(names)} names")
    target = Path("arcade-names.json")
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written: {target}, {target.stat().st_size // 1024} KB")


if __name__ == "__main__":
    import urllib.parse
    main()
