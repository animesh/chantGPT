#!/usr/bin/env python3
"""
generate_bg_shard.py -- Build a full Bhagavad Gita shard for chantGPT / Vagdhenu.

Source: GRETIL Bhagavad Gita Devanagari (public domain)
  https://gretil.sub.uni-goettingen.de/gretil/corpustei/sa/trans/eppur/mbh/sambbhgG.htm

Output: JSON shard consumable by:
  python src/render.py --shard bhagavad_gita_shard.json --results /tmp/res.json --outdir out/

Usage:
  # Auto-download and build shard (requires internet):
  python scripts/generate_bg_shard.py --output examples/bhagavad_gita_full_shard.json

  # From a local text file (one verse per block, see --help):
  python scripts/generate_bg_shard.py --input bg_devanagari.txt --output examples/bhagavad_gita_full_shard.json

  # Dry-run: print first 5 entries:
  python scripts/generate_bg_shard.py --dry-run --limit 5

Notes on meter:
  - BG is overwhelmingly anushtubh (4 padas, 8 syllables each, lines end with । ॥)
  - Chapter 11 has many trishtubh / jagati verses (11-12 syllables per pada)
  - The meter field drives reference-clip selection in Vagdhenu; wrong meter -> prosody mismatch
  - A simple syllable count heuristic is used here; manual review recommended for ch. 11.
"""

import argparse
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Syllable counting (approximate, for meter heuristic)
# ---------------------------------------------------------------------------
DEVANAGARI_VOWELS = set(
    "अ आ इ ई उ ऊ ऋ ॠ ऌ ए ऐ ओ औ"
    "ा ि ी ु ू ृ ॄ ॢ े ै ो ौ"
    .split()
)


def count_syllables(pada: str) -> int:
    """Very rough syllable count -- count vowel matras + independent vowels."""
    n = 0
    for ch in pada:
        cat = unicodedata.category(ch)
        name = unicodedata.name(ch, "")
        if "DEVANAGARI LETTER" in name and "VOWEL" in name:
            n += 1
        elif "DEVANAGARI VOWEL SIGN" in name:
            n += 1
        elif "DEVANAGARI LETTER" in name:
            # consonant with implicit 'a' unless followed by halanta / virama
            n += 1
    return n


def guess_meter(padas: list[str]) -> str:
    """
    Heuristic meter detection:
      anushtubh  -- ~8 syllables per pada
      trishtubh  -- ~11 syllables per pada
      jagati     -- ~12 syllables per pada
    """
    if not padas:
        return "anushtubh"
    # Use longest pada as proxy
    max_syl = max(count_syllables(p) for p in padas)
    if max_syl <= 9:
        return "anushtubh"
    elif max_syl <= 11:
        return "trishtubh"
    else:
        return "jagati"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
VERSE_RE = re.compile(
    r"(\d+\.\d+)\s*[।\|]?\s*\n?"  # chapter.verse number
)

PADA_SPLIT_RE = re.compile(r"[।॥\|]+")  # split on dandas


def split_into_padas(verse_text: str) -> list[str]:
    """
    Split a verse string on dandas into padas.
    Strips speaker labels (e.g. 'श्रीभगवानुवाच', 'अर्जुन उवाच').
    """
    # Remove speaker labels (text before first newline or colon that ends in 'उवाच')
    verse_text = re.sub(r"[^\n]*उवाच\s*[।\|]?\s*\n?", "", verse_text)
    # Remove verse number markers like ॥ 1 ॥ or (1)
    verse_text = re.sub(r"॥\s*\d+[\.\d]*\s*॥", "", verse_text)
    verse_text = re.sub(r"\(\d+\)", "", verse_text)
    # Split on dandas
    raw = PADA_SPLIT_RE.split(verse_text)
    padas = [p.strip() for p in raw if p.strip()]
    return padas


