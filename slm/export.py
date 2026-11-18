"""
Export a trained checkpoint (.pt state_dict of slm.model.Qwen3Model) to a Hugging Face
`Qwen3ForCausalLM` folder (config.json + model.safetensors + tokenizer), which can be

  * loaded with transformers.AutoModelForCausalLM,
  * checked against the reference implementation (scripts/verify_export.py),
  * converted to GGUF with llama.cpp and imported into Ollama (ollama/Modelfile).

The only architectural difference to the HF implementation is that our model multiplies
the token embeddings by sqrt(d_model).  The LM head is not tied to the embedding, so the
factor is folded into the exported embedding matrix - the exported model is numerically
identical (verified by scripts/verify_export.py).

Usage:
  python -m slm.export --ckpt checkpoints/supermart_sft.pt --out export/supermart-slm
"""
import argparse
import json
import math
import os

import torch

from slm.model import DEFAULT_CONFIG, QWEN3_VOCAB_SIZE, resize_vocab

CHATML_TEMPLATE = (
    "{% for message in messages %}"
    "{{ '<|im_start|>' + message['role'] + '\n' + message['content'] + '<|im_end|>' + '\n' }}"
    "{% endfor %}"
    "{% if add_generation_prompt %}{{ '<|im_start|>assistant\n' }}{% endif %}"
)

TOKENIZER_REPO = "Qwen/Qwen3-0.6B"   # identical BPE vocabulary to Qwen3-8B used in training, much smaller download


def load_checkpoint(path):
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    if isinstance(ckpt, dict) and "model" in ckpt:              # {"model": sd, "config": {...}}
        return ckpt["model"], {**DEFAULT_CONFIG, **ckpt.get("config", {})}
    sd = ckpt                                                   # plain state_dict (original notebook)
    cfg = dict(DEFAULT_CONFIG)
    cfg["vocab_size"] = sd["tok_emb.weight"].shape[0]
    cfg["d_model"] = sd["tok_emb.weight"].shape[1]
    cfg["n_layers"] = len({k.split(".")[1] for k in sd if k.startswith("blocks.")})
    cfg["d_ff"] = sd["blocks.0.feed_forward.gate_proj.weight"].shape[0]
    hd = sd["blocks.0.attention.q_norm.weight"].shape[0]
    cfg["n_heads"] = sd["blocks.0.attention.W_query.weight"].shape[0] // hd
    cfg["n_kv_groups"] = sd["blocks.0.attention.W_key.weight"].shape[0] // hd
    return sd, cfg


def to_hf_state_dict(sd, cfg):
    scale = math.sqrt(cfg["d_model"])
    out = {
        "model.embed_tokens.weight": (sd["tok_emb.weight"].float() * scale),
        "model.norm.weight": sd["final_norm.weight"],
        "lm_head.weight": sd["out_head.weight"],
    }
    for i in range(cfg["n_layers"]):
        p, q = f"blocks.{i}.", f"model.layers.{i}."
        m = {
            "attention.W_query.weight": "self_attn.q_proj.weight",
            "attention.W_key.weight": "self_attn.k_proj.weight",
            "attention.W_value.weight": "self_attn.v_proj.weight",
            "attention.out_proj.weight": "self_attn.o_proj.weight",
            "attention.q_norm.weight": "self_attn.q_norm.weight",
            "attention.k_norm.weight": "self_attn.k_norm.weight",
            "feed_forward.gate_proj.weight": "mlp.gate_proj.weight",
            "feed_forward.up_proj.weight": "mlp.up_proj.weight",
            "feed_forward.down_proj.weight": "mlp.down_proj.weight",
            "norm1.weight": "input_layernorm.weight",
            "norm2.weight": "post_attention_layernorm.weight",
        }
        for a, b in m.items():
            out[q + b] = sd[p + a]
    return out


def hf_config(cfg, dtype="bfloat16"):
    return {
        "architectures": ["Qwen3ForCausalLM"],
        "model_type": "qwen3",
        "vocab_size": cfg["vocab_size"],
        "hidden_size": cfg["d_model"],
        "intermediate_size": cfg["d_ff"],
        "num_hidden_layers": cfg["n_layers"],
        "num_attention_heads": cfg["n_heads"],
        "num_key_value_heads": cfg["n_kv_groups"],
        "head_dim": cfg["d_model"] // cfg["n_heads"],
        "hidden_act": "silu",
        "max_position_embeddings": cfg["max_seq_len"],
        "rms_norm_eps": 1e-6,
        "rope_theta": cfg.get("rope_theta", 10_000.0),
        "rope_scaling": None,
        "attention_bias": False,
        "attention_dropout": 0.0,
        "tie_word_embeddings": False,
        "use_cache": True,
        "use_sliding_window": False,
        "sliding_window": None,
        "max_window_layers": cfg["n_layers"],
        "initializer_range": 0.02,
        "bos_token_id": 151643,
        "eos_token_id": 151645,
        "torch_dtype": dtype,
    }


def export(ckpt_path, out_dir, dtype="bfloat16", tokenizer_repo=TOKENIZER_REPO, save_tokenizer=True):
    from safetensors.torch import save_file

    sd, cfg = load_checkpoint(ckpt_path)
    if cfg["vocab_size"] < QWEN3_VOCAB_SIZE:      # old 151,643-row checkpoint -> pad for GGUF/chat tokens
        sd = resize_vocab(sd, QWEN3_VOCAB_SIZE)
        cfg["vocab_size"] = QWEN3_VOCAB_SIZE
    tdtype = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}[dtype]
    hf_sd = {k: v.to(tdtype).contiguous() for k, v in to_hf_state_dict(sd, cfg).items()}

    os.makedirs(out_dir, exist_ok=True)
    save_file(hf_sd, os.path.join(out_dir, "model.safetensors"), metadata={"format": "pt"})
    with open(os.path.join(out_dir, "config.json"), "w") as f:
        json.dump(hf_config(cfg, dtype), f, indent=2)
    with open(os.path.join(out_dir, "generation_config.json"), "w") as f:
        json.dump({"bos_token_id": 151643, "eos_token_id": [151645, 151643], "pad_token_id": 151643,
                   "do_sample": True, "temperature": 0.3, "top_p": 0.9, "repetition_penalty": 1.1,
                   "max_new_tokens": 256}, f, indent=2)

    if save_tokenizer:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(tokenizer_repo)
        tok.chat_template = CHATML_TEMPLATE        # plain ChatML, exactly the SFT format (no <think> blocks)
        tok.eos_token = "<|im_end|>"
        tok.pad_token = "<|endoftext|>"
        tok.save_pretrained(out_dir)

    n = sum(v.numel() for v in hf_sd.values())
    print(f"exported {n / 1e6:.1f}M parameters -> {out_dir}")
    return out_dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--out", default="export/supermart-slm")
    ap.add_argument("--dtype", default="bfloat16", choices=["bfloat16", "float16", "float32"])
    a = ap.parse_args()
    export(a.ckpt, a.out, a.dtype)
