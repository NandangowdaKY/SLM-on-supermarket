# SuperMart SLM — a from-scratch Qwen3 small language model for retail analytics

AIML-C Design Thinking project. A ~340M-parameter language model with the **Qwen3 architecture, trained
from scratch** (no pretrained weights) on supermarket transaction data and retail research papers, and
served as a local chat assistant with **Ollama**.

## Links

| What | Where |
|---|---|
| Trained model (safetensors + GGUF + Modelfile) | https://huggingface.co/nandangowda/supermart-slm |
| Dataset (train / validation / test) | https://huggingface.co/datasets/nandangowda/supermarket-sales-qa |
| Ollama chat demo | `ollama run supermart-slm` (see section 7) |

```
research PDFs ─► Markdown ─► design_thinking_merged.jsonl ─┐   clean_jsonl.py
                                                            ├─► build_dataset.py ─► transactions_corpus (276k baskets)
combined_supermarket_data.csv (2.6M rows) ──────────────────┘                    ├► pretrain_corpus.jsonl
                                                                                 ├► sft_train/val.jsonl
                                                                                 └► dataset_stats.json
Stage A: baskets (pre-training from scratch) ─► Stage B: research papers ─► Stage C: chat Q&A fine-tuning
   ─► slm/export.py (Qwen3ForCausalLM safetensors) ─► convert_to_gguf.py ─► Ollama chat demo
   ─► Hugging Face: model + dataset (train / validation / test)
```

## Repository layout

| Path | What it is |
|---|---|
| `design thinking/*.md` | 23 research documents collected in the Empathise/Define phases (PDF → Markdown) |
| `design_thinking_merged.jsonl` | the documents as JSONL — **cleaned & de-duplicated** (11 unique docs) |
| `data/raw/design_thinking_merged.raw.jsonl` | original, uncleaned JSONL (23 rows), kept for reference |
| `combined_supermarket_data.csv` | 2,595,732 transaction lines (not in git: 400 MB) |
| `data/transactions_corpus_{train,val}.txt` | one line of text per basket — Stage A corpus (generated, not in git: 225 MB) |
| `data/pretrain_corpus.jsonl` | domain pre-training text |
| `data/sft_train.jsonl`, `data/sft_val.jsonl` | chat Q&A conversations (ChatML `messages`) |
| `data/stats/dataset_stats.json` | every statistic computed from the CSV |
| `scripts/clean_jsonl.py` | JSONL cleaning |
| `scripts/build_dataset.py` | CSV statistics → corpus + Q&A |
| `scripts/verify_export.py` | proves the exported model equals the trained model |
| `scripts/convert_to_gguf.py` | safetensors → GGUF (Q8_0) for Ollama, using the `gguf` package |
| `scripts/make_hf_dataset.py` | builds the Hugging Face dataset folder (train / validation / test parquet) |
| `slm/model.py` | Qwen3 model (GQA, QK-RMSNorm, RoPE, SwiGLU, RMSNorm) |
| `slm/export.py` | checkpoint → `Qwen3ForCausalLM` safetensors (input for GGUF conversion) |
| `5_slm_from_scratch_qwen.ipynb` | first experiment: Qwen3 SLM on TinyStories (original run, unchanged) |
| `6_supermart_slm_end_to_end.ipynb` | **main notebook — the complete pipeline with all code inline**: cleaning → dataset build → statistics → train/val/test files → tokenizer → model → 3-stage training → evaluation → export → GGUF → Ollama → question test → browser chat |
| `runs/6_supermart_slm_end_to_end_training_run_2026-11-18.ipynb` | the executed training run (18 Nov 2026, RTX 4050 Laptop, ~4.6 h) with every live training log line, kept unchanged |
| `ollama/Modelfile` | Ollama import (ChatML template, system prompt, stop tokens) |
| `app/server.py`, `app/index.html` | local chat web page on http://localhost:8000 (talks to Ollama; standard library only) |