def parse_raw_text(text: str) -> list[dict]:
    """
    Parse a plain Devanagari BG text where chapters are delimited by
    'अथ ... अध्यायः' and verses by '॥ N ॥' markers.

    Returns list of dicts with keys: chapter, verse, padas, meter.
    """
    records = []
    current_chapter = 0

    # Split into chapter blocks
    chapter_blocks = re.split(r"अथ\s+\S+\s+अध्यायः", text)
    for ch_idx, block in enumerate(chapter_blocks[1:], start=1):
        current_chapter = ch_idx
        # Split into verse blocks by double danda + number
        verse_chunks = re.split(r"(?=॥\s*\d+[\.\d]*\s*॥)", block)
        verse_num = 0
        for chunk in verse_chunks:
            m = re.search(r"॥\s*(\d+)[\.\d]*\s*॥", chunk)
            if not m:
                continue
            verse_num = int(m.group(1))
            padas = split_into_padas(chunk)
            if not padas:
                continue
            meter = guess_meter(padas)
            records.append({
                "chapter": current_chapter,
                "verse": verse_num,
                "padas": padas,
                "meter": meter,
            })
    return records


# ---------------------------------------------------------------------------
# Shard building
# ---------------------------------------------------------------------------
def build_shard(records: list[dict], seed: int = 42) -> list[dict]:
    shard = []
    for r in records:
        ch = r["chapter"]
        vs = r["verse"]
        entry_id = f"bg_{ch:02d}_{vs:02d}"
        shard.append({
            "id": entry_id,
            "meter": r["meter"],
            "padas": r["padas"],
            "seed": seed,
            "out": f"{entry_id}.wav",
        })
    return shard


# ---------------------------------------------------------------------------
# Download helpers (optional)
# ---------------------------------------------------------------------------
GRETIL_URL = (
    "https://gretil.sub.uni-goettingen.de/gretil/corpustei/sa/trans/eppur/mbh/"
    "sambbhgG.htm"
)

WIKISOURCE_API = (
    "https://sa.wikisource.org/w/api.php?action=parse&page="
    "%E0%A4%B6%E0%A5%8D%E0%A4%B0%E0%A5%80%E0%A4%AE%E0%A4%A6%E0%A5%8D%E0%A4%AD%E0%A4%97%E0%A4%B5%E0%A4%A6%E0%A5%8D%E0%A4%97%E0%A5%80%E0%A4%A4%E0%A4%BE"
    "&prop=wikitext&format=json"
)


def fetch_gretil_bg() -> str:
    """Download GRETIL BG HTML and extract Devanagari text."""
    print(f"Fetching from GRETIL: {GRETIL_URL}", file=sys.stderr)
    with urllib.request.urlopen(GRETIL_URL, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", "", html)
    # Collapse whitespace
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r" +", " ", text)
    return text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", "-i", help="Local Devanagari BG text file (UTF-8). If omitted, downloads from GRETIL.")
    ap.add_argument("--output", "-o", default="examples/bhagavad_gita_full_shard.json", help="Output shard JSON path.")
    ap.add_argument("--seed", type=int, default=42, help="Random seed for render.")
    ap.add_argument("--chapters", help="Comma-separated list of chapter numbers to include (default: all 18).")
    ap.add_argument("--dry-run", action="store_true", help="Print shard to stdout without writing.")
    ap.add_argument("--limit", type=int, default=0, help="Only process first N verses (for testing).")
    args = ap.parse_args()

    # Load text
    if args.input:
        text = Path(args.input).read_text(encoding="utf-8")
    else:
        try:
            text = fetch_gretil_bg()
        except Exception as e:
            print(f"Download failed: {e}", file=sys.stderr)
            print("Tip: download BG Devanagari text manually and pass via --input.", file=sys.stderr)
            sys.exit(1)

    # Parse
    records = parse_raw_text(text)
    print(f"Parsed {len(records)} verses.", file=sys.stderr)

    # Filter chapters
    if args.chapters:
        wanted = {int(c) for c in args.chapters.split(",")}
        records = [r for r in records if r["chapter"] in wanted]
        print(f"After chapter filter: {len(records)} verses.", file=sys.stderr)

    # Limit
    if args.limit:
        records = records[: args.limit]

    # Build shard
    shard = build_shard(records, seed=args.seed)

    # Output
    json_str = json.dumps(shard, ensure_ascii=False, indent=2)
    if args.dry_run:
        print(json_str)
    else:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_str, encoding="utf-8")
        print(f"Wrote {len(shard)} entries to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
