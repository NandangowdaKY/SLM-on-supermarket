"""
Clean the research-document corpus (design_thinking_merged.jsonl).

Problems found in the raw file (23 rows):
  * 12 rows are exact duplicates: several Markdown files in `design thinking/`
    are byte-identical copies saved under different topic names
    (e.g. Revenue_analysis == Sales_revenue_analysis == Total_sales_calculation ...).
    Training on them would over-weight 5 papers by 2-5x and leak between
    train/validation splits.  -> 23 rows become 11 unique documents.
  * PDF-extraction artefacts: form-feed / control characters, "(cid:NNNN)"
    glyph placeholders, private-use-area glyphs, Unicode math-italic letters,
    running page headers/footers repeated on every page, bare page numbers,
    empty Markdown table rows and runs of blank lines.
  * Multi-column PDF pages rendered as fake Markdown tables
    ("| are calculated | | from this | selected |") -> flattened to plain text.
  * Author e-mail addresses (personal data) - removed before publishing the
    dataset on Hugging Face.

Usage:
    python scripts/clean_jsonl.py                     # cleans in place, keeps a .raw backup
    python scripts/clean_jsonl.py --in a.jsonl --out b.jsonl
"""
import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ASCII_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": " - ", "−": "-", "‐": "-", "‑": "-",
    "…": "...", "•": "-", " ": " ", "❏": "", "❒": "", "­": "",
}

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
CID_RE = re.compile(r"\(cid:\d+\)")
CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
PUA_RE = re.compile(r"[-]")
TABLE_SEP_RE = re.compile(r"^\|?[\s|:-]*\|[\s|:-]*$")      # | --- | --- |  or |   |   |
PAGE_NUM_RE = re.compile(r"^(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?$", re.I)
MULTISPACE_RE = re.compile(r"[ \t]{2,}")


def topic_from_filename(name: str) -> str:
    stem = os.path.splitext(name)[0]
    stem = re.sub(r"\s*\(\d+\)$", "", stem)            # "X (2)" -> "X"
    stem = re.sub(r"_Research$", "", stem)
    return stem.replace("_", " ").strip()


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = CTRL_RE.sub("\n", text)                     # form-feeds = page breaks
    text = CID_RE.sub("", text)
    text = PUA_RE.sub("", text)
    text = unicodedata.normalize("NFKC", text)         # math-italic letters, ligatures
    for k, v in ASCII_MAP.items():
        text = text.replace(k, v)
    text = EMAIL_RE.sub("", text)

    lines = [MULTISPACE_RE.sub(" ", ln).strip() for ln in text.split("\n")]

    # running headers / footers: identical non-trivial lines repeated on many pages
    counts = collections.Counter(ln for ln in lines if ln)
    boiler = {ln for ln, c in counts.items()
              if c >= 4 and len(ln) >= 12 and not ln.startswith("|")}

    out = []
    for ln in lines:
        if ln in boiler:
            continue
        if PAGE_NUM_RE.match(ln):
            continue
        if ln and TABLE_SEP_RE.match(ln):
            continue                                   # "| --- | --- |" and empty "|  |  |" rows
        if ln.startswith("|"):
            # The PDF->Markdown converter turned multi-column page layouts into
            # fake tables ("| are calculated | | from this | ...").  A small LM
            # learns far better from the flattened sentence text.
            ln = " ".join(c.strip() for c in ln.strip("|").split("|") if c.strip())
        if len(ln) <= 2 and not ln.isdigit():
            ln = ""                                    # stray math fragments: "i", "k", ")"
        out.append(ln)

    text = "\n".join(out)
    text = re.sub(r"([a-z])-\n([a-z])", r"\1\2", text)   # re-join hyphenated line breaks: "is-\nsue"
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=os.path.join(ROOT, "design_thinking_merged.jsonl"))
    ap.add_argument("--out", default=None, help="default: overwrite input (backup kept as *.raw.jsonl)")
    args = ap.parse_args()

    out_path = args.out or args.inp
    src = args.inp
    if out_path == args.inp:
        backup = os.path.join(ROOT, "data", "raw", "design_thinking_merged.raw.jsonl")
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        if not os.path.exists(backup):
            shutil.copyfile(args.inp, backup)
        src = backup                                   # always clean from the pristine copy

    rows = []
    with open(src, encoding="utf-8-sig") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  ! skipping malformed line {n}: {e}")

    by_hash = collections.OrderedDict()
    for r in rows:
        content = r.get("content") or r.get("text") or ""
        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if h in by_hash:
            by_hash[h]["aliases"].append(r["file_name"])
        else:
            by_hash[h] = {"file_name": r["file_name"], "aliases": [], "raw": content}

    cleaned = []
    for i, (h, d) in enumerate(by_hash.items()):
        text = clean_text(d["raw"])
        topics = [topic_from_filename(d["file_name"])] + [topic_from_filename(a) for a in d["aliases"]]
        cleaned.append({
            "id": f"doc-{i:03d}",
            "file_name": d["file_name"],
            "aliases": d["aliases"],
            "topics": sorted(set(topics), key=topics.index),
            "num_chars": len(text),
            "num_words": len(text.split()),
            "sha256": h[:16],
            "content": text,
        })

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for r in cleaned:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    raw_chars = sum(len(r.get("content", "")) for r in rows)
    print(f"rows in : {len(rows)}  ({raw_chars:,} chars)")
    print(f"rows out: {len(cleaned)} unique docs ({sum(r['num_chars'] for r in cleaned):,} chars)")
    for r in cleaned:
        alias = f"  (+{len(r['aliases'])} duplicate: {', '.join(r['aliases'])})" if r["aliases"] else ""
        print(f"  {r['id']} {r['file_name']:<45} {r['num_words']:>7,} words{alias}")
    print(f"written -> {out_path}")


if __name__ == "__main__":
    main()
