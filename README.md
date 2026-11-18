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
                                                            ├─► build_dataset.py ─► pretrain_corpus.jsonl
combined_supermarket_data.csv (2.6M rows) ──────────────────┘                    └► sft_train/val.jsonl
                                                                                     dataset_stats.json
276k baskets as text ─► Stage A: pre-training from scratch ─► Stage B: domain pre-training ─► Stage C: chat SFT
            ─► slm/export.py (Qwen3ForCausalLM safetensors) ─► convert_to_gguf.py ─► Ollama chat demo
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
| `slm/model.py` | Qwen3 model (GQA, QK-RMSNorm, RoPE, SwiGLU, RMSNorm) |
| `slm/export.py` | checkpoint → `Qwen3ForCausalLM` safetensors (input for GGUF conversion) |
| `5_slm_from_scratch_qwen.ipynb` | first experiment: Qwen3 SLM on TinyStories (original run, unchanged) |
| `6_supermart_slm_end_to_end.ipynb` | **main notebook**: data → training → evaluation → GGUF |
| `ollama/Modelfile` | Ollama import (ChatML template, system prompt, stop tokens) |

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
  This is the main pre-training corpus — the model is trained **only on our own data** (no TinyStories).
* **`pretrain_corpus.jsonl`** — the 11 cleaned papers + a retail glossary + data-insight paragraphs.
* **`sft_train.jsonl` / `sft_val.jsonl`** — ~520 ChatML conversations (253 distinct facts with 1–3
  question paraphrases each): CSV statistics, glossary definitions (gross margin, markup, RFM, GST, BNPL…),
  paper summaries and model identity. Every number in an answer is computed from the data. Paraphrases of a
  fact share a `group` and are never split across train/validation.

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

| Stage | Data | Objective | Default steps |
|---|---|---|---|
| A | `transactions_corpus_*.txt`: all 276,484 baskets written as text (~100M tokens, last 5 % by time = validation) | next-token prediction, learning language from our own data | 4,000 on 6 GB (≈33M tokens), ≈4.5 h |
| B | `pretrain_corpus.jsonl` (90/10 split per doc) | next-token prediction, domain adaptation | 800 on 6 GB, ≈30 min |
| C | `sft_*.jsonl` | next-token loss on **assistant tokens only** | 800 on 6 GB, ≈1.5 h |

Optimiser: AdamW (β 0.9/0.95, weight decay 0.1), linear warm-up + cosine decay, grad-clip 1.0, bf16 autocast
with fp32 master weights. On GPUs with < 12 GB (e.g. RTX 4050 Laptop, 6 GB) the notebook automatically
uses 8-bit AdamW (bitsandbytes), gradient checkpointing and small micro-batches with gradient accumulation.

Fixes compared with notebook 5: cell order (config before model), `min_lr` was larger than `learning_rate`
(so the cosine "decay" increased the LR), scheduler stepped per micro-batch, no EOS between documents, vocabulary
too small for chat tokens, pure-bf16 weights.

Evaluation in the notebook: train/val loss curves, validation perplexity, numeric fact recall (share of numbers
in the reference answer reproduced by the model) on seen vs. unseen facts, and sample chats.

## 6. Setup

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

## 7. Ollama chat demo

The notebook converts the final checkpoint to the standard `Qwen3ForCausalLM` layout (`slm/export.py`; the
only difference, the √d_model embedding scale, is folded into the embedding matrix — `scripts/verify_export.py`
checks the logits match exactly), then to GGUF with `scripts/convert_to_gguf.py` (Q8_0, 367 MB): `ollama/supermart-slm-q8_0.gguf`.

```bash
# install Ollama from https://ollama.com/download, then:
cd ollama
ollama create supermart-slm -f Modelfile
ollama run supermart-slm
>>> Which departments generate the most sales?
>>> What is gross margin?
```

## Limitations

A small model trained from scratch on a narrow domain: it reliably reproduces facts it was fine-tuned on, but
can invent numbers for questions outside them. Research-paper text extracted from PDFs still contains some
words without spaces. Not for real financial decisions.