## 1. Data collection

* **Research corpus** — 23 papers/articles on customer demographics, segmentation, gross margin, pricing &
  demand forecasting, payment methods (e-wallets, BNPL), revenue/RFM and tax engines were downloaded as PDF,
  converted to Markdown (`design thinking/`) and merged into `design_thinking_merged.jsonl`
  (`{"file_name", "content"}` per document).
* **Transactions** — `combined_supermarket_data.csv`: 2,500 households, 276,484 baskets, 582 stores,
  92,339 products, 102 weeks; product hierarchy (department, commodity, brand type), household demographics
  (age, income, marital status, household size/composition, kids, home ownership) and display/mailer promotion
  flags. Column layout follows the dunnhumby *The Complete Journey* dataset.

## 2. Data cleaning — `python scripts/clean_jsonl.py`

Problems found in the original JSONL and fixed:

| Problem | Fix |
|---|---|
| 12 of 23 rows were **byte-identical duplicates**: the same paper saved under several topic names (e.g. `Revenue_analysis` = `Sales_revenue_analysis` = `Total_sales_calculation` = `Total_sales_monitoring` = `Total_transaction_value`) | de-duplicated by SHA-256 → 11 docs; the other names kept in `aliases`/`topics` |
| form-feed/control characters, `(cid:1234)` glyph placeholders, private-use glyphs | removed |
| Unicode math letters (𝑡, 𝛽), ligatures, smart quotes, dashes | NFKC + ASCII normalisation |
| running page headers/footers repeated on every page, bare page numbers | removed |
| multi-column PDF pages rendered as fake Markdown tables | flattened to text |
| words hyphenated across lines (`is-\nsue`) | re-joined |
| author e-mail addresses | removed |

Result: 1.57M → 0.74M characters of cleaner text. The script is idempotent — it always cleans from the raw
backup in `data/raw/`.

## 3. Dataset build — `python scripts/build_dataset.py`

Computes statistics from the CSV (overview, basket and household spend, departments, top commodities,
national vs private label, discounts and coupons, sales by hour and week, stores, display/mailer effect,
spending by age, income, marital status, household type/size, kids, home ownership) and turns them into:

* **`transactions_corpus_{train,val}.txt`** — every basket as one line: store, week/day/time, household
  demographics, each item with department, brand type, size, quantity, price and discount, and the basket total.
  This is the main pre-training corpus — no general-English corpus (such as TinyStories) is used.
* **`pretrain_corpus.jsonl`** — the 11 cleaned papers + a retail glossary + data-insight paragraphs.
* **`sft_train.jsonl` / `sft_val.jsonl`** — ~520 ChatML conversations (253 distinct facts with 1–3
  question paraphrases each): CSV statistics, glossary definitions (gross margin, markup, RFM, GST, BNPL…),
  abstracts of the research papers and model identity. Every number in a sales answer is computed from the data;
glossary definitions and question templates were written with AI. Paraphrases of a
  fact share a `group` and are never split across train/validation.

### Train / validation / test record counts

A **basket** is one shopping trip — everything one household bought in one visit (one checkout receipt).
The CSV's 2,595,732 item rows group into 276,484 baskets.

| Data | One record = | Train | Validation | Test |
|---|---|---|---|---|
| Q&A (fine-tuning, stage C) | one chat conversation | 452 (223 facts) | 34 (13 facts) | 33 (17 facts) |
| Baskets (pre-training, stage A) | one shopping trip as text | 262,659 | 6,912 | 6,913 |

