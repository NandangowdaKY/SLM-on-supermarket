"""
Build the Hugging Face dataset folder in the standard layout:

  data/train-00000-of-00001.parquet        chat Q&A the model was fine-tuned on (sft_train.jsonl)
  data/validation-00000-of-00001.parquet   held-out facts, half of sft_val.jsonl
  data/test-00000-of-00001.parquet         held-out facts, other half of sft_val.jsonl
  pretraining/{train,validation,test}-00000-of-00001.parquet
                                           276,484 baskets as text (stage A); the held-out 5 % is split
                                           in time order into validation (earlier) and test (later)
  domain/pretrain_corpus.jsonl             stage B corpus
  source/                                  raw CSV, research docs (cleaned + raw), statistics
  README.md                                dataset card

Validation/test are split by fact `group` (paraphrases of one fact never cross splits). The training
split is unchanged, so the published model's numbers still hold.

Usage:  python scripts/make_hf_dataset.py --out C:/Users/<you>/HF-upload/dataset
"""
import argparse
import hashlib
import json
import os
import shutil

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def to_frame(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        m = r["messages"]
        rows.append({"question": m[1]["content"], "answer": m[2]["content"], "system": m[0]["content"],
                     "messages": m, "source": r["source"].split(":")[0], "fact_group": r["group"]})
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--card", default=os.path.join(ROOT, "hf", "dataset_card.md"))
    a = ap.parse_args()

    out = a.out
    if os.path.exists(out):
        shutil.rmtree(out)
    for d in ["data", "pretraining", "domain", "source"]:
        os.makedirs(os.path.join(out, d))

    train = to_frame(os.path.join(ROOT, "data", "sft_train.jsonl"))
    held = to_frame(os.path.join(ROOT, "data", "sft_val.jsonl"))
    is_test = held.fact_group.map(lambda g: int(hashlib.md5(g.encode()).hexdigest(), 16) % 2 == 1)
    splits = {"train": train, "validation": held[~is_test], "test": held[is_test]}
    for name, df in splits.items():
        df.reset_index(drop=True).to_parquet(os.path.join(out, "data", f"{name}-00000-of-00001.parquet"), index=False)
        print(f"{name:<10} {len(df):>4} conversations, {df.fact_group.nunique():>3} facts")

    def lines(path):
        return [l.rstrip("\n") for l in open(path, encoding="utf-8") if l.strip()]
    b_train = lines(os.path.join(ROOT, "data", "transactions_corpus_train.txt"))
    b_held = lines(os.path.join(ROOT, "data", "transactions_corpus_val.txt"))
    half = len(b_held) // 2
    basket_splits = {"train": b_train, "validation": b_held[:half], "test": b_held[half:]}
    for name, rows in basket_splits.items():
        pd.DataFrame({"text": rows}).to_parquet(
            os.path.join(out, "pretraining", f"{name}-00000-of-00001.parquet"), index=False)
        print(f"baskets {name:<10} {len(rows):>7,}")

    copies = {
        "domain": ["data/pretrain_corpus.jsonl"],
        "source": ["combined_supermarket_data.csv", "design_thinking_merged.jsonl",
                   "data/raw/design_thinking_merged.raw.jsonl", "data/stats/dataset_stats.json"],
    }
    for folder, files in copies.items():
        for f in files:
            shutil.copy(os.path.join(ROOT, f), os.path.join(out, folder))

    card = open(a.card, encoding="utf-8").read()
    for name, df in splits.items():
        card = card.replace(f"__N_{name.upper()}__", str(len(df)))
    for name, rows in basket_splits.items():
        card = card.replace(f"__B_{name.upper()}__", f"{len(rows):,}")
    open(os.path.join(out, "README.md"), "w", encoding="utf-8").write(card)
    print("written ->", out)


if __name__ == "__main__":
    main()
