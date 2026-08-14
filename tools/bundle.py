"""Builds platforms/bundle.json: every pack in one file.

Importing fetched one pack per console, which is a round trip each for a few
kilobytes. The packs are near-identical in shape, so one compressed stream costs
about what forty separate ones do and covers all of them.

Generated rather than hand-kept, and regenerated whenever a pack changes, because a
bundle that has drifted from the packs beside it is worse than no bundle: an import
would quietly install yesterday's launch arguments.
"""
import hashlib
import json
import os

PLATFORMS = "platforms"
OUT = os.path.join(PLATFORMS, "bundle.json")


def main():
    index_path = os.path.join(PLATFORMS, "index.json")
    with open(index_path, encoding="utf-8") as f:
        index = json.load(f)

    packs = {}
    for entry in index["platformList"]:
        name = entry["filename"]
        path = os.path.join(PLATFORMS, name)
        if not os.path.isfile(path):
            print("missing, skipped:", name)
            continue
        with open(path, encoding="utf-8") as f:
            packs[name] = json.load(f)

    # The index is what a device compares against, so it has to agree with the packs.
    #
    # It does not keep itself in step, and nothing said so. A pack was edited and its own
    # revisionNumber raised, the index was left alone, and every install went on
    # believing it had the current one: the change was committed, pushed, live, and
    # reached nobody. That had already happened once before anyone noticed - the
    # PlayStation pack carried its ARMSX1 player at revision 14 while the index
    # advertised 13, so the emulator we imported from upstream was never delivered.
    #
    # Checked before anything is written, because a bundle built from a stale index
    # carries the new players under the old numbers, which is the same silence one step
    # further along.
    disagreeing = [
        f"{name}: index says {entry.get('revisionNumber')}, "
        f"the pack says {packs[name].get('revisionNumber')}"
        for entry in index["platformList"]
        for name in [entry["filename"]]
        if name in packs and entry.get("revisionNumber") != packs[name].get("revisionNumber")
    ]
    if disagreeing:
        raise SystemExit(
            "index.json disagrees with the packs, so devices would not see these "
            "changes:\n  " + "\n  ".join(disagreeing) +
            "\n\nRaise the revisionNumber in index.json to match each pack."
        )

    # The revisions the bundle was built from, so a reader can tell at a glance
    # whether it matches the index it came with.
    revisions = {
        entry["filename"]: entry.get("revisionNumber")
        for entry in index["platformList"]
        if entry["filename"] in packs
    }

    bundle = {
        "formatVersion": 1,
        "count": len(packs),
        "revisions": revisions,
        "packs": packs,
    }
    text = json.dumps(bundle, indent=1, ensure_ascii=False, sort_keys=True)

    # Written only when it differs, so a scheduled run that changes nothing does not
    # produce a commit that says it did.
    if os.path.isfile(OUT):
        with open(OUT, encoding="utf-8") as f:
            if f.read() == text:
                print("bundle unchanged:", len(packs), "packs")
                return

    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    digest = hashlib.sha256(text.encode()).hexdigest()[:12]
    print("bundle written:", len(packs), "packs,", len(text) // 1000, "KB,", digest)


if __name__ == "__main__":
    main()
