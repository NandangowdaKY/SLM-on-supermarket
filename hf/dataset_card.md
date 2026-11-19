---
license: other
language: [en]
task_categories: [question-answering, text-generation]
tags: [retail, supermarket, sales, transactions, chatml, sft]
size_categories: [100K<n<1M]
configs:
  - config_name: default
    data_files:
      - split: train
        path: data/train-00000-of-00001.parquet
      - split: validation
        path: data/validation-00000-of-00001.parquet
      - split: test
        path: data/test-00000-of-00001.parquet
  - config_name: pretraining
    data_files:
      - split: train
        path: pretraining/train-00000-of-00001.parquet
      - split: validation
        path: pretraining/validation-00000-of-00001.parquet
      - split: test
        path: pretraining/test-00000-of-00001.parquet
---

# SuperMart SLM — supermarket sales Q&A

Chat question–answer data used to fine-tune [nandangowda/supermart-slm](https://huggingface.co/nandangowda/supermart-slm),
a Qwen3-style language model trained from scratch, plus the corpora it was pre-trained on.
Every number in an answer is computed from a 2.6M-line supermarket transaction dataset.
Code: https://github.com/NandangowdaKY/SLM-on-supermarket

## Overview — two subsets, each with train / validation / test

| Subset (config) | What a record is | Train | Validation | Test |
|---|---|---|---|---|
| `default` (Q&A, `data/`) | one chat conversation (question + answer) | __N_TRAIN__ | __N_VALIDATION__ | __N_TEST__ |
| `pretraining` (`pretraining/`) | one shopping basket (a checkout receipt) written as text | __B_TRAIN__ | __B_VALIDATION__ | __B_TEST__ |

A **basket** is one shopping trip: all items one household bought together in one visit. The 2,595,732
item-level rows of the CSV group into 276,484 baskets.

## Q&A subset (`data/`) — fine-tuning (stage C)

| Split | Conversations | Use |
|---|---|---|
| train | __N_TRAIN__ | fine-tuning |
| validation | __N_VALIDATION__ | held-out facts, monitoring |
| test | __N_TEST__ | held-out facts, final evaluation |

Validation and test contain **facts never seen in training**. Paraphrases of one fact share a `fact_group`
and never cross splits.

How they were used: during training, validation + test (67 conversations) were monitored together as one
held-out set; neither was used to choose the model (the final checkpoint is published). On these never-seen
facts the model reproduces only 4.8 % of the reference numbers, against 95.3 % on trained facts.

| Column | Type | Content |
|---|---|---|
| `question` | string | user question |
| `answer` | string | reference answer |
| `system` | string | system prompt |
| `messages` | list of {role, content} | full ChatML conversation (system, user, assistant) |
| `source` | string | `supermarket_csv`, `glossary`, `research` or `identity` |
| `fact_group` | string | id of the underlying fact |

```python
from datasets import load_dataset
ds = load_dataset("nandangowda/supermarket-sales-qa")
print(ds["train"][0]["question"], "->", ds["train"][0]["answer"])
```

## Pretraining subset (`pretraining/`) — pre-training from scratch (stage A)

One column, `text`: one basket per row, e.g.

> Store 396, week 1, day 1 at 09:46. Household 1172 (age 25-34, single, income 50-74K, ...). Bought: Body Wash (Drug Gm, national brand) x1 for $2.29; Toothpaste (Drug Gm, national brand, 6 OZ) x1 for $2.00, saved $0.99; ... Basket total $23.41 for 9 items.

Baskets are ordered by time. The model trained on the first 95 % (train); the last 5 % were held out and split
in time order into validation (earlier half) and test (later half).

```python
from datasets import load_dataset
baskets = load_dataset("nandangowda/supermarket-sales-qa", "pretraining")
```

## Other files

| Path | Content |
|---|---|
| `domain/pretrain_corpus.jsonl` | stage B domain corpus: 11 research papers + glossary + data-insight paragraphs |
| `source/combined_supermarket_data.csv` | 2,595,732 transaction lines: 2,500 households, 276,484 baskets, 582 stores, 92,339 products, 102 weeks (dunnhumby *The Complete Journey* schema) |
| `source/design_thinking_merged.jsonl` | research documents, cleaned and de-duplicated (11 docs) |
| `source/design_thinking_merged.raw.jsonl` | the same documents before cleaning (23 rows, 12 exact duplicates) |
| `source/dataset_stats.json` | every aggregate computed from the CSV |

## Key statistics

* Total sales **$8,057,463.08**; average basket **$29.14** (median $17.07), 9.4 line items
* Top departments: Grocery 50.8 %, Drug GM 13.1 %, Produce 6.9 %, Meat 6.8 %, Kiosk-Gas 6.8 %
* National brands 72.2 % of sales, private label 27.8 %
* Sales peak at 17:00–18:00; loyalty discounts on 50.2 % of line items

## How it was built

```bash
python scripts/clean_jsonl.py        # de-duplicate + clean the research JSONL
python scripts/build_dataset.py      # statistics, basket corpus, domain corpus, Q&A
python scripts/make_hf_dataset.py --out <folder>   # this layout
```
