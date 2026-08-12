#!/usr/bin/env python3
"""
generate_bg_full_shard.py  --  Bhagavad Gita complete shard for chantGPT / Vagdhenu.

Fetches all 700 verses from vedicscriptures.github.io (public domain, no API key needed).
API: https://vedicscriptures.github.io/slok/{chapter}/{verse}

Fixes vs previous version:
  - Virama-aware syllable counting (previous version grossly overcounted, assigning
    upajati meter to ALL verses)
  - Ch13 verse count corrected to 35 (standard BG has 700 total, not 699)
  - UVACA_RE tightened: no longer strips 'prahuH' embedded in verse content
  - Minimum pada threshold lowered to 1 (handles half-verses like 1.21)
  - Half-pada pairs joined into full padas for cleaner TTS input

Usage:
  python scripts/generate_bg_full_shard.py
  python scripts/generate_bg_full_shard.py --chapters 11
  python scripts/generate_bg_full_shard.py --dry-run --limit 5

Render after generating:
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
# Chapter verse counts -- standard 700-verse BG (Gita Press critical edition)
# Ch13 = 35 (includes the introductory verse 13.01 "idam shariram kaunteya")
# ---------------------------------------------------------------------------
CHAPTER_VERSE_COUNTS = {
    1: 46,  2: 72,  3: 43,  4: 42,  5: 29,
    6: 47,  7: 30,  8: 28,  9: 34, 10: 42,
    11: 55, 12: 20, 13: 35, 14: 27, 15: 20,
    16: 24, 17: 28, 18: 78,
}
assert sum(CHAPTER_VERSE_COUNTS.values()) == 700, "verse count must total 700"

API_BASE = "https://vedicscriptures.github.io/slok"

# ---------------------------------------------------------------------------
# Meter knowledge
# ---------------------------------------------------------------------------
UPAJATI_VERSES = {
    (2, 20),
    (8,  9),
    (8, 10),
    (15, 4),   # tatah padam tat-parimargitavyam -- trishtubh class
} | {(11, v) for v in range(15, 51)}

# Hard-coded corrections for verses where the API pada encoding needs adjustment.
# bg_15_04: API splits second trishtubh line into two half-lines -> merge them.
# bg_01_20: genuine 3-line verse in this API encoding -> keep as-is.
# bg_01_21: half-verse (continuation of 1.20) -> keep as-is.
VERSE_CORRECTIONS = {
    (15, 4): "merge_last_two",
    (1, 20): "keep",
    (1, 21): "keep",
}



# ---------------------------------------------------------------------------
# Syllable counting -- virama-aware
#
# Rule: a Devanagari LETTER contributes 1 syllable UNLESS immediately followed
# by a virama (U+094D), which kills its inherent vowel (consonant cluster).
# Vowel signs (matras) and virama itself are not counted.
# ---------------------------------------------------------------------------
_VIRAMA = "\u094D"


def _count_syllables(text: str) -> int:
    n = 0
    for i, ch in enumerate(text):
        name = unicodedata.name(ch, "")
        if "DEVANAGARI LETTER" in name:
            # Dead consonant if next char is virama -- don't count
            next_ch = text[i + 1] if i + 1 < len(text) else ""
            if next_ch != _VIRAMA:
                n += 1
    return n


def get_meter(chapter: int, verse: int, padas: list) -> str:
    if (chapter, verse) in UPAJATI_VERSES:
        return "upajati"
    # Safety net for merged padas:
    # anushtubh after merging 2 half-padas = ~16 syllables
    # upajati after merging 2 half-padas = ~22 syllables
    # Threshold 19 correctly separates them
    if padas and max(_count_syllables(p) for p in padas) >= 19:
        return "upajati"
    return "anushtubh"


# ---------------------------------------------------------------------------
# Parsing
#
# The API uses | as a half-pada separator and || as verse-end marker.
# Speaker labels ("अर्जुन उवाच |") appear as their own segment.
# Strategy:
#   1. Remove verse-number markers  ||ch-vs||
#   2. Split at | and ||
#   3. Strip segments that are pure speaker labels
#   4. Join consecutive half-padas into full padas
# ---------------------------------------------------------------------------
_VERSENO_RE = re.compile(r"\|\|[\d\-।-॥]+\|\|")

# Speaker label: short segment (<=35 chars) ending in उवाच or उचुः
# NOT matching mid-verse uses like "प्राहुर्" or "उवाच पार्थ" as verse content
_SPEAKER_LABEL_RE = re.compile(
    r"^\s*[^\n]{1,35}(?:उवाच|उचुः)\s*$",
    re.MULTILINE,
)


def _is_speaker_label(segment: str) -> bool:
    """True if this pipe-separated segment is a speaker label, not verse content.
    Speaker labels (e.g. shriibhagavaanuvaaca, arjuna uvaaca) are short segments
    containing uvaca or ucuh with fewer than 9 syllables.
    Verse-embedded uses like 'uvaaca paartha pashyaitaan...' have >= 9 syllables.
    Uses Unicode escapes to avoid CRLF/encoding corruption of Devanagari literals.
    """
    # Two forms of uvaca:
    # \u0909\u0935\u093e\u091a = uvaca standalone (arjuna uvAca -- space before u)
    # \u0941\u0935\u093e\u091a = uvaca sandhi-joined (shriibhagavAn+uvAca -- u becomes vowel sign U+0941)
    # \u0909\u091a\u0941\u0903 = ucuh standalone
    _UVACA  = "\u0909\u0935\u093e\u091a"
    _UVACA2 = "\u0941\u0935\u093e\u091a"
    _UCUH   = "\u0909\u091a\u0941\u0903"
    s = segment.strip()
    if (_UVACA in s or _UVACA2 in s or _UCUH in s) and _count_syllables(s) < 9:
        return True
    return False


def parse_slok(slok_text: str) -> list:
    """
    Parse API 'slok' field into a list of full padas.

    The API separates half-padas with |. We:
      1. Remove verse-number markers
      2. Split at | and ||
      3. Drop speaker-label segments
      4. Clean each segment
      5. Pair consecutive segments into full padas (2 half-padas = 1 full pada)
    """
    text = _VERSENO_RE.sub("", slok_text.strip())
    # Split at || first, then |
    raw = re.split(r"\|\||\|", text)

    segments = []
    for seg in raw:
        seg = seg.strip().replace("\n", " ")
        seg = re.sub(r"\s+", " ", seg).strip()
        if not seg:
            continue
        if _is_speaker_label(seg):
            continue
        if _count_syllables(seg) < 3:   # skip tiny fragments
            continue
        segments.append(seg)

    if not segments:
        return []

    # Pair consecutive half-padas into full padas
    # Heuristic: if avg segment length looks like a half-pada (<= 10 syllables),
    # merge pairs; otherwise keep as-is
    avg_syl = sum(_count_syllables(s) for s in segments) / len(segments)
    if avg_syl <= 10 and len(segments) > 1:
        padas = []
        for i in range(0, len(segments), 2):
            if i + 1 < len(segments):
                padas.append(segments[i] + " " + segments[i + 1])
            else:
                padas.append(segments[i])   # odd leftover
    else:
        padas = segments

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
                print(f"\n  WARN: empty slok {chapter}.{verse}", file=sys.stderr)
                continue
            padas = parse_slok(slok)
            if not padas:
                print(f"\n  WARN: {chapter}.{verse} no padas parsed", file=sys.stderr)
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
# Build shard
# ---------------------------------------------------------------------------

def build_shard(records: list) -> list:
    shard = []
    for r in records:
        ch, vs, padas = r["chapter"], r["verse"], r["padas"]
        # Apply verse-specific corrections
        correction = VERSE_CORRECTIONS.get((ch, vs))
        if correction == "merge_last_two" and len(padas) >= 3:
            padas = padas[:-2] + [padas[-2] + " " + padas[-1]]

        entry = {
            "id":        f"bg_{ch:02d}_{vs:02d}",
            "meter":     get_meter(ch, vs, padas),
            "no_sandhi": True,
            "padas":     padas,
            "seed":      ch * 1000 + vs,
            "out":       f"bg_{ch:02d}_{vs:02d}.wav",
        }
        shard.append(entry)
    return shard


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(shard: list) -> list:
    warns = []
    for e in shard:
        if not e["padas"]:
            warns.append(f"{e['id']}: empty padas")
        for i, p in enumerate(e["padas"]):
            if not any("\u0900" <= c <= "\u097f" for c in p):
                warns.append(f"{e['id']} pada[{i}]: no Devanagari: {p!r:.40s}")
        syl = [_count_syllables(p) for p in e["padas"]] if e["padas"] else []
        if syl and e["meter"] == "anushtubh" and max(syl) > 18:
            warns.append(
                f"{e['id']}: anushtubh but max_syl={max(syl)} -- check meter"
            )
    return warns


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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

    # Spot-check syllable counts on a sample
    print("\n[syllable spot-check]", file=sys.stderr)
    for eid in ["bg_01_01", "bg_02_47", "bg_11_32"]:
        entry = next((e for e in shard if e["id"] == eid), None)
        if entry:
            syls = [_count_syllables(p) for p in entry["padas"]]
            print(f"  {eid} meter={entry['meter']} pada_syllables={syls}", file=sys.stderr)

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
