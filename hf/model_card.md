---
license: other
language: [en]
library_name: transformers
pipeline_tag: text-generation
tags: [qwen3, small-language-model, from-scratch, retail, supermarket, ollama, gguf]
datasets: [__HF_USER__/supermart-slm-data]
---

# SuperMart SLM

A 340M-parameter **Qwen3-architecture language model trained from scratch** (no pretrained weights) on
supermarket transaction data and retail research papers. It answers retail-analytics questions about a
2.6M-line supermarket transaction dataset. Built for the AIML-C Design Thinking project.

* Code: https://github.com/NandangowdaKY/SLM-on-supermarket
* Data: [__HF_USER__/supermart-slm-data](https://huggingface.co/datasets/__HF_USER__/supermart-slm-data)

## Files

| File | Use |
|---|---|
| `model.safetensors`, `config.json`, tokenizer files | 🤗 transformers (`Qwen3ForCausalLM`, float32) |
| `supermart-slm-q8_0.gguf` | Ollama / llama.cpp (Q8_0, 367 MB) |
| `Modelfile` | Ollama import: ChatML template, system prompt, stop tokens |

## Architecture

| | |
|---|---|
| Type | decoder-only transformer, Qwen3 layout |
| Layers / hidden / FFN | 12 / 768 / 3072 (SwiGLU) |
| Attention | grouped-query, 12 query heads / 6 KV heads, head dim 64, QK-RMSNorm, RoPE θ = 10,000 |
| Vocabulary | Qwen3 BPE, 151,936 |
| Context | 512 tokens |
| Parameters | 339.6M (untied embedding and LM head) |

## Training (only our own data, single RTX 4050 Laptop GPU, 6 GB)

| Stage | Data | Steps | Final train loss | Final val loss |
|---|---|---|---|---|
| A — pre-training from scratch | 262,659 supermarket baskets written as text (90M-token corpus; 4,000 steps ≈ 33M tokens seen) | 4,000 | 0.455 | 0.529 |
| B — domain pre-training | 11 cleaned retail research papers + glossary + data insights | 800 | 1.317 | 6.635 (best 5.766) |
| C — chat fine-tuning (ChatML, loss on answers only) | 452 Q&A conversations, 223 facts computed from the data | 800 | 0.011 | 2.871 (best 1.927) |

AdamW 8-bit (β 0.9/0.95, wd 0.1), linear warm-up + cosine decay, bf16 autocast with fp32 master weights,
gradient checkpointing. About 7 hours in total. The final checkpoint of stage C is published.

## Evaluation

| Metric | Value |
|---|---|
| Stage A validation perplexity (13,825 held-out baskets) | 1.7 |
| Numeric fact recall, questions seen in training (sample of 50) | **95.3 %** |
| Numeric fact recall, never-seen questions (67 held-out conversations) | **4.8 %** |

*Numeric fact recall* = share of the numbers in the reference answer that the model reproduces (greedy decoding).
The model memorises its training facts almost perfectly but does not generalise to new facts.

## Use with Ollama

```bash
hf download __HF_USER__/supermart-slm supermart-slm-q8_0.gguf Modelfile --local-dir supermart-slm
cd supermart-slm
ollama create supermart-slm -f Modelfile
ollama run supermart-slm "Which departments generate the most sales?"
```

## Use with transformers

```python
from transformers import AutoTokenizer, AutoModelForCausalLM
tok = AutoTokenizer.from_pretrained("__HF_USER__/supermart-slm")
model = AutoModelForCausalLM.from_pretrained("__HF_USER__/supermart-slm")
system = "You are SuperMart SLM, a small language model trained from scratch to answer questions about supermarket retail analytics: sales, products, departments, discounts, baskets, customer demographics, gross margin, pricing, payment methods and tax. Answer concisely and use the numbers from the SuperMart transaction dataset when relevant."
msgs = [{"role": "system", "content": system},
        {"role": "user", "content": "What is the average basket size?"}]
ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt", return_dict=True)["input_ids"]
out = model.generate(ids, max_new_tokens=128, do_sample=False)
print(tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True))
```

## Example

> **Q:** What time of day do customers shop the most?
> **A:** Sales peak at 17:00-18:00 (10.3% of daily sales). The morning (6-12) brings 16.1%, afternoon (12-17) brings 40.7%, evening (17-22) brings 38.1% of sales.

## Limitations

A small model trained from scratch on a narrow domain. It reproduces the facts it was fine-tuned on exactly,
but invents confident wrong answers for questions outside them (held-out validation facts are not recalled).
Not for real business or financial decisions.
