#!/usr/bin/env python3
"""
sync_from_devrel.py [--apply]

The event pages on this site are hand-maintained, and they drifted: on
2026-09-11 Road to Mainnet #3 still read `event_status = "upcoming"` with a
live countdown to a date almost three months past, #4 had no page at all, #5
sat in `draft` and unpublished, and only two of the completed events linked
their recording. The site was telling the public something untrue.

The canonical record is the event YAML in the devrel repo. This script copies
the handful of fields that are FACTS out of it and leaves everything written by
a human alone. It never touches the page body, the speakers block, the venue,
the perks or the description.

Fields it owns:
    event_status      completed | upcoming, from the YAML status and the date
    recording_url     recap.recording_url
    slides_url        recap.slides_url
    countdown_target  present only while an event is still ahead of us
    registration_url  deposit.bethere_url

Pages are matched to events by DATE, because the file names follow three
different conventions and the BeThere URL is missing from three of them.
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import yaml

DEVREL = Path.home() / "solana-thailand-devrel-helper"
PAGES = Path(__file__).resolve().parent.parent / "docs" / "content" / "events"

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}

OWNED = ("event_status", "recording_url", "slides_url",
         "countdown_target", "registration_url")

# `date` is owned too, but lives at the top level of the front matter rather
# than under [extra], so it is handled separately. The events index sorts on
# it: weights had drifted to 3, 4, 4, 5, 6, 10 and 55 across seven pages and
# ordered the list at random.


def page_date(text: str) -> date | None:
    """'Sunday, 26 April 2026' -> date(2026, 4, 26)."""
    m = re.search(r'event_date\s*=\s*"[^,"]*,?\s*(\d{1,2})\s+(\w+)\s+(\d{4})"', text)
    if not m or m.group(2) not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))


def load_events() -> dict[date, dict]:
    out = {}
    for f in sorted((DEVREL / "events").glob("*.yml")):
        e = yaml.safe_load(f.read_text()) or {}
        if e.get("status") not in ("completed", "draft", "upcoming"):
            continue
        d = e.get("date")
        if isinstance(d, str):
            d = date.fromisoformat(d)
        if d:
            out[d] = e
    return out


def desired(e: dict) -> dict[str, str | None]:
    """What the owned fields should say. None means the key must not be there."""
    d = e["date"]
    if isinstance(d, str):
        d = date.fromisoformat(d)
    done = e.get("status") == "completed"
    recap = e.get("recap") or {}
    time = str(e.get("time") or "").split("–")[0].strip().replace(".", ":")
    return {
        "event_status": "completed" if done else "upcoming",
        # A countdown to a date in the past is worse than no countdown.
        "countdown_target": None if done else f"{d.isoformat()}T{time or '13:00'}:00+07:00",
        "recording_url": recap.get("recording_url") or None,
        "slides_url": recap.get("slides_url") or None,
        "registration_url": (e.get("deposit") or {}).get("bethere_url") or None,
    }


def set_key(text: str, key: str, value: str | None) -> tuple[str, str | None]:
    """Set, add or delete one TOML key inside [extra]. Returns (text, what changed)."""
    pat = re.compile(rf'^{key}\s*=\s*"[^"]*"\s*$\n?', re.M)
    cur = re.search(rf'^{key}\s*=\s*"([^"]*)"\s*$', text, re.M)
    current = cur.group(1) if cur else None
    if value is None:
        if cur is None:
            return text, None
        return pat.sub("", text), f"{key}: removed ({current})"
    if current == value:
        return text, None
    line = f'{key} = "{value}"\n'
    if cur is not None:
        return pat.sub(line, text, count=1), f"{key}: {current} -> {value}"
    # New key goes directly after event_status so the block stays readable.
    anchor = re.search(r'^event_status\s*=\s*"[^"]*"\s*$\n', text, re.M)
    if not anchor:
        return text, None
    at = anchor.end()
    return text[:at] + line + text[at:], f"{key}: + {value}"


def set_top_key(text: str, key: str, value: str) -> tuple[str, str | None]:
    """Set a top-level TOML key, above the [extra] table."""
    cur = re.search(rf'^{key}\s*=\s*(\S+)\s*$', text, re.M)
    if cur and cur.group(1) == value:
        return text, None
    if cur:
        return (text[:cur.start()] + f"{key} = {value}" + text[cur.end():],
                f"{key}: {cur.group(1)} -> {value}")
    anchor = re.search(r'^template\s*=\s*"[^"]*"\s*$\n', text, re.M)
    if not anchor:
        return text, None
    return (text[:anchor.end()] + f"{key} = {value}\n" + text[anchor.end():],
            f"{key}: + {value}")


def main() -> int:
    apply = "--apply" in sys.argv
    events = load_events()
    seen = set()
    changed_files = 0

    for f in sorted(PAGES.glob("*.md")):
        if f.name == "_index.md":
            continue
        text = f.read_text()
        d = page_date(text)
        if d is None:
            print(f"  {f.name}: no parsable event_date — skipped")
            continue
        e = events.get(d)
        if e is None:
            print(f"  {f.name}: {d} has no event YAML — skipped")
            continue
        seen.add(d)
        out, notes = text, []
        out, note = set_top_key(out, "date", d.isoformat())
        if note:
            notes.append(note)
        for key in OWNED:
            out, note = set_key(out, key, desired(e)[key])
            if note:
                notes.append(note)
        if not notes:
            continue
        changed_files += 1
        print(f"\n  {f.name}  ({d})")
        for n in notes:
            print(f"      {n}")
        if apply:
            f.write_text(out)

    missing = sorted(set(events) - seen)
    if missing:
        print("\n  events with NO page on the site:")
        for d in missing:
            print(f"      {d}  {events[d].get('title')}")

    print(f"\n  {changed_files} page(s) {'updated' if apply else 'would change'}"
          f", {len(missing)} event(s) unpublished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
