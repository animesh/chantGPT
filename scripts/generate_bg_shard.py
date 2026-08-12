#!/usr/bin/env python3
"""
generate_bg_full_shard.py  --  Bhagavad Gita complete shard for chantGPT / Vagdhenu.

Fetches all 700 verses from vedicscriptures.github.io (public domain, no API key needed).
API: https://vedicscriptures.github.io/slok/{chapter}/{verse}
slok field format: "speaker uvaca |\npada1 |\npada2 ||ch-vs||"

Usage:
  # Full 700-verse shard (~5 min to fetch):
  python scripts/generate_bg_full_shard.py

  # Single chapter:
  python scripts/generate_bg_full_shard.py --chapters 11

  # Dry-run first 5 verses:
  python scripts/generate_bg_full_shard.py --dry-run --limit 5

  # Render after generating:
  mkdir -p out/bhagavad_gita_full
  export PYTHONPATH="$PWD/BigVGAN:$PWD/src:$PYTHONPATH"
  python src/render.py \
      --shard examples/bhagavad_gita_full_shard.json \
      --results bg_full_results.json \
      --outdir out/bhagavad_gita_full/ \
      --speed 0.85
"""

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path
from collections import Counter

# ---------------------------------------------------------------------------
# Chapter verse counts (standard critical edition -- 700 total)
# ---------------------------------------------------------------------------
CHAPTER_VERSE_COUNTS = {
    1: 46,  2: 72,  3: 43,  4: 42,  5: 29,
    6: 47,  7: 30,  8: 28,  9: 34, 10: 42,
    11: 55, 12: 20, 13: 34, 14: 27, 15: 20,
    16: 24, 17: 28, 18: 78,
}

API_BASE = "https://vedicscriptures.github.io/slok"

# ---------------------------------------------------------------------------
# Meter knowledge
# ---------------------------------------------------------------------------
# Known trishtubh-class verses (upajati bank key, 11-syllable padas)
UPAJATI_VERSES = {
    (2, 20),   # na jayate mriyate va kadacit
    (8,  9),   # kavim puranam anusasitaram
    (8, 10),   # prayana-kale manasacalena
} | {(11, v) for v in range(15, 51)}   # Vishvarupa darshana

# Famous verses rendered at slightly slower pace
SLOW_VERSES = {
    (2, 47), (4, 7), (4, 8), (6, 5),
    (9, 22), (11, 32), (18, 65), (18, 66),
}

SPEED_SLOW = 0.85

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_UVACA_RE  = re.compile(r"^[^\n|]*(?:उवाच|उचुः|अब्रवीत्|प्राह)[^\n]*\n?", re.MULTILINE)
_VERSENO_RE = re.compile(r"\|\|[\d\-।-॥]+\|\|")


def _count_syllables(text: str) -> int:
    n = 0
    for ch in text:
        name = unicodedata.name(ch, "")
        if "DEVANAGARI LETTER" in name or "DEVANAGARI VOWEL SIGN" in name:
            n += 1
    return n


def get_meter(chapter: int, verse: int, padas: list) -> str:
    if (chapter, verse) in UPAJATI_VERSES:
        return "upajati"
    if padas and max(_count_syllables(p) for p in padas) >= 13:
        return "upajati"
    return "anushtubh"


def parse_slok(slok_text: str) -> list:
    text = slok_text.strip()
    text = _UVACA_RE.sub("", text)
    text = _VERSENO_RE.sub("", text)
    raw = re.split(r"\|\||\|", text)
    padas = []
    for p in raw:
        p = p.strip().replace("\n", " ")
        p = re.sub(r"\s+", " ", p)
        if p and _count_syllables(p) >= 4:
            padas.append(p)
    return padas

# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_verse(chapter: int, verse: int, retries: int = 3):
    url = f"{API_BASE}/{chapter}/{verse}"
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (chantGPT shard builder)"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  WARN: failed {chapter}.{verse}: {e}", file=sys.stderr)
                return None


