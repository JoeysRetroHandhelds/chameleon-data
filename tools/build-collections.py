#!/usr/bin/env python3
"""Build collections/curated.json: themed sets, named by title, emitted as checksums.

A curated set is a list of games the app fills in from what each person owns. It is authored
two ways, and this merges both into the one file the app reads:

- **By hand**, in `collections/curated-sources.json`: a set names its games by title and
  platform, the way a person thinks of them. Each title is resolved to every dump's CRC via
  the No-Intro dats (see `nointro.py`), so a set lights up whichever region a person has.
- **Automatically**, from data already in this repo: an `auto` set is a rule rather than a
  list. "Short and sweet" is every game under N hours per `hltb/hltb.json`, resolved the same
  way. These refresh themselves as the underlying data grows, with no titles to maintain.

The app matches by CRC and reads `games` as `[{platform, crc}]`, one entry per checksum, so a
title with ten dumps becomes ten entries under one set. Run from the repo root:

    python tools/collections.py
"""
import json
import os
import re

import nointro

SOURCES = os.path.join("collections", "curated-sources.json")
OUT = os.path.join("collections", "curated.json")
HLTB = os.path.join("hltb", "hltb.json")


def _packs() -> dict[str, dict]:
    """shortname -> platform dict, for every pack in the index."""
    index = json.load(open(os.path.join("platforms", "index.json"), encoding="utf-8"))
    packs = {}
    for entry in index["platformList"]:
        path = os.path.join("platforms", entry["filename"])
        if not os.path.isfile(path):
            continue
        platform = json.load(open(path, encoding="utf-8"))["platform"]
        packs[platform["shortname"]] = platform
    return packs


def _resolvers(packs: dict[str, dict]) -> dict[str, nointro.Resolver]:
    """One resolver per platform, built once and shared across every set that names it."""
    out = {}
    for shortname, platform in packs.items():
        r = nointro.resolver(platform)
        if r:
            out[shortname] = r
    return out


def _entries(games, resolvers) -> list[dict]:
    """Resolve authored `[{platform, title}]` to `[{platform, crc}]`, one row per dump."""
    rows = []
    seen = set()
    for game in games:
        shortname = game["platform"].lower()
        resolver = resolvers.get(shortname)
        if not resolver:
            continue
        crcs = resolver.crcs(game["title"])
        if not crcs:
            print(f"  unresolved: {shortname} {game['title']!r}")
        for crc in sorted(crcs):
            key = (shortname, crc)
            if key not in seen:
                seen.add(key)
                rows.append({"platform": shortname, "crc": crc})
    return rows


def _hltb_index() -> dict[str, float]:
    """Folded title -> shortest known hours, so a title meets the dats' formal names."""
    if not os.path.isfile(HLTB):
        return {}
    raw = json.load(open(HLTB, encoding="utf-8")).get("games", {})
    out: dict[str, float] = {}
    for title, info in raw.items():
        hours = info.get("h")
        if not hours:
            continue
        key = nointro.fold(title)
        if key and (key not in out or hours < out[key]):
            out[key] = hours
    return out


def _auto_hours(rule: dict, resolvers, hltb) -> list[dict]:
    """Every game whose playtime is within [minHours, maxHours] on the named platforms, capped
    at `limit` per platform. One rule covers a quick pick-up, an evening, or an RPG marathon,
    depending on the bounds it sets."""
    lo = rule.get("minHours", 0)
    hi = rule.get("maxHours", 1e9)
    limit = rule.get("limit", 40)
    rows, seen = [], set()
    for shortname in rule.get("platforms", []):
        resolver = resolvers.get(shortname)
        if not resolver:
            continue
        picked = 0
        for key, crcs in sorted(resolver.by_title.items()):
            hours = hltb.get(key)
            if hours is None or not (lo <= hours <= hi):
                continue
            added = False
            for crc in sorted(crcs):
                k = (shortname, crc)
                if k not in seen:
                    seen.add(k)
                    rows.append({"platform": shortname, "crc": crc})
                    added = True
            if added:
                picked += 1
            if picked >= limit:
                break
    return rows


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _auto_franchise(rule: dict, resolvers) -> list[dict]:
    """One collection per named franchise: every game whose folded title contains the franchise
    name, across the given platforms. "Contains" rather than "starts with" so a series named
    after its hero is caught wherever the word sits (Super Mario, Dr. Mario, Paper Mario). Each
    becomes its own `franchise-<slug>` collection, returned ready to append."""
    out = []
    for franchise in rule.get("franchises", []):
        needle = nointro.fold(franchise)
        if not needle:
            continue
        games, seen = [], set()
        for shortname in rule.get("platforms", []):
            resolver = resolvers.get(shortname)
            if not resolver:
                continue
            for key, crcs in resolver.by_title.items():
                if needle in key:
                    for crc in sorted(crcs):
                        k = (shortname, crc)
                        if k not in seen:
                            seen.add(k)
                            games.append({"platform": shortname, "crc": crc})
        if games:
            out.append(
                {
                    "id": f"franchise-{_slug(franchise)}",
                    "name": franchise,
                    "description": f"Every {franchise} game in your library, in one place.",
                    "source": rule.get("source", "Chameleon"),
                    "games": games,
                }
            )
    return out


def main():
    packs = _packs()
    resolvers = _resolvers(packs)
    sources = json.load(open(SOURCES, encoding="utf-8"))
    hltb = _hltb_index()

    collections = []
    for c in sources.get("collections", []):
        print(f"set: {c['name']}")
        games = _entries(c["games"], resolvers)
        if games:
            collections.append(
                {
                    "id": c["id"],
                    "name": c["name"],
                    "description": c.get("description", ""),
                    "source": c.get("source", ""),
                    "games": games,
                }
            )
    for rule in sources.get("auto", []):
        kind = rule.get("kind")
        print(f"auto: {rule.get('name', kind)}")
        if kind == "franchise":
            # One rule fans out to a collection per series.
            collections.extend(_auto_franchise(rule, resolvers))
            continue
        # "short" kept as an alias for the hours rule it grew out of.
        games = _auto_hours(rule, resolvers, hltb) if kind in ("hours", "short") else []
        if games:
            collections.append(
                {
                    "id": rule["id"],
                    "name": rule["name"],
                    "description": rule.get("description", ""),
                    "source": rule.get("source", "Chameleon"),
                    "games": games,
                }
            )

    os.makedirs("collections", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"collections": collections}, f, indent=2)
        f.write("\n")
    total = sum(len(c["games"]) for c in collections)
    print(f"wrote {OUT}: {len(collections)} collections, {total} entries")


if __name__ == "__main__":
    main()