Validation and test contain only records the model never trained on. Baskets are split by time (the last 5 %
are held out); Q&A is split by fact. During training the held-out Q&A (validation + test, 67 conversations) and
held-out baskets were evaluated together as one validation set; neither was used to choose the model (the final
checkpoint is published). `python scripts/make_hf_dataset.py --out <folder>` writes these splits as parquet
files — published at [nandangowda/supermarket-sales-qa](https://huggingface.co/datasets/nandangowda/supermarket-sales-qa).

Example:
```json
{"messages": [
  {"role": "system", "content": "You are SuperMart SLM, ..."},
  {"role": "user", "content": "What is the average basket size?"},
  {"role": "assistant", "content": "The average basket value is $29.14 (median $17.07; 90th percentile $70.65). An average basket contains 9.4 line items (median 5)."}]}
```

## 4. Model

| | |
|---|---|
| Architecture | Qwen3 decoder-only transformer |
| Layers / width / FFN | 12 / 768 / 3072 (SwiGLU) |
| Attention | grouped-query, 12 query heads / 6 KV heads, head dim 64, QK-RMSNorm, RoPE (θ = 10,000) |
| Vocabulary | Qwen3 BPE, 151,936 rows (includes `<\|im_start\|>`, `<\|im_end\|>`) |
| Context | 512 tokens |
| Parameters | ~340M (233M of them in the untied embedding + LM head) |

## 5. Training (local GPU) — `6_supermart_slm_end_to_end.ipynb`

The notebook contains every step's code; the files in `scripts/`, `slm/` and `app/` are the same code as standalone
command-line tools. With `RETRAIN = False` (default) it loads the trained checkpoints and prints their saved loss
histories; set `RETRAIN = True` to train all three stages again.

| Stage | Data | Objective | Default steps |
|---|---|---|---|
| A | `transactions_corpus_*.txt`: all 276,484 baskets written as text (~100M tokens, last 5 % by time = validation) | next-token prediction, learning the language of the basket data | 4,000 on 6 GB (≈33M tokens), ≈3.9 h |
| B | `pretrain_corpus.jsonl` (90/10 split per doc) | next-token prediction, domain adaptation | 800 on 6 GB, ≈22 min |
| C | `sft_*.jsonl` | next-token loss on **assistant tokens only** | 800 on 6 GB, ≈20 min |

Optimiser: AdamW (β 0.9/0.95, weight decay 0.1), linear warm-up + cosine decay, grad-clip 1.0, bf16 autocast
with fp32 master weights. On GPUs with < 12 GB (e.g. RTX 4050 Laptop, 6 GB) the notebook automatically
uses 8-bit AdamW (bitsandbytes), gradient checkpointing and small micro-batches with gradient accumulation.

Fixes compared with notebook 5: cell order (config before model), `min_lr` was larger than `learning_rate`
(so the cosine "decay" increased the LR), scheduler stepped per micro-batch, no EOS between documents, vocabulary
too small for chat tokens, pure-bf16 weights.

## 6. Results

Trained on one RTX 4050 Laptop GPU (6 GB), about 4.6 hours in total.

| Stage | Final train loss | Final validation loss | Best validation loss | Validation perplexity |
|---|---|---|---|---|
| A — baskets (pre-training from scratch) | 0.455 | 0.529 | 0.529 | 1.7 |
| B — research papers (domain) | 1.317 | 6.635 | 5.766 | 761 |
| C — chat Q&A (fine-tuning) | 0.011 | 2.871 | 1.927 | 17.7 |

**Numeric fact recall** — share of the numbers in the reference answer that the model reproduces
(greedy decoding):

| Questions | Recall |
|---|---|
| Seen in training (sample of 50) | **95.3 %** |
| Held out of chat fine-tuning (validation + test) | **4.8 %** |

What this means:
* Stage A learned the structure of the basket data well (train and validation loss are close).
* Stage B over-fits: 11 papers are far too little text for a model of this size.
* Stage C memorises the trained facts almost perfectly, which is what the chat demo relies on, but it does not
  answer the held-out questions — it answers them confidently and wrongly. The answers to 57 of the 67 held-out questions also appear in the stage B domain corpus (about 38 of them in its training part), because that corpus was built before the Q&A split. So these questions were not seen as chat examples, but many of their facts were seen as text.

The notebook also shows loss curves for all three stages and sample chats.

## 7. Setup (to re-train)

```bash
python -m venv C:\Users\<you>\venvs\supermart-slm
C:\Users\<you>\venvs\supermart-slm\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements.txt
python -m ipykernel install --user --name supermart-slm --display-name "Python (supermart-slm GPU)"
```
Keep the venv outside the OneDrive folder. Open `6_supermart_slm_end_to_end.ipynb` in VS Code/Jupyter, pick the
**Python (supermart-slm GPU)** kernel and run all cells.

To rebuild the data only:
```bash
python scripts/clean_jsonl.py
python scripts/build_dataset.py
```

To rebuild the Hugging Face dataset folder (train / validation / test parquet):
```bash
python scripts/make_hf_dataset.py --out HF-upload/dataset
```

The CSV is not in this repository (400 MB) — download it from the
[dataset repo](https://huggingface.co/datasets/nandangowda/supermarket-sales-qa) (`source/combined_supermarket_data.csv`)
and place it in the project root before rebuilding the data.

## 8. Ollama chat demo

The notebook converts the final checkpoint to the standard `Qwen3ForCausalLM` layout (`slm/export.py`; the
only difference, the √d_model embedding scale, is folded into the embedding matrix — `scripts/verify_export.py`
checks the logits match exactly), then to GGUF with `scripts/convert_to_gguf.py` (Q8_0, 367 MB): `ollama/supermart-slm-q8_0.gguf`.

The GGUF is too large for GitHub, so without re-training, download the trained model from Hugging Face:

1. Install Ollama from https://ollama.com/download.
2. Open https://huggingface.co/nandangowda/supermart-slm/tree/main and download `supermart-slm-q8_0.gguf`
   into this repository's `ollama/` folder (next to `Modelfile`). Or with the Hugging Face CLI:
   `hf download nandangowda/supermart-slm supermart-slm-q8_0.gguf --local-dir ollama`
3. Import and chat:

```bash
cd ollama
ollama create supermart-slm -f Modelfile
ollama run supermart-slm
>>> Which departments generate the most sales?
>>> What is gross margin?
```

Ask questions the model was trained on (see `data/sft_train.jsonl`), e.g. *What is the average basket size?*,
*What time of day do customers shop the most?*, *How does spending vary by age group?*, *Explain RFM analysis.*

## 9. Chat in the browser (localhost)

After the Ollama step above, start the local web app from the repository root (Python standard library only,
no installs):

```bash
python app/server.py
```

Then open **http://localhost:8000**. The page shows example questions the model was trained on (click one, or
type your own), streams the answer as it is generated, and shows whether Ollama and the `supermart-slm` model
are available. Each question is sent on its own, matching how the model was fine-tuned. Stop with **Ctrl + C**.
Use `--port 9000` for another port. Ollama itself also serves an API at `http://localhost:11434`.

## Limitations

A small model trained from scratch on a narrow domain: it reliably reproduces facts it was fine-tuned on, but
can invent numbers for questions outside them. Research-paper text extracted from PDFs still contains some
words without spaces. Not for real financial decisions.

## Known issues

* **Leak between stages:** The answers to 57 of the 67 held-out questions also appear in the stage B domain corpus (about 38 of them in its training part), because that corpus was built before the Q&A split. So these questions were not seen as chat examples, but many of their facts were seen as text.
* **Wrong identity answer:** asked "How were you trained?", the model says it was pre-trained on general English
  text. That is false (it was pre-trained on supermarket baskets) and comes from an outdated training answer.

## Use of AI

An AI assistant (Claude, Anthropic) wrote most of the code, the glossary definitions, the question templates and
the figures, and drafted the documentation. The team supplied the data and the starting notebook, directed the work,
ran the training on their own laptop (18 Nov 2026) and published the results.