def fetch_all(chapters: list, limit: int = 0, sleep_ms: int = 100) -> list:
    records = []
    fetched = 0
    for chapter in chapters:
        n = CHAPTER_VERSE_COUNTS.get(chapter, 0)
        if n == 0:
            print(f"  WARN: unknown chapter {chapter}", file=sys.stderr)
            continue
        print(f"Chapter {chapter:2d} ({n} verses)...", file=sys.stderr, end=" ", flush=True)
        ch_ok = 0
        for verse in range(1, n + 1):
            if limit and fetched >= limit:
                break
            data = fetch_verse(chapter, verse)
            if not data:
                continue
            slok = data.get("slok", "")
            if not slok:
                continue
            padas = parse_slok(slok)
            if len(padas) < 2:
                print(f"\n  WARN: {chapter}.{verse} parsed to <2 padas", file=sys.stderr)
                continue
            records.append({"chapter": chapter, "verse": verse, "padas": padas})
            fetched += 1
            ch_ok += 1
            if sleep_ms:
                time.sleep(sleep_ms / 1000)
        print(f"OK {ch_ok}/{n}", file=sys.stderr)
        if limit and fetched >= limit:
            break
    return records

# ---------------------------------------------------------------------------
# Build + validate
# ---------------------------------------------------------------------------

def build_shard(records: list) -> list:
    shard = []
    for r in records:
        ch, vs, padas = r["chapter"], r["verse"], r["padas"]
        entry = {
            "id":        f"bg_{ch:02d}_{vs:02d}",
            "meter":     get_meter(ch, vs, padas),
            "no_sandhi": True,
            "padas":     padas,
            "seed":      ch * 1000 + vs,
            "out":       f"bg_{ch:02d}_{vs:02d}.wav",
        }
        if (ch, vs) in SLOW_VERSES:
            entry["speed"] = SPEED_SLOW
        shard.append(entry)
    return shard


def validate(shard: list) -> list:
    warns = []
    for e in shard:
        if len(e["padas"]) not in (2, 4):
            warns.append(f"{e['id']}: {len(e['padas'])} padas (expected 2 or 4)")
        for i, p in enumerate(e["padas"]):
            if not any("\u0900" <= c <= "\u097f" for c in p):
                warns.append(f"{e['id']} pada[{i}]: no Devanagari: {p!r:.40s}")
        syl = [_count_syllables(p) for p in e["padas"]]
        if syl and e["meter"] == "anushtubh" and max(syl) > 12:
            warns.append(f"{e['id']}: anushtubh but max_syl={max(syl)} -- possible trishtubh")
    return warns

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--output", "-o", default="examples/bhagavad_gita_full_shard.json")
    ap.add_argument("--chapters", help="e.g. --chapters 2,11")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep-ms", type=int, default=100)
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args()

    chapters = list(range(1, 19))
    if args.chapters:
        chapters = [int(c) for c in args.chapters.split(",")]

    print(f"Fetching {len(chapters)} chapter(s) from {API_BASE}", file=sys.stderr)
    records = fetch_all(chapters, limit=args.limit, sleep_ms=args.sleep_ms)
    print(f"\nTotal: {len(records)} verses fetched", file=sys.stderr)

    if not records:
        print("ERROR: no verses fetched.", file=sys.stderr)
        sys.exit(1)

    shard = build_shard(records)

    if not args.no_validate:
        warns = validate(shard)
        if warns:
            print(f"\n[validation] {len(warns)} warning(s):", file=sys.stderr)
            for w in warns[:20]:
                print(f"  WARN {w}", file=sys.stderr)
            if len(warns) > 20:
                print(f"  ... and {len(warns) - 20} more", file=sys.stderr)
        else:
            print("[validation] all OK", file=sys.stderr)

    mc = Counter(e["meter"] for e in shard)
    print("\n[meters]", file=sys.stderr)
    for m, n in mc.most_common():
        print(f"  {m:20s} {n}", file=sys.stderr)
    print(f"  slow-verse overrides: {sum(1 for e in shard if 'speed' in e)}", file=sys.stderr)

    out_json = json.dumps(shard, ensure_ascii=False, indent=2)
    if args.dry_run:
        print(out_json)
    else:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out_json, encoding="utf-8")
        print(f"\nWrote {len(shard)} entries -> {out_path}", file=sys.stderr)
        print(
            f"\nRender command:\n"
            f"  mkdir -p out/bhagavad_gita_full\n"
            f"  export PYTHONPATH=\"$PWD/BigVGAN:$PWD/src:$PYTHONPATH\"\n"
            f"  python src/render.py \\\n"
            f"      --shard {args.output} \\\n"
            f"      --results bg_full_results.json \\\n"
            f"      --outdir out/bhagavad_gita_full/ \\\n"
            f"      --speed 0.85",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
