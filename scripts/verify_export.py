"""
Check that slm/export.py produces a Hugging Face Qwen3ForCausalLM that is numerically
identical to our from-scratch model.

  python scripts/verify_export.py                       # tiny random model (CPU, seconds)
  python scripts/verify_export.py --ckpt checkpoints/supermart_sft.pt --hf export/supermart-slm
"""
import argparse
import os
import sys
import tempfile

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from slm.export import export, load_checkpoint, resize_vocab, QWEN3_VOCAB_SIZE  # noqa: E402
from slm.model import Qwen3Model  # noqa: E402


def compare(ckpt, hf_dir):
    from transformers import AutoModelForCausalLM
    sd, cfg = load_checkpoint(ckpt)
    if cfg["vocab_size"] < QWEN3_VOCAB_SIZE:
        sd, cfg["vocab_size"] = resize_vocab(sd, QWEN3_VOCAB_SIZE), QWEN3_VOCAB_SIZE
    ours = Qwen3Model(**cfg).float().eval()
    ours.load_state_dict({k: v.float() for k, v in sd.items()})
    hf = AutoModelForCausalLM.from_pretrained(hf_dir, dtype=torch.float32).eval()

    torch.manual_seed(0)
    ids = torch.randint(0, 151_000, (2, 48))
    with torch.no_grad():
        a, _ = ours(ids)
        b = hf(ids).logits
    diff = (a - b).abs().max().item()
    rel = diff / a.abs().max().item()
    same_argmax = (a.argmax(-1) == b.argmax(-1)).float().mean().item()
    print(f"max |logit diff| = {diff:.2e}  (relative {rel:.2e}),  next-token agreement = {same_argmax:.1%}")
    return rel, same_argmax


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt")
    ap.add_argument("--hf")
    a = ap.parse_args()
    if a.ckpt and a.hf:
        rel, agree = compare(a.ckpt, a.hf)
        ok = agree > 0.98            # bf16 export -> tiny rounding differences
    else:
        cfg = dict(vocab_size=QWEN3_VOCAB_SIZE, d_model=64, n_heads=4, n_kv_groups=2, n_layers=2,
                   d_ff=128, max_seq_len=64)
        torch.manual_seed(123)
        m = Qwen3Model(**cfg)
        for p in m.parameters():                           # randomise norms too
            torch.nn.init.normal_(p, std=0.2) if p.dim() > 1 else torch.nn.init.uniform_(p, 0.5, 1.5)
        with tempfile.TemporaryDirectory() as tmp:
            ck = os.path.join(tmp, "tiny.pt")
            torch.save({"model": m.state_dict(), "config": cfg}, ck)
            export(ck, os.path.join(tmp, "hf"), dtype="float32", save_tokenizer=False)
            rel, agree = compare(ck, os.path.join(tmp, "hf"))
        ok = rel < 1e-4 and agree == 1.0
    print("EXPORT OK" if ok else "EXPORT MISMATCH")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
