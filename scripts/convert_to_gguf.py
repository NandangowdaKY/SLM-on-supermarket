"""
Convert the exported Qwen3ForCausalLM folder (slm/export.py output) into a GGUF file for Ollama /
llama.cpp, using only the `gguf` Python package (pip install gguf) - no llama.cpp checkout needed.

It writes the same metadata and tensor names as llama.cpp's convert_hf_to_gguf.py for the
"qwen3" architecture: matrices as Q8_0 (or F16), norm weights as F32, and the Qwen BPE tokenizer
("gpt2" model, "qwen2" pre-tokenizer) with the ChatML template.

Usage:
  python scripts/convert_to_gguf.py --hf export/supermart-slm --out ollama/supermart-slm-q8_0.gguf
"""
import argparse
import json
import os

import numpy as np
import gguf
from safetensors.numpy import load_file
from transformers import AutoTokenizer

TENSOR_MAP = {
    "self_attn.q_proj.weight": "attn_q.weight",
    "self_attn.k_proj.weight": "attn_k.weight",
    "self_attn.v_proj.weight": "attn_v.weight",
    "self_attn.o_proj.weight": "attn_output.weight",
    "self_attn.q_norm.weight": "attn_q_norm.weight",
    "self_attn.k_norm.weight": "attn_k_norm.weight",
    "mlp.gate_proj.weight": "ffn_gate.weight",
    "mlp.up_proj.weight": "ffn_up.weight",
    "mlp.down_proj.weight": "ffn_down.weight",
    "input_layernorm.weight": "attn_norm.weight",
    "post_attention_layernorm.weight": "ffn_norm.weight",
}


def gguf_name(hf_name):
    if hf_name == "model.embed_tokens.weight":
        return "token_embd.weight"
    if hf_name == "model.norm.weight":
        return "output_norm.weight"
    if hf_name == "lm_head.weight":
        return "output.weight"
    _, _, i, rest = hf_name.split(".", 3)          # model.layers.{i}.{rest}
    return f"blk.{i}.{TENSOR_MAP[rest]}"


def add_tokenizer(w, hf_dir, vocab_size):
    tok = AutoTokenizer.from_pretrained(hf_dir)
    vocab = tok.get_vocab()
    rev = {i: t for t, i in vocab.items()}
    added = tok.added_tokens_decoder                 # {id: AddedToken}
    tokens, types = [], []
    for i in range(vocab_size):
        if i not in rev:
            tokens.append(f"[PAD{i}]"); types.append(gguf.TokenType.UNUSED)
        elif i in added:
            tokens.append(added[i].content)
            types.append(gguf.TokenType.CONTROL if added[i].special else gguf.TokenType.USER_DEFINED)
        else:
            tokens.append(rev[i]); types.append(gguf.TokenType.NORMAL)

    tj = json.load(open(os.path.join(hf_dir, "tokenizer.json"), encoding="utf-8"))
    merges = [m if isinstance(m, str) else " ".join(m) for m in tj["model"]["merges"]]

    w.add_tokenizer_model("gpt2")
    w.add_tokenizer_pre("qwen2")                     # Qwen3 uses the Qwen2 pre-tokenizer regex
    w.add_token_list(tokens)
    w.add_token_types(types)
    w.add_token_merges(merges)
    w.add_bos_token_id(vocab["<|endoftext|>"])
    w.add_eos_token_id(vocab["<|im_end|>"])
    w.add_pad_token_id(vocab["<|endoftext|>"])
    w.add_add_bos_token(False)
    if tok.chat_template:
        w.add_chat_template(tok.chat_template)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hf", default="export/supermart-slm")
    ap.add_argument("--out", default="ollama/supermart-slm-q8_0.gguf")
    ap.add_argument("--outtype", default="q8_0", choices=["q8_0", "f16", "f32"])
    a = ap.parse_args()

    cfg = json.load(open(os.path.join(a.hf, "config.json")))
    arch = "qwen3"
    w = gguf.GGUFWriter(a.out, arch)
    w.add_name("SuperMart SLM")
    w.add_context_length(cfg["max_position_embeddings"])
    w.add_embedding_length(cfg["hidden_size"])
    w.add_block_count(cfg["num_hidden_layers"])
    w.add_feed_forward_length(cfg["intermediate_size"])
    w.add_head_count(cfg["num_attention_heads"])
    w.add_head_count_kv(cfg["num_key_value_heads"])
    w.add_key_length(cfg["head_dim"])
    w.add_value_length(cfg["head_dim"])
    w.add_rope_freq_base(cfg["rope_theta"])
    w.add_layer_norm_rms_eps(cfg["rms_norm_eps"])
    ftype = {"q8_0": gguf.LlamaFileType.MOSTLY_Q8_0, "f16": gguf.LlamaFileType.MOSTLY_F16,
             "f32": gguf.LlamaFileType.ALL_F32}[a.outtype]
    w.add_file_type(ftype)
    add_tokenizer(w, a.hf, cfg["vocab_size"])

    sd = load_file(os.path.join(a.hf, "model.safetensors"))
    for name, t in sd.items():
        data = t.astype(np.float32)
        if data.ndim == 1 or a.outtype == "f32":
            w.add_tensor(gguf_name(name), data)                     # norms stay F32
        elif a.outtype == "f16":
            w.add_tensor(gguf_name(name), data.astype(np.float16))
        else:
            q = gguf.quants.quantize(data, gguf.GGMLQuantizationType.Q8_0)
            w.add_tensor(gguf_name(name), q, raw_dtype=gguf.GGMLQuantizationType.Q8_0)

    w.write_header_to_file()
    w.write_kv_data_to_file()
    w.write_tensors_to_file()
    w.close()
    print(f"wrote {a.out} ({os.path.getsize(a.out) / 1e6:.0f} MB, {a.outtype})")


if __name__ == "__main__":
    main()
